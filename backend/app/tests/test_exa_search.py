from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from app.services.search_providers import WebSearchError
from app.services.web_search import search_web
from app.tools.registry import execute_tool_call, get_enabled_tool_specs
from app.tools.web_search import web_citations, web_search
from app.models.chat import ChatSettings


class ExaSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        # All HTTP is mocked, even if the developer's .env contains a real key.
        for target, value in [
            ("app.services.search_providers.settings.search_provider", "exa"),
            ("app.services.search_providers.settings.exa_api_key", SecretStr("test-only-key")),
        ]:
            item = patch(target, value)
            item.start()
            self.addCleanup(item.stop)
        request = patch("app.services.search_providers.httpx.post")
        self.post = request.start()
        self.addCleanup(request.stop)

    def respond(self, payload: object, status: int = 200) -> None:
        self.post.return_value = httpx.Response(status, json=payload)

    def test_exa_request_and_normalized_results_generate_real_citations(self) -> None:
        self.respond({"results": [{
            "title": "FastAPI docs", "url": "https://fastapi.tiangolo.com/",
            "highlights": ["First excerpt.", "Second excerpt."],
            "publishedDate": "2026-10-12T00:00:00Z",
        }]})
        query = "查找 FastAPI 的英文官方文档"
        spec = get_enabled_tool_specs(ChatSettings(web_search=True))[0]
        result = execute_tool_call({spec.name: spec}, "search_web", json.dumps({"query": query}))
        item = result["results"][0]
        self.assertEqual(item["published_at"], "2026-10-12T00:00:00Z")
        self.assertEqual(item["snippet"], "First excerpt. Second excerpt.")
        citation = web_citations(result)[0]
        self.assertEqual((citation.type, citation.title, citation.url), ("web", "FastAPI docs", item["url"]))
        kwargs = self.post.call_args.kwargs
        self.assertEqual(self.post.call_args.args, ("https://api.exa.ai/search",))
        self.assertEqual(kwargs["json"], {"query": query, "type": "auto", "numResults": 5, "contents": {"highlights": True}})
        self.assertFalse(kwargs["follow_redirects"])
        self.assertEqual(kwargs["timeout"].read, 15.0)
        self.post.assert_called_once()

    def test_empty_results(self) -> None:
        self.respond({"results": []})
        result = web_search("test")
        self.assertEqual(result["results"], [])
        self.assertIn("No relevant", result["note"])

    def test_disabled_workspace_does_not_register_or_call_search(self) -> None:
        self.assertNotIn("search_web", [spec.name for spec in get_enabled_tool_specs(ChatSettings(web_search=False))])
        self.post.assert_not_called()

    def test_urls_deduplicated_validated_and_results_bounded(self) -> None:
        self.respond({"results": [
            {"url": "https://example.com/real", "highlights": ["x" * 1000]},
            {"url": "https://example.com/real"},
            *({"url": url} for url in ["javascript:alert(1)", "file:///etc/passwd", "https://[", "https://user:password@example.com", "https://", "https://bad host.com"]),
            *({"url": f"https://example.com/{i}"} for i in range(10)),
        ]})
        results = search_web("test")
        self.assertEqual(len(results), 5)
        self.assertEqual(len({item["url"] for item in results}), 5)
        self.assertEqual(len(results[0]["snippet"]), 900)
        self.assertTrue(all(item["url"].startswith("https://example.com/") for item in results))

    def test_missing_key_never_falls_back_to_ddgs(self) -> None:
        with patch("app.services.search_providers.settings.exa_api_key", None), patch("app.services.search_providers.DDGS") as ddgs:
            self.assertIn("set EXA_API_KEY", web_search("test")["error"])
        self.post.assert_not_called()
        ddgs.assert_not_called()

    def test_api_errors_are_clear_and_do_not_expose_response_body(self) -> None:
        for status, expected in [(401, "authentication"), (403, "access denied"), (429, "rate limit"), (500, "HTTP 500")]:
            with self.subTest(status=status):
                self.respond({"error": "private-response-body"}, status)
                result = web_search("test")
                self.assertIn(expected, result["error"])
                self.assertNotIn("private-response-body", result["error"])
                self.assertNotIn("test-only-key", result["error"])
        self.assertEqual(self.post.call_count, 4)

    def test_timeout_and_network_error_are_bounded(self) -> None:
        for error, expected in [(httpx.ReadTimeout("test-only-key"), "timed out"), (httpx.ConnectError("test-only-key"), "network")]:
            with self.subTest(error=type(error).__name__):
                self.post.side_effect = error
                result = web_search("test")
                self.assertIn(expected, result["error"])
                self.assertNotIn("test-only-key", result["error"])
        self.assertEqual(self.post.call_count, 2)

    def test_invalid_response_is_rejected(self) -> None:
        for payload in [[], {}, {"results": {}}, {"results": None}]:
            self.respond(payload)
            self.assertIn("invalid response", web_search("test")["error"])
        self.post.return_value = httpx.Response(200, content=b"not JSON")
        self.assertIn("invalid JSON", web_search("test")["error"])

    def test_query_validation_precedes_http(self) -> None:
        for query in [" ", "x" * 601, "word " * 76]:
            with self.assertRaises(WebSearchError):
                search_web(query)
        self.post.assert_not_called()

    def test_unknown_provider_never_silently_falls_back(self) -> None:
        with patch("app.services.search_providers.settings.search_provider", "unknown"):
            self.assertIn("Unknown SEARCH_PROVIDER", web_search("test")["error"])
        self.post.assert_not_called()
