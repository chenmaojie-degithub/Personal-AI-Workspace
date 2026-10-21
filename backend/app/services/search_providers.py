from __future__ import annotations

import logging
from typing import Protocol

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from app.core.config import settings

logger = logging.getLogger(__name__)


class WebSearchError(Exception):
    pass


class SearchProvider(Protocol):
    def search(self, query: str) -> list[dict]: ...


class ExaProvider:
    def search(self, query: str) -> list[dict]:
        if not settings.exa_api_key or not settings.exa_api_key.get_secret_value().strip():
            raise WebSearchError("Exa Search is not configured: set EXA_API_KEY in backend/.env.")
        try:
            response = httpx.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": settings.exa_api_key.get_secret_value()},
                json={
                    "query": query,
                    "type": "auto",
                    "numResults": 5,
                    "contents": {"highlights": True},
                },
                timeout=httpx.Timeout(15.0, connect=5.0),
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise WebSearchError("Exa Search timed out.") from None
        except httpx.RequestError:
            raise WebSearchError("Exa Search network request failed.") from None
        # Never include response bodies or request headers in errors or logs.
        logger.info("exa response status=%d", response.status_code)
        errors = {
            401: "Exa Search authentication failed (401): check EXA_API_KEY.",
            403: "Exa Search access denied (403): check API permissions.",
            429: "Exa Search rate limit or quota reached (429).",
        }
        if not 200 <= response.status_code < 300:
            raise WebSearchError(errors.get(response.status_code, f"Exa Search API failed (HTTP {response.status_code})."))
        try:
            payload = response.json()
        except ValueError:
            raise WebSearchError("Exa Search returned invalid JSON.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise WebSearchError("Exa Search returned an invalid response.")
        results = []
        for item in payload["results"]:
            if not isinstance(item, dict):
                continue
            highlights = item.get("highlights")
            snippet = " ".join(part for part in highlights if isinstance(part, str)) if isinstance(highlights, list) else ""
            results.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": snippet,
                "published_at": item.get("publishedDate"),
            })
        return results


class DDGSProvider:
    def search(self, query: str) -> list[dict]:
        failures: list[Exception] = []
        for attempt, options in enumerate(({}, {"backend": "duckduckgo,yahoo", "region": "wt-wt"}), 1):
            try:
                items = DDGS(timeout=8).text(query, max_results=5, **options)
                if not isinstance(items, list):
                    raise WebSearchError("Web Search returned an invalid response.")
                if items:
                    return [
                        {"title": item.get("title"), "url": item.get("href") or item.get("url"),
                         "snippet": item.get("body") or item.get("snippet") or "", "published_at": None}
                        for item in items if isinstance(item, dict)
                    ]
            except (DDGSException, OSError) as exc:
                failures.append(exc)
                reason = "no_results" if "no results found" in str(exc).lower() else type(exc).__name__
                logger.warning("ddgs attempt=%d backend=%s failure=%s", attempt, options.get("backend", "auto"), reason)
        if not failures or all("no results found" in str(exc).lower() for exc in failures):
            return []
        if any(isinstance(exc, RatelimitException) for exc in failures):
            raise WebSearchError("Web Search rate limit reached or the search source refused the request.")
        if all(isinstance(exc, TimeoutException) for exc in failures):
            raise WebSearchError("Web Search timed out after two search attempts.")
        raise WebSearchError("Web Search is temporarily unavailable after two attempts; search sources may be blocked or unreachable.")


def get_search_provider() -> SearchProvider:
    provider = settings.search_provider.strip().lower()
    if provider == "exa":
        return ExaProvider()
    if provider == "ddgs":
        return DDGSProvider()
    raise WebSearchError("Unknown SEARCH_PROVIDER: use exa or ddgs.")
