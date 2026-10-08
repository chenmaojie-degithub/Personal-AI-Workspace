from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.orchestrator import cancel_agent_run, run_agent, should_run_agent
from app.api.routes.chat_stream import _routed_events
from app.core import database
from app.models.chat import ChatMessage, ChatRequest, ChatSettings
from app.providers.base import LLMResponse, LLMUsage, ProviderToolCall


def response(content: str, calls: tuple[ProviderToolCall, ...] = (), tokens: int = 10) -> LLMResponse:
    return LLMResponse(content, calls, "test-model", "test-provider", LLMUsage(tokens - 2, 2, tokens))


class Provider:
    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.tools: list[list[dict] | None] = []

    def complete(self, messages, tools=None):
        self.tools.append(tools)
        return self.responses.pop(0)


class AgentOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        path = (Path(self.temp_dir.name) / "agent.sqlite3").as_posix()
        self.setting = patch.object(database.settings, "database_url", f"sqlite:///{path}")
        self.setting.start()

    def tearDown(self) -> None:
        self.setting.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def request(content: str, **tool_settings: bool) -> ChatRequest:
        return ChatRequest(
            session_id="agent-session",
            messages=[ChatMessage(role="user", content=content)],
            settings=ChatSettings(**tool_settings),
        )

    def test_simple_question_stays_on_direct_chat_path(self) -> None:
        self.assertFalse(should_run_agent(self.request("What is Docker?")))
        self.assertTrue(should_run_agent(self.request("Research and compare the latest web news")))

    def test_complex_request_is_dispatched_through_agent_sse(self) -> None:
        with patch("app.api.routes.chat_stream.run_agent", return_value=iter([
            ("agent_status", {"run_id": "run-1", "status": "completed"}),
        ])):
            output = list(_routed_events(self.request("Research and compare sources")))
        self.assertIn("event: agent_status", output[0])

    def test_two_tools_observations_and_usage_are_persisted(self) -> None:
        search = ProviderToolCall("call-1", "search_web", '{"query":"release"}')
        analyze = ProviderToolCall("call-2", "analyze_data", '{"file_id":"sales.csv","operation":"shape"}')
        provider = Provider(
            response('{"steps":["Find current evidence","Inspect the data"]}', tokens=5),
            response("", (search,), 7),
            response("", (analyze,), 11),
            response("Final comparison", tokens=13),
        )
        req = self.request("Compare latest web news with sales.csv data", web_search=True, data_analysis=True)
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.tools.web_search.search_web", return_value=[{"title": "Real", "url": "https://example.com", "snippet": "Evidence"}]
        ), patch("app.tools.data_analysis.analyze_data", return_value={"type": "table", "rows": 3}), patch(
            "app.agents.orchestrator.resolve_model"
        ) as model:
            model.return_value.supports_tools = True
            events = list(run_agent(req))

        self.assertEqual([data["status"] for event, data in events if event == "agent_step"], ["running", "completed", "running", "completed"])
        self.assertEqual([event for event, _ in events].count("tool_call"), 2)
        self.assertEqual([data["type"] for event, data in events if event == "source"], ["web"])
        self.assertEqual([data for event, data in events if event == "message"][0]["content"], "Final comparison")
        run_id = next(data["run_id"] for event, data in events if event == "agent_run")
        stored = database.get_agent_run(run_id)
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["total_tokens"], 36)
        self.assertEqual(len(stored["steps"]), 2)

    def test_tool_failure_is_an_observation_and_does_not_crash(self) -> None:
        call = ProviderToolCall("call-1", "search_web", '{"query":"blocked"}')
        provider = Provider(response('{"steps":["Search"]}'), response("", (call,)), response("Explain failure"))
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.tools.web_search.search_web", side_effect=RuntimeError("network blocked")
        ), patch("app.agents.orchestrator.resolve_model") as model:
            model.return_value.supports_tools = True
            events = list(run_agent(self.request("Research the latest web report", web_search=True)))
        self.assertTrue(any(event == "agent_step" and data["status"] == "failed" for event, data in events))
        self.assertTrue(any(event == "message" and data["content"] == "Explain failure" for event, data in events))
        self.assertFalse(any(event == "error" for event, _ in events))

    def test_workspace_tool_switch_prevents_registration(self) -> None:
        provider = Provider(response('{"steps":["Search"]}'), response("Cannot search"))
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider):
            events = list(run_agent(self.request("Research and compare web sources", web_search=False)))
        self.assertIsNone(provider.tools[1])
        self.assertFalse(any(event == "tool_call" for event, _ in events))
        self.assertTrue(any(event == "message" and data["content"] == "Cannot search" for event, data in events))

    def test_closing_stream_cancels_run_before_more_work(self) -> None:
        provider = Provider(response('{"steps":["Search"]}'))
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider):
            iterator = run_agent(self.request("Research and compare sources"))
            event, data = next(iterator)
            self.assertEqual(event, "agent_run")
            iterator.close()
        self.assertEqual(database.get_agent_run(data["run_id"])["status"], "cancelled")
        self.assertEqual(provider.responses, [response('{"steps":["Search"]}')])

    def test_cancel_endpoint_signal_stops_before_tool_execution(self) -> None:
        provider = Provider(response('{"steps":["Search"]}'))
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider):
            iterator = run_agent(self.request("Research and compare sources"))
            _, started = next(iterator)
            cancelled = cancel_agent_run(started["run_id"], database.DEFAULT_WORKSPACE_ID)
            remaining = list(iterator)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(any(event == "agent_status" and data["status"] == "cancelled" for event, data in remaining))
        self.assertFalse(any(event == "tool_call" for event, _ in remaining))

    def test_agent_run_routes_are_workspace_scoped(self) -> None:
        run = database.create_agent_run("route-run", "route-session", database.DEFAULT_WORKSPACE_ID, "Goal")
        from fastapi.testclient import TestClient
        from app.main import create_app

        client = TestClient(create_app())
        latest = client.get("/agent-runs/latest", params={
            "session_id": "route-session", "workspace_id": database.DEFAULT_WORKSPACE_ID,
        })
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["id"], run["id"])
        self.assertEqual(client.get("/agent-runs/route-run", params={"workspace_id": "wrong"}).status_code, 404)

    def test_model_call_budget_returns_partial_answer(self) -> None:
        call = ProviderToolCall("call-1", "search_web", '{"query":"repeat"}')
        provider = Provider(response('{"steps":["Search"]}'), *(response("", (call,)) for _ in range(3)))
        req = self.request("Research and compare web sources", web_search=True)
        with patch.object(database.settings, "agent_max_model_calls", 3), patch(
            "app.agents.orchestrator.create_llm_provider", return_value=provider
        ), patch("app.tools.web_search.search_web", return_value=[]), patch(
            "app.agents.orchestrator.resolve_model"
        ) as model:
            model.return_value.supports_tools = True
            events = list(run_agent(req))
        status = next(data for event, data in events if event == "agent_status")
        self.assertEqual(status["status"], "budget_exceeded")
        self.assertEqual(status["reason"], "model_call_budget")
        self.assertTrue(any(event == "message" for event, _ in events))

    def test_tool_step_budget_stops_after_configured_limit(self) -> None:
        calls = tuple(
            ProviderToolCall(f"call-{index}", "search_web", f'{{"query":"query {index}"}}')
            for index in range(1, 4)
        )
        provider = Provider(
            response('{"steps":["First","Second"]}'),
            response("", calls),
            response("Partial result"),
        )
        with patch.object(database.settings, "agent_max_tool_steps", 2), patch(
            "app.agents.orchestrator.create_llm_provider", return_value=provider
        ), patch("app.tools.web_search.search_web", return_value=[]), patch(
            "app.agents.orchestrator.resolve_model"
        ) as model:
            model.return_value.supports_tools = True
            events = list(run_agent(self.request("Research and compare web sources", web_search=True)))
        self.assertEqual(len([1 for event, data in events if event == "agent_step" and data["status"] == "completed"]), 2)
        status = next(data for event, data in events if event == "agent_status")
        self.assertEqual((status["status"], status["reason"]), ("budget_exceeded", "tool_step_budget"))


if __name__ == "__main__":
    unittest.main()
