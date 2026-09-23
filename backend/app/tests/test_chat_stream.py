from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.routes.chat_stream import _events
from app.main import app
from app.models.chat import ChatMessage, ChatRequest, ChatSettings
from app.providers.base import LLMStreamEvent, LLMUsage, ProviderToolCall
from app.rag.models import RAGChunk


def parsed_events(req: ChatRequest) -> list[tuple[str, object]]:
    return [
        (line.split("\n")[0].removeprefix("event: "), json.loads(line.split("data: ", 1)[1]))
        for line in _events(req)
    ]


class FakeProvider:
    def __init__(self, *rounds: list[LLMStreamEvent]) -> None:
        self.rounds = list(rounds)
        self.tool_args: list[list[dict] | None] = []

    def stream(self, messages, tools=None):
        self.tool_args.append(tools)
        yield from self.rounds.pop(0)


def request(**settings: bool) -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role="user", content="What is in note.txt?")], settings=ChatSettings(**settings))


class StreamTests(unittest.TestCase):
    def test_normal_stream_and_single_persistence(self) -> None:
        provider = FakeProvider([
            LLMStreamEvent("message", content="Hel"),
            LLMStreamEvent("message", content="lo"),
            LLMStreamEvent("usage", usage=LLMUsage(5, 2, 7)),
            LLMStreamEvent("done", model="deepseek-flash", provider="deepseek"),
        ])
        with patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat_stream.save_chat_turn"
        ) as save:
            events = parsed_events(request())
        self.assertEqual([item[1]["content"] for item in events if item[0] == "message"], ["Hel", "lo"])
        self.assertEqual([kind for kind, _ in events], ["message", "message", "usage", "done"])
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["assistant_content"], "Hello")
        self.assertEqual(save.call_args.kwargs["usage"], LLMUsage(5, 2, 7))

    def test_rag_sources_are_real_retrieval_results(self) -> None:
        provider = FakeProvider([
            LLMStreamEvent("message", content="From document [1]"),
            LLMStreamEvent("done", model="deepseek-flash", provider="deepseek"),
        ])
        chunk = RAGChunk("Document text", "note.txt", "doc-1", 3, 0.2)
        with patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat_stream._should_use_rag", return_value=True
        ), patch("app.api.routes.chat_stream.RAGService") as rag, patch(
            "app.api.routes.chat_stream.save_chat_turn"
        ):
            rag.return_value.retrieve.return_value = [chunk]
            events = parsed_events(request())
        sources = [data for kind, data in events if kind == "source"]
        self.assertEqual(len(sources), 1)
        self.assertEqual((sources[0]["filename"], sources[0]["chunk_index"]), ("note.txt", 3))

    def test_tool_usage_sums_both_streams(self) -> None:
        provider = FakeProvider(
            [LLMStreamEvent("tool_call", tool_call=ProviderToolCall("call-1", "search_web", '{"query":"test"}')),
             LLMStreamEvent("usage", usage=LLMUsage(10, 3, 13)),
             LLMStreamEvent("done", model="deepseek-flash", provider="deepseek")],
            [LLMStreamEvent("message", content="Tool result"),
             LLMStreamEvent("usage", usage=LLMUsage(15, 4, 19)),
             LLMStreamEvent("done", model="deepseek-flash", provider="deepseek")],
        )
        with patch("app.tools.web_search.search_web", return_value=[{"title": "Example", "url": "https://example.com/page", "snippet": "Actual result"}]), patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat_stream.save_chat_turn"
        ) as save:
            events = parsed_events(request(web_search=True))
        self.assertEqual([data for kind, data in events if kind == "usage"], [
            {"prompt_tokens": 25, "completion_tokens": 7, "total_tokens": 32}
        ])
        self.assertEqual(len([kind for kind, _ in events if kind == "tool_call"]), 1)
        self.assertEqual([data["url"] for kind, data in events if kind == "source"], ["https://example.com/page"])
        self.assertEqual(save.call_args.kwargs["usage"], LLMUsage(25, 7, 32))
        self.assertIsNotNone(provider.tool_args[0])
        self.assertIsNotNone(provider.tool_args[1])

    def test_error_does_not_save_partial_answer(self) -> None:
        def broken(*args, **kwargs):
            yield LLMStreamEvent("message", content="partial")
            raise RuntimeError("model failed")

        provider = SimpleNamespace(stream=broken)
        with patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat_stream.save_chat_turn"
        ) as save:
            events = parsed_events(request())
        self.assertEqual([kind for kind, _ in events], ["message", "error"])
        save.assert_not_called()

    def test_existing_chat_route_and_stream_route_exist(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertIn("/chat", paths)
        self.assertIn("/chat/stream", paths)
        self.assertEqual(TestClient(app).post("/chat/stream", json={"messages": []}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
