from __future__ import annotations

import logging

from app.core.config import settings
from app.models.chat import CitationSource
from app.services.web_search import WebSearchError, search_web

logger = logging.getLogger(__name__)


def web_search(query: str) -> dict:
    if settings.app_env == "dev":
        logger.info("web_search tool called query=%r", query[:200])
    try:
        results = search_web(query)
    except WebSearchError as exc:
        return {"query": query, "results": [], "error": str(exc)}
    return {
        "query": query,
        "results": results,
        **({"note": "No relevant web search results were found."} if not results else {}),
    }


def web_citations(result: dict) -> list[CitationSource]:
    return [
        CitationSource(type="web", title=item["title"], url=item["url"], content_preview=item["snippet"][:240])
        for item in result.get("results", [])
    ]
