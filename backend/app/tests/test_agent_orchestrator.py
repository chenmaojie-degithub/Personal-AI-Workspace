from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.orchestrator import cancel_agent_run, run_agent, should_run_agent
from app.api.routes.chat import orchestrate_request
from app.api.routes.chat_stream import _routed_events
from app.core import database
from app.models.chat import ChatMessage, ChatRequest, ChatSettings
from app.providers.base import LLMResponse, LLMStreamEvent, LLMUsage, ProviderToolCall


def response(content: str, calls: tuple[ProviderToolCall, ...] = (), tokens: int = 10) -> LLMResponse:
    return LLMResponse(content, calls, "test-model", "test-provider", LLMUsage(tokens - 2, 2, tokens))


class Provider:
    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.tools: list[list[dict] | None] = []
        self.max_tokens: list[int | None] = []

    def complete(self, messages, tools=None, max_tokens=None):
        self.tools.append(tools)
        self.max_tokens.append(max_tokens)
        return self.responses.pop(0)


class StreamingProvider(Provider):
    def __init__(self, *responses: LLMResponse, stream_events: list[LLMStreamEvent]) -> None:
        super().__init__(*responses)
        self.stream_events = stream_events
        self.stream_max_tokens: list[int | None] = []

    def stream(self, messages, tools=None, max_tokens=None):
        self.stream_max_tokens.append(max_tokens)
        yield from self.stream_events


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
        self.assertEqual(database.settings.agent_max_tool_steps, 4)
        self.assertFalse(should_run_agent(self.request("What is Docker?")))
        self.assertTrue(should_run_agent(self.request("Research and compare the latest web news")))

    def test_routing_uses_task_shape_and_recent_context(self) -> None:
        attached = self.request("Use the attached evidence and current online sources to verify the claim")
        attached.document_ids = ["doc-1"]
        self.assertTrue(should_run_agent(attached))
        self.assertFalse(should_run_agent(self.request("What does annual report mean?")))
        self.assertTrue(should_run_agent(self.request("请 compare 附件与 latest news")))
        follow_up = ChatRequest(messages=[
            ChatMessage(role="user", content="I uploaded a document about the launch."),
            ChatMessage(role="assistant", content="Understood."),
            ChatMessage(role="user", content="Now compare it with current news."),
        ])
        self.assertTrue(should_run_agent(follow_up))
        self.assertTrue(should_run_agent(self.request("Search the web and then summarize the two strongest sources")))

    def test_complex_request_is_dispatched_through_agent_sse(self) -> None:
        with patch("app.api.routes.chat_stream.run_agent", return_value=iter([
            ("agent_status", {"run_id": "run-1", "status": "completed"}),
        ])):
            output = list(_routed_events(self.request("Research and compare sources")))
        self.assertIn("event: agent_status", output[0])

    def test_simple_non_streaming_request_keeps_direct_path(self) -> None:
        expected = object()
        with patch("app.api.routes.chat.orchestrate_chat", return_value=expected) as direct, patch(
            "app.agents.orchestrator.run_agent"
        ) as agent:
            result = orchestrate_request(self.request("What is Docker?"))
        self.assertIs(result, expected)
        direct.assert_called_once()
        agent.assert_not_called()

    def test_complex_non_streaming_request_uses_agent_and_adapts_events(self) -> None:
        events = iter([
            ("agent_run", {"run_id": "run-1", "session_id": "agent-session", "status": "planning"}),
            ("tool_call", {"name": "search_web", "input": {"query": "release"}}),
            ("source", {"type": "web", "title": "Release", "url": "https://example.com/release"}),
            ("message", {"content": "Final "}),
            ("message", {"content": "answer"}),
            ("usage", {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}),
            ("agent_status", {"run_id": "run-1", "status": "completed", "reason": None}),
            ("done", {"session_id": "agent-session", "agent_run_id": "run-1"}),
        ])
        with patch("app.agents.orchestrator.run_agent", return_value=events) as agent:
            result = orchestrate_request(self.request("Research and compare sources"))
        agent.assert_called_once()
        self.assertEqual(result.session_id, "agent-session")
        self.assertEqual(result.assistant_message.content, "Final answer")
        self.assertEqual(result.tool_calls[0].name, "search_web")
        self.assertEqual(result.sources[0].type, "web")
        self.assertEqual(result.usage.total_tokens, 25)
        self.assertIsNone(result.error)

    def test_final_answer_streams_and_is_saved_once_after_completion(self) -> None:
        call = ProviderToolCall("call-1", "search_web", '{"query":"release"}')
        provider = StreamingProvider(
            response('{"steps":["Search","Answer"]}'),
            response("", (call,)),
            response("FINAL_READY"),
            stream_events=[
                LLMStreamEvent("message", content="Final "),
                LLMStreamEvent("message", content="answer"),
                LLMStreamEvent("usage", usage=LLMUsage(12, 3, 15)),
                LLMStreamEvent("done", model="test-model", provider="test-provider"),
            ],
        )
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.tools.registry.web_search",
            return_value={"query": "release", "results": [{"title": "Real", "url": "https://example.com", "snippet": "Evidence"}]},
        ), patch("app.agents.orchestrator.resolve_model") as model, patch(
            "app.agents.orchestrator.save_chat_turn"
        ) as save:
            model.return_value.supports_tools = True
            events = list(run_agent(self.request("Research and compare current web sources", web_search=True)))

        self.assertEqual([data["content"] for event, data in events if event == "message"], ["Final ", "answer"])
        self.assertEqual([data["type"] for event, data in events if event == "source"], ["web"])
        self.assertEqual([data for event, data in events if event == "usage"][-1]["total_tokens"], 45)
        self.assertTrue(provider.stream_max_tokens[0] > 0)
        save.assert_called_once()
        self.assertEqual(save.call_args.args[2], "Final answer")

    def test_cancel_during_final_stream_does_not_save_partial_answer(self) -> None:
        provider = StreamingProvider(
            response('{"steps":["Answer"]}'), response("FINAL_READY"),
            stream_events=[
                LLMStreamEvent("message", content="Partial"),
                LLMStreamEvent("message", content=" answer"),
                LLMStreamEvent("done", model="test-model", provider="test-provider"),
            ],
        )
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.agents.orchestrator.save_chat_turn"
        ) as save:
            iterator = run_agent(self.request("Research current web sources", web_search=True))
            seen = []
            for item in iterator:
                seen.append(item)
                if item[0] == "message":
                    break
            run_id = next(data["run_id"] for event, data in seen if event == "agent_run")
            cancel_agent_run(run_id, database.DEFAULT_WORKSPACE_ID)
            remaining = list(iterator)
        self.assertTrue(any(event == "agent_status" and data["status"] == "cancelled" for event, data in remaining))
        save.assert_not_called()

    def test_two_tools_observations_and_usage_are_persisted(self) -> None:
        search = ProviderToolCall("call-1", "search_web", '{"query":"release"}')
        analyze = ProviderToolCall("call-2", "analyze_data", '{"file_id":"sales.csv","operation":"shape"}')
        class AdaptiveProvider(Provider):
            def complete(self, messages, tools=None, max_tokens=None):
                if len(self.tools) == 2:
                    self.assert_observation(messages, "Evidence")
                if len(self.tools) == 3:
                    self.assert_observation(messages, '"rows": 3')
                return super().complete(messages, tools, max_tokens)

            @staticmethod
            def assert_observation(messages, expected):
                assert any(item.get("role") == "tool" and expected in item.get("content", "") for item in messages)

        provider = AdaptiveProvider(
            response('{"steps":["Find current evidence","Inspect the data"]}', tokens=5),
            response("", (search,), 7), response("", (analyze,), 11), response("Final comparison", tokens=13),
        )
        req = self.request("Compare latest web news with sales.csv data", web_search=True, data_analysis=True)
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.tools.registry.web_search", return_value={"query": "release", "results": [{"title": "Real", "url": "https://example.com", "snippet": "Evidence"}]}
        ), patch("app.tools.registry.analyze_data", return_value={"type": "table", "rows": 3}), patch(
            "app.agents.orchestrator.resolve_model"
        ) as model:
            model.return_value.supports_tools = True
            events = list(run_agent(req))

        self.assertEqual([data["status"] for event, data in events if event == "agent_step"], ["running", "completed", "running", "completed"])
        self.assertEqual([event for event, _ in events].count("tool_call"), 2)
        self.assertEqual([event for event, _ in events].count("agent_observation"), 2)
        self.assertEqual([data["status"] for event, data in events if event == "agent_status"].count("replanning"), 2)
        self.assertEqual([data["type"] for event, data in events if event == "source"], ["web"])
        self.assertEqual([data for event, data in events if event == "message"][0]["content"], "Final comparison")
        run_id = next(data["run_id"] for event, data in events if event == "agent_run")
        stored = database.get_agent_run(run_id)
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["total_tokens"], 36)
        self.assertEqual(len(stored["steps"]), 2)
        self.assertEqual([item["status"] for item in stored["plan"]], ["completed", "completed"])
        self.assertTrue(all(value is not None and value <= database.settings.agent_max_completion_tokens for value in provider.max_tokens))

    def test_tool_failure_is_an_observation_and_does_not_crash(self) -> None:
        call = ProviderToolCall("call-1", "search_web", '{"query":"blocked"}')
        provider = Provider(response('{"steps":["Search"]}'), response("", (call,)), response("Explain failure"))
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.tools.registry.web_search", side_effect=RuntimeError("network blocked")
        ), patch("app.agents.orchestrator.resolve_model") as model:
            model.return_value.supports_tools = True
            events = list(run_agent(self.request("Research the latest web report", web_search=True)))
        self.assertTrue(any(event == "agent_step" and data["status"] == "failed" for event, data in events))
        self.assertTrue(any(event == "message" and data["content"] == "Explain failure" for event, data in events))
        self.assertFalse(any(event == "error" for event, _ in events))

    def test_observation_can_replace_skip_and_add_public_plan_steps(self) -> None:
        first = ProviderToolCall("call-1", "search_web", '{"query":"broad"}')
        second = ProviderToolCall("call-2", "search_web", '{"query":"official"}')
        provider = Provider(
            response('{"steps":["Search broadly","Analyze weak lead","Draft answer"]}'),
            response("", (first,)),
            response('{"plan_update":{"remaining_steps":["Verify official source","Draft answer"]}}', (second,)),
            response("Verified answer"),
        )
        with patch("app.agents.orchestrator.create_llm_provider", return_value=provider), patch(
            "app.tools.registry.web_search", return_value={"query": "test", "results": []}
        ), patch("app.agents.orchestrator.resolve_model") as model:
            model.return_value.supports_tools = True
            events = list(run_agent(self.request("Research and compare current web sources", web_search=True)))

        plans = [data["steps"] for event, data in events if event == "agent_plan"]
        changed = next(plan for plan in plans if any(item["title"] == "Verify official source" for item in plan))
        self.assertEqual(
            [(item["title"], item["status"]) for item in changed],
            [
                ("Search broadly", "completed"),
                ("Analyze weak lead", "skipped"),
                ("Verify official source", "pending"),
                ("Draft answer", "pending"),
            ],
        )
        final_plan = plans[-1]
        self.assertEqual(next(item["status"] for item in final_plan if item["title"] == "Verify official source"), "completed")
        self.assertEqual(next(item["status"] for item in final_plan if item["title"] == "Draft answer"), "skipped")

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
        ), patch("app.tools.registry.web_search", return_value={"query": "repeat", "results": []}), patch(
            "app.agents.orchestrator.resolve_model"
        ) as model:
            model.return_value.supports_tools = True
            events = list(run_agent(req))
        status = [data for event, data in events if event == "agent_status"][-1]
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["reason"], "model_call_budget")
        self.assertTrue(any(event == "message" for event, _ in events))
        self.assertEqual(cancel_agent_run(status["run_id"], database.DEFAULT_WORKSPACE_ID)["status"], "partial")

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
        ), patch("app.tools.registry.web_search", return_value={"query": "test", "results": []}), patch(
            "app.agents.orchestrator.resolve_model"
        ) as model:
            model.return_value.supports_tools = True
            events = list(run_agent(self.request("Research and compare web sources", web_search=True)))
        self.assertEqual(len([1 for event, data in events if event == "agent_step" and data["status"] == "completed"]), 2)
        status = [data for event, data in events if event == "agent_status"][-1]
        self.assertEqual((status["status"], status["reason"]), ("partial", "tool_step_budget"))

    def test_response_that_crosses_token_budget_is_not_marked_completed(self) -> None:
        provider = Provider(response('{"steps":["Answer"]}', tokens=5), response("Final answer", tokens=50))
        with patch.object(database.settings, "agent_token_budget", 40), patch(
            "app.agents.orchestrator.create_llm_provider", return_value=provider
        ):
            events = list(run_agent(self.request("Research and compare sources")))
        status = [data for event, data in events if event == "agent_status"][-1]
        self.assertEqual((status["status"], status["reason"]), ("budget_exceeded", "token_budget"))
        self.assertEqual(database.get_agent_run(status["run_id"])["status"], "budget_exceeded")

    def test_response_that_crosses_time_budget_stops_before_tool(self) -> None:
        call = ProviderToolCall("call-1", "search_web", '{"query":"late"}')
        clock = [0.0]

        class SlowProvider(Provider):
            def complete(self, messages, tools=None, max_tokens=None):
                result = super().complete(messages, tools, max_tokens)
                if len(self.tools) == 2:
                    clock[0] = 5.0
                return result

        provider = SlowProvider(response('{"steps":["Search"]}'), response("", (call,)))
        with patch.object(database.settings, "agent_timeout_seconds", 2), patch(
            "app.agents.orchestrator.create_llm_provider", return_value=provider
        ), patch("app.agents.orchestrator.time.monotonic", side_effect=lambda: clock[0]), patch(
            "app.tools.registry.web_search"
        ) as search_web:
            events = list(run_agent(self.request("Research and compare web sources", web_search=True)))
        status = [data for event, data in events if event == "agent_status"][-1]
        self.assertEqual((status["status"], status["reason"]), ("budget_exceeded", "timeout"))
        search_web.assert_not_called()


if __name__ == "__main__":
    unittest.main()
