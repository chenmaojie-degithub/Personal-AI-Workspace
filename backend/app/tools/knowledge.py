from __future__ import annotations

from typing import Any

from app.models.chat import CitationSource
from app.rag.service import get_rag_service


def search_knowledge(
    session_id: str,
    workspace_id: str | None,
    query: str,
    document_id: str | None = None,
    top_k: int | None = None,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Search only vectors owned by the current Workspace or legacy session."""
    chunks = get_rag_service().retrieve(
        session_id,
        query,
        top_k=top_k or 5,
        workspace_id=workspace_id,
        document_id=document_id,
        document_ids=document_ids,
    )
    return {
        "type": "knowledge_search",
        "query": query,
        "results": [
            {
                "content": chunk.content,
                "filename": chunk.filename,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.metadata.get("page_number"),
                "section": chunk.metadata.get("section"),
                "distance": chunk.distance,
            }
            for chunk in chunks
        ],
    }


def read_document(
    session_id: str,
    workspace_id: str | None,
    document_id: str,
    cursor: int | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Read a bounded, ordered segment from a document in the current scope."""
    result = get_rag_service().read_document(
        session_id,
        document_id,
        cursor=cursor or 0,
        max_chars=max_chars or 8_000,
        workspace_id=workspace_id,
    )
    return {"type": "document_read", **result}


def knowledge_citations(result: dict[str, Any]) -> list[CitationSource]:
    items = result.get("results") if result.get("type") == "knowledge_search" else result.get("chunks")
    citations: list[CitationSource] = []
    seen: set[tuple[str, int]] = set()
    for item in items or []:
        key = (str(item.get("document_id") or ""), int(item.get("chunk_index") or 0))
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            CitationSource(
                type="knowledge",
                filename=item.get("filename"),
                document_id=item.get("document_id"),
                chunk_index=item.get("chunk_index"),
                page_number=item.get("page_number"),
                section=item.get("section"),
                content_preview=" ".join(str(item.get("content") or "").split())[:240],
                distance=item.get("distance"),
            )
        )
    return citations
