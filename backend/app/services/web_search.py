from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.core.config import settings
from app.services.search_providers import WebSearchError, get_search_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None = None


def search_web(query: str) -> list[dict]:
    query = query.strip()
    if not query or len(query) > 600 or len(query.split()) > 75:
        raise WebSearchError("Web Search query must contain 1–600 characters and at most 75 words.")
    items = get_search_provider().search(query)

    if not isinstance(items, list):
        raise WebSearchError("Web Search returned an invalid response.")

    results: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not _safe_web_url(url) or url in seen:
            continue
        seen.add(url)
        title = item.get("title") or urlparse(url).netloc
        snippet = item.get("snippet") or ""
        published_at = item.get("published_at")
        published_at = published_at if isinstance(published_at, str) else None
        results.append(asdict(WebSearchResult(str(title)[:200], url, str(snippet).strip()[:900], published_at)))
        if len(results) == 5:
            break
    if settings.app_env == "dev":
        logger.info("web_search provider=%s results=%d", settings.search_provider, len(results))
    return results


def _safe_web_url(url: str) -> bool:
    if any(char.isspace() or ord(char) < 32 for char in url):
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False
