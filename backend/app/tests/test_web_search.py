from __future__ import annotations

import unittest
from unittest.mock import call, patch

from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from app.models.chat import ChatSettings
from app.services.web_search import search_web
from app.tools.registry import execute_tool_call, get_enabled_tool_specs
from app.tools.web_search import web_search


class WebSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        provider = patch("app.services.search_providers.settings.search_provider", "ddgs")
        provider.start()
        self.addCleanup(provider.stop)

    def test_workspace_switch_controls_registration(self) -> None:
        self.assertEqual(get_enabled_tool_specs(ChatSettings()), [])
        spec = get_enabled_tool_specs(ChatSettings(web_search=True))[0]
        self.assertEqual(spec.name, "search_web")
        self.assertEqual(spec.parameters_schema, {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False})
        with self.assertRaisesRegex(ValueError, "Unexpected tool arguments"):
            execute_tool_call({spec.name: spec}, spec.name, '{"query":"test","count":10}')

    def test_ddgs_results_are_bounded_and_only_http_urls_are_cited(self) -> None:
        items = [
            {"title": "Actual page", "href": "https://example.com/real", "body": "first second"},
            {"title": "Duplicate", "href": "https://example.com/real", "body": "ignored"},
            {"title": "Unsafe", "href": "javascript:alert(1)", "body": "ignored"},
        ]
        with patch("app.services.search_providers.DDGS") as ddgs:
            ddgs.return_value.text.return_value = items
            results = search_web("test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://example.com/real")
        self.assertEqual(results[0]["snippet"], "first second")
        ddgs.return_value.text.assert_called_once_with("test", max_results=5)

    def test_ddgs_errors_return_tool_results(self) -> None:
        for error, message in [
            (TimeoutException("timeout"), "timed out"),
            (RatelimitException("429"), "rate limit"),
            (DDGSException("network"), "temporarily unavailable"),
            (OSError("network"), "temporarily unavailable"),
        ]:
            with patch("app.services.search_providers.DDGS") as ddgs:
                ddgs.return_value.text.side_effect = error
                self.assertIn(message, web_search("test")["error"])
        with patch("app.services.search_providers.DDGS") as ddgs:
            ddgs.return_value.text.return_value = []
            self.assertEqual(web_search("test")["note"], "No relevant web search results were found.")

    def test_fallback_recovers_search_without_changing_query_or_citations(self) -> None:
        with patch("app.services.search_providers.DDGS") as ddgs:
            ddgs.return_value.text.side_effect = [
                DDGSException("No results found."),
                [{"title": "Actual result", "href": "https://example.com/page", "body": "Evidence"}],
            ]
            result = web_search("AI engineer interview")
        self.assertNotIn("error", result)
        self.assertEqual(result["results"][0]["url"], "https://example.com/page")
        self.assertEqual(ddgs.return_value.text.call_args_list, [
            call("AI engineer interview", max_results=5),
            call("AI engineer interview", max_results=5, backend="duckduckgo,yahoo", region="wt-wt"),
        ])
        self.assertEqual(ddgs.call_args_list, [call(timeout=8), call(timeout=8)])

    def test_no_results_is_not_a_network_error_and_retry_is_bounded(self) -> None:
        with patch("app.services.search_providers.DDGS") as ddgs:
            ddgs.return_value.text.side_effect = DDGSException("No results found.")
            result = web_search("very narrow query")
        self.assertNotIn("error", result)
        self.assertEqual(result["results"], [])
        self.assertIn("No relevant", result["note"])
        self.assertEqual(ddgs.return_value.text.call_count, 2)

    def test_rate_limit_can_recover_on_alternate_engine(self) -> None:
        with patch("app.services.search_providers.DDGS") as ddgs:
            ddgs.return_value.text.side_effect = [
                RatelimitException("429"),
                [{"title": "Page", "href": "https://example.com", "body": "Result"}],
            ]
            self.assertEqual(len(search_web("test")), 1)

    def test_invalid_response_does_not_retry_or_execute_more_searches(self) -> None:
        with patch("app.services.search_providers.DDGS") as ddgs:
            ddgs.return_value.text.return_value = {"unexpected": "object"}
            self.assertIn("invalid response", web_search("test")["error"])
        self.assertEqual(ddgs.return_value.text.call_count, 1)


if __name__ == "__main__":
    unittest.main()
