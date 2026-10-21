"""Deterministic measurements and persisted/SSE metrics; no real providers or user DB."""
import json
import pytest
from fastapi.testclient import TestClient

from app.agents.observability import RunObservation
from app.agents.orchestrator import cancel_agent_run, run_agent
from app.core import database
from app.main import app
from app.models.chat import ChatRequest
from app.providers.base import LLMResponse, LLMStreamEvent, LLMUsage, ProviderToolCall
from app.providers.text_tool_calls import TextToolCallError


class Clock:
    value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Provider:
    def __init__(self, clock, *, fail=None, missing_usage=False):
        self.clock, self.fail, self.missing_usage = clock, fail, missing_usage
        self.calls = 0
        self.closed = False
        self.extra_delta = False

    def complete(self, messages, tools=None, max_tokens=None):
        self.calls += 1
        self.clock.advance(1.25)
        if self.fail == self.calls:
            raise RuntimeError("Private provider response: must not enter metrics")
        content = '{"steps":["Search","Answer"]}' if self.calls == 1 else "FINAL_READY"
        calls = (ProviderToolCall("tool-1", "search_web", '{"query":"offline"}'),) if self.calls == 2 else ()
        return LLMResponse(content, calls, "mock-model", "offline", None if self.missing_usage else LLMUsage(8, 2, 10))

    def stream(self, messages, tools=None, max_tokens=None):
        try:
            self.clock.advance(2)
            yield LLMStreamEvent("message", content="\n")
            self.clock.advance(0.5)
            yield LLMStreamEvent("message", content="answer")
            if self.extra_delta:
                yield LLMStreamEvent("message", content=" more")
            if self.fail == "stream":
                raise RuntimeError("Private stream error")
            self.clock.advance(1)
            if not self.missing_usage:
                yield LLMStreamEvent("usage", usage=LLMUsage(5, 1, 6))
            yield LLMStreamEvent("done", model="mock-model", provider="offline")
        finally:
            self.closed = True


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(database.settings, "database_url", "sqlite:///" + (tmp_path / "metrics.db").as_posix())
    clock = Clock()
    monkeypatch.setattr("app.agents.orchestrator.RunObservation", lambda started: RunObservation(clock=clock))
    provider = Provider(clock)
    monkeypatch.setattr("app.agents.orchestrator.create_llm_provider", lambda *args: provider)
    monkeypatch.setattr("app.agents.orchestrator.resolve_model", lambda *args: type("Model", (), {"supports_tools": True})())
    def tool(query):
        clock.advance(2)
        return {"results": []}
    monkeypatch.setattr("app.tools.registry.web_search", tool)
    request = ChatRequest(session_id="metrics-session", settings={"web_search": True}, messages=[
        {"role": "user", "content": "Research and compare latest web sources"},
    ])
    return clock, provider, request


def stored(events):
    run_id = next(data["run_id"] for event, data in events if event == "agent_run")
    run = database.get_agent_run(run_id)
    assert run["metrics"] == [data["metrics"] for event, data in events if event == "agent_metrics"][-1]
    assert run["metrics"]["finished"]
    assert run["metrics"]["cost_usd"] is None
    assert "Private" not in json.dumps(run["metrics"])
    return run


def test_completed_run_has_exact_monotonic_times_and_usage(harness):
    _, provider, request = harness
    events = list(run_agent(request))
    run = stored(events)
    metrics = run["metrics"]
    assert run["status"] == "completed"
    assert metrics["duration_ms"] == 9250
    assert metrics["ttft_ms"] == 8250  # Ignores the whitespace-only delta.
    assert metrics["model_call_count"] == 4
    assert metrics["model_duration_ms"] == 7250
    assert metrics["tool_duration_ms"] == run["steps"][0]["duration_ms"] == 2000
    assert metrics["usage"] == {"prompt_tokens": 29, "completion_tokens": 7, "total_tokens": 36}
    assert [call["stage"] for call in metrics["model_calls"]] == ["planning", "action_selection", "replanning", "final_answer"]
    assert metrics["failure_type"] is None
    assert provider.closed
    assert len(database.list_messages(request.session_id)) == 2


def test_recovered_tool_failure_has_duration_and_type(harness, monkeypatch):
    clock, _, request = harness
    def failed(query):
        clock.advance(3)
        raise ValueError("Private document data")
    monkeypatch.setattr("app.tools.registry.web_search", failed)
    run = stored(list(run_agent(request)))
    assert run["status"] == "completed"
    tool = run["metrics"]["tools"][0]
    assert (tool["stage"], tool["status"], tool["error_type"], tool["duration_ms"]) == ("tool", "failed", "ValueError", 3000)
    assert run["metrics"]["failure_type"] is None  # Recovered; not a terminal failure.
    assert "Private" not in json.dumps(run["metrics"])


@pytest.mark.parametrize("failure,stage,count", [(1, "planning", 1), (2, "action_selection", 2), ("stream", "final_answer", 4)])
def test_llm_failures_count_attempts_and_keep_unknown_usage(harness, failure, stage, count):
    _, provider, request = harness
    provider.fail = failure
    run = stored(list(run_agent(request)))
    metrics = run["metrics"]
    assert run["status"] == "failed"
    assert (metrics["failure_stage"], metrics["failure_type"]) == (stage, "RuntimeError")
    assert metrics["model_call_count"] == count
    assert metrics["usage"] is None and run["total_tokens"] is None
    assert metrics["model_calls"][-1]["status"] == "failed"
    assert not database.list_messages(request.session_id)


@pytest.mark.parametrize("usage_arrives_before_cancel_check", [False, True])
def test_cancel_during_stream_persists_metrics_without_partial_chat(harness, usage_arrives_before_cancel_check):
    _, provider, request = harness
    provider.extra_delta = not usage_arrives_before_cancel_check
    iterator = run_agent(request)
    events = []
    for event, data in iterator:
        events.append((event, data))
        if event == "message" and data["content"].strip():
            run_id = next(data["run_id"] for event, data in events if event == "agent_run")
            cancel_agent_run(run_id, database.DEFAULT_WORKSPACE_ID)
            break
    events.extend(iterator)
    run = stored(events)
    assert run["status"] == "cancelled"
    assert run["metrics"]["failure_type"] == "user_cancelled"
    assert run["metrics"]["failure_stage"] == "final_answer"
    assert run["metrics"]["model_call_count"] == 4
    if usage_arrives_before_cancel_check:
        assert run["metrics"]["usage"]["total_tokens"] == 36
    else:
        assert run["metrics"]["usage"] is None
    assert provider.closed and not database.list_messages(request.session_id)


def test_token_budget_termination_is_distinct_from_provider_failure(harness, monkeypatch):
    _, _, request = harness
    monkeypatch.setattr(database.settings, "agent_token_budget", 10)
    run = stored(list(run_agent(request)))
    assert run["status"] == "budget_exceeded"
    assert (run["metrics"]["failure_stage"], run["metrics"]["failure_type"]) == ("budget", "token_budget")
    assert run["metrics"]["model_call_count"] == 1
    assert run["metrics"]["usage"]["total_tokens"] == 10


def test_missing_usage_is_null_not_zero_or_budget_estimate(harness):
    _, provider, request = harness
    provider.missing_usage = True
    events = list(run_agent(request))
    run = stored(events)
    assert run["status"] == "completed"
    assert run["metrics"]["usage"] is None and run["total_tokens"] is None
    assert run["metrics"]["budget_tokens_estimated"]
    assert [data for event, data in events if event == "usage"] == [None]


def test_rejected_call_and_repair_are_counted_without_inventing_usage(harness, monkeypatch):
    clock, _, request = harness
    class RepairProvider(Provider):
        def complete(self, messages, tools=None, max_tokens=None):
            if self.calls == 1:
                self.calls += 1
                clock.advance(1.25)
                raise TextToolCallError("invalid_syntax_or_schema")
            if self.calls == 2:
                self.calls += 1
                clock.advance(1.25)
                return LLMResponse("", (ProviderToolCall("repair", "search_web", '{"query":"offline"}'),), usage=LLMUsage(8, 2, 10))
            return super().complete(messages, tools, max_tokens)
    provider = RepairProvider(clock)
    monkeypatch.setattr("app.agents.orchestrator.create_llm_provider", lambda *args: provider)
    events = list(run_agent(request))
    run = stored(events)
    assert run["status"] == "completed"
    assert run["metrics"]["model_call_count"] == 5
    assert run["metrics"]["model_calls"][1]["error_type"] == "TextToolCallError"
    assert run["metrics"]["model_calls"][2]["stage"] == "tool_call_repair"
    assert run["metrics"]["usage"] is None
    assert [data for event, data in events if event == "usage"] == [None]


def test_ttft_waits_for_citation_validation_not_raw_model_delta(harness, monkeypatch):
    clock, provider, request = harness
    monkeypatch.setattr("app.tools.registry.web_search", lambda query: {"results": [
        {"title": "Evidence", "url": "https://example.com", "snippet": "evidence"},
    ]})
    def stream(messages, tools=None, max_tokens=None):
        catalog = json.loads(messages[-1]["content"].split(": ", 1)[1].split("\n", 1)[0])
        marker = catalog[0]["marker"]
        clock.advance(2)
        yield LLMStreamEvent("message", content=marker[:8])
        clock.advance(3)
        yield LLMStreamEvent("message", content=marker[8:])
        yield LLMStreamEvent("usage", usage=LLMUsage(5, 1, 6))
        yield LLMStreamEvent("done")
    provider.stream = stream
    events = list(run_agent(request))
    run = stored(events)
    assert run["metrics"]["ttft_ms"] == 8750  # 3*1250 + 5000; raw first delta was earlier.
    assert [data["content"] for event, data in events if event == "message"] == ["【1】"]


def test_disconnect_before_any_model_call_is_saved_without_emitting_more(harness):
    _, provider, request = harness
    iterator = run_agent(request)
    _, data = next(iterator)
    iterator.close()
    metrics = database.get_agent_run(data["run_id"])["metrics"]
    assert metrics["failure_type"] == "client_disconnected"
    assert metrics["ttft_ms"] is None and metrics["usage"] is None
    assert metrics["model_call_count"] == 0 and metrics["finished"]
    assert provider.calls == 0


def test_old_plan_arrays_and_new_metrics_survive_plan_updates(harness):
    database.create_agent_run("old", "old-session", database.DEFAULT_WORKSPACE_ID, "old")
    assert database.get_agent_run("old")["metrics"] is None
    database.update_agent_run("old", plan=[{"index": 1, "title": "old step"}])
    observation = RunObservation(clock=Clock())
    metrics = observation.snapshot(0)
    database.update_agent_run("old", metrics=metrics)
    plan = [{"index": 1, "title": "updated step"}]
    database.update_agent_run("old", plan=plan)
    assert database.get_agent_run("old")["metrics"] == metrics
    database.update_agent_run("old", metrics=observation.snapshot(1))
    assert database.get_agent_run("old")["plan"] == plan


def test_http_sse_metrics_match_details_and_workspace_scope(harness):
    _, _, request = harness
    with TestClient(app) as client:
        response = client.post("/chat/stream", json=request.model_dump())
        assert response.status_code == 200
        blocks = response.text.strip().split("\n\n")
        events = [(block.splitlines()[0][7:], json.loads(block.split("data: ", 1)[1])) for block in blocks]
        run = stored(events)
        details = client.get(f"/agent-runs/{run['id']}", params={"workspace_id": database.DEFAULT_WORKSPACE_ID})
        assert details.json()["metrics"] == run["metrics"]
        assert client.get(f"/agent-runs/{run['id']}", params={"workspace_id": "other"}).status_code == 404
