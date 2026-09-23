from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None = None


class WebSearchError(Exception):
    pass


def search_web(query: str) -> list[dict]:
    query = query.strip()
    if not query or len(query) > 600 or len(query.split()) > 75:
        raise WebSearchError("Web Search query must contain 1–600 characters and at most 75 words.")
    try:
        items = DDGS().text(query, max_results=5)
    except TimeoutException as exc:
        raise WebSearchError("Web Search timed out.") from exc
    except RatelimitException as exc:
        raise WebSearchError("Web Search rate limit reached or the search source refused the request.") from exc
    except (DDGSException, OSError) as exc:
        raise WebSearchError("Web Search is temporarily unavailable.") from exc

    if not isinstance(items, list):
        raise WebSearchError("Web Search returned an invalid response.")

    results: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("href") or item.get("url")
        if not isinstance(url, str) or not _safe_web_url(url) or url in seen:
            continue
        seen.add(url)
        title = item.get("title") or urlparse(url).netloc
        snippet = item.get("body") or item.get("snippet") or ""
        results.append(asdict(WebSearchResult(str(title)[:200], url, str(snippet).strip()[:900])))
        if len(results) == 5:
            break
    if settings.app_env == "dev":
        logger.info("ddgs results=%d", len(results))
    return results


def _safe_web_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
