"""Initialization error regression: disposable SQLite and no model calls."""
import json

from fastapi.testclient import TestClient
import pytest

from app.core import database
from app.core.config import settings
from app.main import create_app


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
