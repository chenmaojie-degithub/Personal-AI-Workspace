from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.chat import orchestrate_chat
from app.models.chat import ChatMessage, ChatRequest, ChatSettings
from app.providers.base import LLMResponse, LLMUsage, ProviderToolCall
from app.rag.models import RAGChunk


class SequenceProvider:
    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.tool_args: list[list[dict] | None] = []

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.calls.append(messages)
        self.tool_args.append(tools)
        return self.responses.pop(0)


def response(
    content: str,
    prompt_tokens: int | None = 10,
    completion_tokens: int = 4,
    tool_calls: tuple[ProviderToolCall, ...] = (),
) -> LLMResponse:
    usage = (
        LLMUsage(prompt_tokens, completion_tokens, prompt_tokens + completion_tokens)
        if prompt_tokens is not None
        else None
    )
    return LLMResponse(content, tool_calls, "deepseek-flash", "deepseek", usage)


def request(content: str, **settings: bool) -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role="user", content=content)],
        settings=ChatSettings(**settings),
    )


class ChatUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.persistence = patch("app.api.routes.chat.save_chat_turn")
        self.persistence.start()

    def tearDown(self) -> None:
        self.persistence.stop()

    def test_normal_chat_usage(self) -> None:
        provider = SequenceProvider(response("ok", 10, 4))
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider):
            result = orchestrate_chat(request("hello"))

        self.assertEqual(result.usage, LLMUsage(10, 4, 14))
        self.assertEqual(result.sources, [])

    def test_tool_call_usage_is_summed(self) -> None:
        tool_call = ProviderToolCall("call-1", "search_web", '{"query":"test"}')
        provider = SequenceProvider(
            response("", 20, 5, (tool_call,)),
            response("tool complete", 30, 7),
        )
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider), patch(
            "app.tools.web_search.search_web", return_value=[{"title": "Example", "url": "https://example.com/page", "snippet": "Actual result"}]
        ):
            result = orchestrate_chat(request("search", web_search=True))

        self.assertEqual(result.usage, LLMUsage(50, 12, 62))
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.sources[0].url, "https://example.com/page")
        self.assertEqual(result.sources[0].type, "web")
        self.assertIsNotNone(provider.tool_args[0])
        self.assertIsNotNone(provider.tool_args[1])

    def test_rag_chat_usage(self) -> None:
        provider = SequenceProvider(response("from document", 40, 8))
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat._should_use_rag", return_value=True
        ), patch("app.api.routes.chat.RAGService") as rag_service:
            rag_service.return_value.retrieve.return_value = [
                RAGChunk("document text", "note.txt", "doc-1", 3, 0.2),
                RAGChunk("more text", "note.txt", "doc-1", 4, 0.3),
            ]
            result = orchestrate_chat(request("question"))

        self.assertEqual(result.usage, LLMUsage(40, 8, 48))
        self.assertTrue(any("RAG_CONTEXT" in item["content"] for item in provider.calls[0]))
        self.assertTrue(any("[Source 1]" in item["content"] for item in provider.calls[0]))
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(result.sources[0].filename, "note.txt")
        self.assertEqual(result.sources[0].chunk_index, 3)
        self.assertEqual(result.sources[0].document_id, "doc-1")

    def test_rag_and_web_sources_share_one_response(self) -> None:
        call = ProviderToolCall("call-1", "search_web", '{"query":"test"}')
        provider = SequenceProvider(response("", tool_calls=(call,)), response("answer"))
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat._should_use_rag", return_value=True
        ), patch("app.api.routes.chat.RAGService") as rag, patch(
            "app.tools.web_search.search_web", return_value=[{"title": "Example", "url": "https://example.com/page", "snippet": "Web text"}]
        ):
            rag.return_value.retrieve.return_value = [RAGChunk("Local text", "note.txt", "doc-1", 0, 0.1)]
            result = orchestrate_chat(request("question", web_search=True))
        self.assertEqual([source.type for source in result.sources], ["knowledge", "web"])
        self.assertEqual(result.sources[1].url, "https://example.com/page")

    def test_missing_usage_returns_none(self) -> None:
        provider = SequenceProvider(response("ok", None))
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider):
            result = orchestrate_chat(request("hello"))

        self.assertIsNone(result.usage)


if __name__ == "__main__":
    unittest.main()
