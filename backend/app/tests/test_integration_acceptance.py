"""Initialization error regression: disposable SQLite and no model calls."""
import json
import asyncio

from fastapi.testclient import TestClient
import pytest

from app.core import database
from app.core.config import settings
from app.main import create_app
from app.models.chat import ChatRequest
from app.api.routes import chat_stream


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("prompt", ["Hello", "Research and compare web sources"])
def test_missing_workspace_has_structured_error_without_partial_run(tmp_path, monkeypatch, streaming, prompt):
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + (tmp_path / "business.sqlite3").as_posix())
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    calls = []
    def forbidden(*args):
        calls.append(True)
        raise AssertionError("Invalid Workspace must not call a model")
    for module in ("app.api.routes.chat", "app.api.routes.chat_stream", "app.agents.orchestrator"):
        monkeypatch.setattr(module + ".create_llm_provider", forbidden)
    with TestClient(create_app()) as client:
        response = client.post("/chat/stream" if streaming else "/chat", json={
            "workspace_id": "synthetic-missing", "session_id": "invalid-workspace",
            "messages": [{"role": "user", "content": prompt}],
        })
    assert response.status_code == 200
    if streaming:
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.text.startswith("event: error\n") and "event: done" not in response.text
        assert "Workspace not found" in json.loads(response.text.split("data: ", 1)[1])["message"]
    else:
        assert "Workspace not found" in response.json()["error"]
    assert calls == []
    assert database.list_messages("invalid-workspace") == []
    assert database.latest_agent_run("invalid-workspace", "synthetic-missing") is None


def consume_events(monkeypatch, source, layer, mode):
    """Exercise the real routing or ASGI boundary with the same iterator contract."""
    request = ChatRequest(messages=[{"role": "user", "content": "hello"}])
    if layer == "routed":
        monkeypatch.setattr(chat_stream, "should_run_agent", lambda _: True)
        monkeypatch.setattr(chat_stream, "run_agent", lambda _: source)
        events = chat_stream._routed_events(request)
        assert next(events).startswith("event: message")
        if mode == "close":
            events.close()
        elif mode == "error":
            next(events)
        else:
            assert len(list(events)) == 1
        return

    monkeypatch.setattr(chat_stream, "_routed_events", lambda _: source)
    async def consume():
        events = chat_stream._stream_with_cleanup(request)
        assert await anext(events) == ("message", {"content": "one"})
        if mode == "close":
            await events.aclose()
        elif mode == "error":
            await anext(events)
        else:
            assert [item async for item in events] == [("message", {"content": "two"})]
    asyncio.run(consume())


@pytest.mark.parametrize("layer", ["routed", "asgi"])
@pytest.mark.parametrize("mode", ["complete", "close", "error"])
def test_iterator_cleanup_is_explicit_on_all_exits(monkeypatch, layer, mode):
    closed = []
    def source():
        try:
            yield "message", {"content": "one"}
            if mode == "error":
                raise RuntimeError("Synthetic failure")
            yield "message", {"content": "two"}
        finally:
            closed.append(True)
    if mode == "error":
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            consume_events(monkeypatch, source(), layer, mode)
    else:
        consume_events(monkeypatch, source(), layer, mode)
    assert closed == [True]


@pytest.mark.parametrize("layer", ["routed", "asgi"])
@pytest.mark.parametrize("mode", ["complete", "close"])
def test_plain_list_iterator_needs_no_close(monkeypatch, layer, mode):
    consume_events(monkeypatch, iter([
        ("message", {"content": "one"}), ("message", {"content": "two"}),
    ]), layer, mode)


@pytest.mark.parametrize("layer", ["routed", "asgi"])
@pytest.mark.parametrize("close_attribute", [None, "not callable"])
@pytest.mark.parametrize("mode", ["complete", "close", "error"])
def test_noncallable_close_is_ignored(monkeypatch, layer, close_attribute, mode):
    class Iterator:
        close = close_attribute

        def __init__(self):
            self.items = iter([("message", {"content": "one"}), ("message", {"content": "two"})])
            self.started = False

        def __iter__(self):
            return self

        def __next__(self):
            if self.started and mode == "error":
                raise RuntimeError("Synthetic failure")
            self.started = True
            return next(self.items)

    if mode == "error":
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            consume_events(monkeypatch, Iterator(), layer, mode)
    else:
        consume_events(monkeypatch, Iterator(), layer, mode)


@pytest.mark.parametrize("layer", ["routed", "asgi"])
@pytest.mark.parametrize("mode", ["complete", "close", "error"])
def test_generator_cleanup_errors_are_not_swallowed(monkeypatch, layer, mode):
    def source():
        try:
            yield "message", {"content": "one"}
            if mode == "error":
                raise ValueError("Iteration failed first")
            yield "message", {"content": "two"}
        finally:
            raise RuntimeError("Cleanup failed")

    # Closing a real generator must surface its finally error on every exit path.
    with pytest.raises(RuntimeError, match="Cleanup failed") as error:
        consume_events(monkeypatch, source(), layer, mode)
    if mode == "error":
        assert isinstance(error.value.__context__, ValueError)
        assert str(error.value.__context__) == "Iteration failed first"
