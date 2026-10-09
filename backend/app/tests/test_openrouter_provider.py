from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.routes.chat import orchestrate_chat
from app.api.routes.chat_stream import _events
from app.main import app
from app.models.chat import ChatMessage, ChatRequest, ChatSettings
from app.providers.base import LLMResponse, LLMStreamEvent, LLMUsage
from app.providers.factory import create_llm_provider
from app.providers.openrouter import OpenRouterProvider
from app.providers.registry import ModelEntry
from app.rag.models import RAGChunk


def fake_settings(openrouter_key: str | None = "test-key") -> SimpleNamespace:
    return SimpleNamespace(
        llm_provider="deepseek",
        deepseek_api_key="test-deepseek-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-flash",
        openai_api_key=None,
        openai_base_url=None,
        openai_model="unused",
        openrouter_api_key=openrouter_key,
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_model="openrouter/free",
        openrouter_fixed_model="nvidia/nemotron-3-super-120b-a12b:free",
    )


class OpenRouterTests(unittest.TestCase):
    @patch("app.providers.deepseek.OpenAI")
    def test_text_tool_call_is_executed_without_streaming_control_tokens(self, openai) -> None:
        class FakeStream(list):
            def close(self):
                pass

        def chunk(content: str):
            return SimpleNamespace(model="text-tool-model", usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))])

        raw = "Searching now. <|tool_call_start|>[web_search(query='OpenAI latest news official website today', source='news', count=10)]<|tool_call_end|>"
        first = FakeStream([chunk(raw[:14]), chunk(raw[14:56]), chunk(raw[56:])])
        second = FakeStream([chunk("Here is the "), chunk("answer.")])
        openai.return_value.chat.completions.create.side_effect = [first, second]
        provider = OpenRouterProvider("test-key", "https://openrouter.ai/api/v1", "openrouter/free")
        ddgs_results = [{"title": "OpenAI News", "href": "https://openai.com/news/example", "body": "Official update"}]
        req = ChatRequest(messages=[ChatMessage(role="user", content="Find current OpenAI news")], settings=ChatSettings(web_search=True))
        with patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider), patch(
            "app.api.routes.chat_stream._should_use_rag", return_value=True
        ), patch("app.api.routes.chat_stream.get_rag_service") as rag_factory, patch(
            "app.api.routes.chat_stream.save_chat_turn"
        ), patch("app.services.web_search.DDGS") as ddgs:
            ddgs.return_value.text.return_value = ddgs_results
            rag_factory.return_value.retrieve.return_value = [RAGChunk("Local notes", "README.md", "doc-1", 3, 0.1)]
            events = [(line.split("\n")[0].removeprefix("event: "), json.loads(line.split("data: ", 1)[1])) for line in _events(req)]

        messages = [data["content"] for kind, data in events if kind == "message"]
        sources = [data for kind, data in events if kind == "source"]
        self.assertEqual("".join(messages), "Here is the answer.")
        self.assertNotIn("<|tool_call_", "".join(messages))
        self.assertEqual([data["name"] for kind, data in events if kind == "tool_call"], ["search_web"])
        self.assertEqual([source["type"] for source in sources], ["knowledge", "web"])
        self.assertEqual(sources[0]["filename"], "README.md")
        self.assertEqual(sources[1]["url"], "https://openai.com/news/example")
        ddgs.return_value.text.assert_called_once_with("OpenAI latest news official website today", max_results=5)

    def test_models_endpoint_and_model_switch(self) -> None:
        config = fake_settings()
        with patch("app.providers.registry.settings", config), patch("app.providers.factory.settings", config):
            response = TestClient(app).get("/models")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [item["model_id"] for item in response.json()["models"]],
                ["deepseek", "openrouter/free", "openrouter/fixed"],
            )
            self.assertEqual(response.json()["default_model_id"], "deepseek")
            self.assertEqual(create_llm_provider("deepseek")._model, "deepseek-flash")
            self.assertIsInstance(create_llm_provider("openrouter/free"), OpenRouterProvider)
            self.assertEqual(
                create_llm_provider("openrouter/fixed")._model,
                "nvidia/nemotron-3-super-120b-a12b:free",
            )

    def test_unconfigured_openrouter_is_not_listed(self) -> None:
        with patch("app.providers.registry.settings", fake_settings(None)):
            response = TestClient(app).get("/models")
            self.assertEqual([item["model_id"] for item in response.json()["models"]], ["deepseek"])

    def test_unknown_fixed_model_is_not_allowed_to_register_agent_tools(self) -> None:
        config = fake_settings()
        config.openrouter_fixed_model = "vendor/unknown-model:free"
        with patch("app.providers.registry.settings", config):
            fixed = next(item for item in TestClient(app).get("/models").json()["models"] if item["model_id"] == "openrouter/fixed")
        self.assertFalse(fixed["supports_tools"])

    def test_unknown_legacy_openrouter_model_is_not_allowed_agent_tools(self) -> None:
        config = fake_settings()
        config.openrouter_model = "vendor/unknown-model"
        with patch("app.providers.registry.settings", config):
            legacy = next(item for item in TestClient(app).get("/models").json()["models"] if item["model_id"] == "openrouter/free")
        self.assertFalse(legacy["supports_tools"])

    @patch("app.providers.deepseek.OpenAI")
    def test_openrouter_maps_real_response_usage_and_provider(self, openai) -> None:
        openai.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=None))],
            model="actual/free-model",
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3, total_tokens=14),
        )
        provider = OpenRouterProvider("test-key", "https://openrouter.ai/api/v1", "openrouter/free")
        result = provider.complete([{"role": "user", "content": "hello"}])
        self.assertEqual((result.provider, result.model, result.usage),
                         ("openrouter", "actual/free-model", LLMUsage(11, 3, 14)))
        openai.assert_called_once_with(api_key="test-key", base_url="https://openrouter.ai/api/v1")

    @patch("app.providers.deepseek.OpenAI")
    def test_openrouter_stream_maps_usage_and_provider(self, openai) -> None:
        class FakeStream(list):
            def close(self):
                pass

        openai.return_value.chat.completions.create.return_value = FakeStream([
            SimpleNamespace(model="actual/free-model", choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello", tool_calls=None))], usage=None),
            SimpleNamespace(model="actual/free-model", choices=[], usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2, total_tokens=10)),
        ])
        provider = OpenRouterProvider("test-key", "https://openrouter.ai/api/v1", "openrouter/free")
        events = list(provider.stream([{"role": "user", "content": "hello"}]))
        self.assertEqual([event.content for event in events if event.type == "message"], ["Hello"])
        self.assertEqual(next(event.usage.total_tokens for event in events if event.type == "usage"), 10)
        self.assertEqual((events[-1].provider, events[-1].model), ("openrouter", "actual/free-model"))
        self.assertTrue(openai.return_value.chat.completions.create.call_args.kwargs["stream"])

    def test_chat_model_id_reaches_factory_and_persistence(self) -> None:
        req = ChatRequest(model_id="openrouter/free", messages=[ChatMessage(role="user", content="hi")])
        provider = SimpleNamespace(complete=lambda **kwargs: LLMResponse("hello", model="actual/free-model", provider="openrouter", usage=LLMUsage(4, 2, 6)))
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider) as factory, patch(
            "app.api.routes.chat.save_chat_turn"
        ) as save:
            result = orchestrate_chat(req)
        factory.assert_called_once_with("openrouter/free")
        self.assertEqual(result.usage.total_tokens, 6)
        self.assertEqual((save.call_args.kwargs["provider"], save.call_args.kwargs["model"]),
                         ("openrouter", "actual/free-model"))

    def test_model_without_tools_returns_explicit_error(self) -> None:
        req = ChatRequest(model_id="openrouter/free", messages=[ChatMessage(role="user", content="search")], settings=ChatSettings(web_search=True))
        with patch("app.api.routes.chat.create_llm_provider", return_value=SimpleNamespace()) as factory, patch(
            "app.api.routes.chat.resolve_model",
            return_value=ModelEntry("openrouter/free", "openrouter", "openrouter/free", False, True),
        ):
            result = orchestrate_chat(req)
        factory.assert_called_once_with("openrouter/free")
        self.assertIn("does not support Tool Calling", result.error)

    def test_stream_model_id_and_usage(self) -> None:
        req = ChatRequest(model_id="openrouter/free", messages=[ChatMessage(role="user", content="hi")])
        provider = SimpleNamespace(stream=lambda *args: iter([
            LLMStreamEvent("message", content="hi"),
            LLMStreamEvent("usage", usage=LLMUsage(4, 2, 6)),
            LLMStreamEvent("done", model="actual/free-model", provider="openrouter"),
        ]))
        with patch("app.api.routes.chat_stream.create_llm_provider", return_value=provider) as factory, patch(
            "app.api.routes.chat_stream.save_chat_turn"
        ) as save:
            events = list(_events(req))
        factory.assert_called_once_with("openrouter/free")
        self.assertTrue(any("event: usage" in item for item in events))
        self.assertEqual((save.call_args.kwargs["provider"], save.call_args.kwargs["model"]),
                         ("openrouter", "actual/free-model"))


if __name__ == "__main__":
    unittest.main()
