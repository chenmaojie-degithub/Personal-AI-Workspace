from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.providers.deepseek import DeepSeekProvider


class DeepSeekProviderTests(unittest.TestCase):
    @patch("app.providers.deepseek.OpenAI")
    def test_text_data_analysis_call_uses_registered_schema(self, openai) -> None:
        raw = "<|tool_call_start|>[analyze_data(file_id='sales.csv', operation='mean', column='revenue')]<|tool_call_end|>"
        openai.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw, tool_calls=None))],
            model="text-tool-model", usage=None,
        )
        tool = {
            "type": "function",
            "function": {
                "name": "analyze_data",
                "parameters": {
                    "type": "object",
                    "properties": {"file_id": {}, "operation": {}, "column": {}},
                    "required": ["file_id", "operation"],
                    "additionalProperties": False,
                },
            },
        }
        result = DeepSeekProvider("test-key", "https://example.com", "text-tool-model").complete(
            [{"role": "user", "content": "average revenue"}], [tool]
        )
        self.assertEqual(result.content, "")
        self.assertEqual(result.tool_calls[0].name, "analyze_data")
        self.assertEqual(
            result.tool_calls[0].arguments,
            '{"file_id": "sales.csv", "operation": "mean", "column": "revenue"}',
        )

    @patch("app.providers.deepseek.OpenAI")
    def test_text_tool_call_is_normalized_to_registered_schema(self, openai) -> None:
        raw = "<|tool_call_start|>[web_search(query='OpenAI news', source='news', count=10)]<|tool_call_end|>"
        openai.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw, tool_calls=None))],
            model="text-tool-model", usage=None,
        )
        tool = {"type": "function", "function": {"name": "search_web"}}
        result = DeepSeekProvider("test-key", "https://example.com", "text-tool-model").complete(
            [{"role": "user", "content": "news"}], [tool]
        )
        self.assertEqual(result.content, "")
        self.assertEqual(result.tool_calls[0].name, "search_web")
        self.assertEqual(result.tool_calls[0].arguments, '{"query": "OpenAI news"}')

    @patch("app.providers.deepseek.OpenAI")
    def test_stream_normalizes_content_tool_fragments_and_usage(self, openai) -> None:
        def chunk(content=None, fragments=None, usage=None):
            return SimpleNamespace(
                model="deepseek-flash",
                choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=fragments))] if content or fragments else [],
                usage=usage,
            )

        class FakeStream(list):
            def close(self):
                pass

        fragments = [
            SimpleNamespace(index=0, id="call-1", function=SimpleNamespace(name="search_web", arguments='{"query":')),
            SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='"test"}')),
        ]
        openai.return_value.chat.completions.create.return_value = FakeStream([
            chunk(content="Hel"),
            chunk(content="lo"),
            chunk(fragments=[fragments[0]]),
            chunk(fragments=[fragments[1]]),
            chunk(usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15)),
        ])
        events = list(DeepSeekProvider("test-key", "https://api.deepseek.com", "deepseek-flash").stream([{"role": "user", "content": "test"}]))
        self.assertEqual([event.content for event in events if event.type == "message"], ["Hel", "lo"])
        self.assertEqual(next(event.tool_call.arguments for event in events if event.type == "tool_call"), '{"query":"test"}')
        self.assertEqual(next(event.usage.total_tokens for event in events if event.type == "usage"), 15)
        self.assertEqual(events[-1].type, "done")
        self.assertTrue(openai.return_value.chat.completions.create.call_args.kwargs["stream"])

    @patch("app.providers.deepseek.OpenAI")
    def test_normalizes_message_and_tool_calls(self, openai) -> None:
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="search_web", arguments='{"query":"test"}'),
        )
        openai.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))],
            model="deepseek-flash",
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=3,
                total_tokens=15,
            ),
        )

        provider = DeepSeekProvider("test-key", "https://api.deepseek.com", "deepseek-flash")
        result = provider.complete([{"role": "user", "content": "test"}])

        self.assertEqual(result.content, "")
        self.assertEqual(result.tool_calls[0].name, "search_web")
        self.assertEqual(result.provider, "deepseek")
        self.assertEqual(result.model, "deepseek-flash")
        self.assertEqual(result.usage.total_tokens, 15)
        openai.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.deepseek.com",
        )

    @patch("app.providers.deepseek.OpenAI")
    def test_missing_usage_returns_none_without_estimating(self, openai) -> None:
        openai.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
            model="deepseek-flash",
            usage=None,
        )

        provider = DeepSeekProvider("test-key", "https://api.deepseek.com", "deepseek-flash")

        self.assertIsNone(provider.complete([{"role": "user", "content": "test"}]).usage)

    @patch("app.providers.deepseek.OpenAI")
    def test_completion_limit_is_forwarded_to_provider(self, openai) -> None:
        openai.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
            model="deepseek-flash", usage=None,
        )
        DeepSeekProvider("test-key", "https://api.deepseek.com", "deepseek-flash").complete(
            [{"role": "user", "content": "test"}], max_tokens=321,
        )
        self.assertEqual(openai.return_value.chat.completions.create.call_args.kwargs["max_tokens"], 321)


if __name__ == "__main__":
    unittest.main()
