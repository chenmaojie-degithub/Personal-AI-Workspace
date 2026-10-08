from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.chunking import chunk_documents
from app.rag.embeddings import create_embedding_provider
from app.rag.loaders import load_files
from app.rag.models import RAGChunk

import chromadb
from chromadb.config import Settings as ChromaSettings


@lru_cache(maxsize=8)
def _cached_rag_service(config_key: tuple[str, ...]) -> "RAGService":
    return RAGService()


def get_rag_service() -> "RAGService":
    """Reuse the expensive Chroma and embedding clients while settings stay unchanged."""
    return _cached_rag_service((
        str(Path(settings.chroma_persist_dir).resolve()),
        settings.chroma_collection,
        settings.embedding_provider,
        settings.local_embedding_model,
        str(Path(settings.local_embedding_cache_dir).resolve()),
        settings.openai_embedding_base_url or "",
        settings.openai_embedding_model,
        "configured" if settings.openai_embedding_api_key else "unconfigured",
    ))


class RAGService:
    """
    RAG service orchestrator.

    Responsibilities:
      - Load files
      - Chunk content
      - Generate embeddings
      - Store in ChromaDB
      - Retrieve top-k chunks on demand

    This is a separate module from /chat endpoint logic.
    """

    def __init__(self) -> None:
        persist_dir = Path(settings.chroma_persist_dir).resolve()
        persist_dir.mkdir(parents=True, exist_ok=True)

        # Persistent client so data survives restarts
        self.client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Create collection if missing
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
        )

        self._embedding_provider = create_embedding_provider()


    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self._embedding_provider:
            raise RuntimeError(
                "Embedding provider is not configured. Set EMBEDDING_PROVIDER=local "
                "or configure an OpenAI embedding key."
            )
        if not texts:
            return []

        return self._embedding_provider.embed(texts)

    @staticmethod
    def _where(session_id: str, filename: str | None = None, workspace_id: str | None = None) -> dict[str, Any]:
        scope = {"workspace_id": workspace_id} if workspace_id else {"session_id": session_id}
        if filename:
            return {"$and": [scope, {"filename": filename}]}
        return scope

    @staticmethod
    def _chunk(content: str, metadata: dict[str, Any], distance: float | None) -> RAGChunk:
        return RAGChunk(
            content=content,
            filename=str(metadata.get("filename") or ""),
            document_id=str(metadata.get("document_id") or ""),
            chunk_index=int(metadata.get("chunk_index") or 0),
            distance=distance,
            metadata=dict(metadata),
        )

    def ingest_files(self, session_id: str, file_paths: list[Path], workspace_id: str | None = None) -> dict[str, Any]:
        """
        Ingest files for a session: load, chunk, embed, store.

        Returns summary dict with counts.
        """
        # 1. Load files
        documents = load_files(file_paths)

        # 2. Chunk documents
        chunks = chunk_documents(documents)

        # 3. Generate embeddings
        contents = [c["content"] for c in chunks]
        embeddings = self._embed_texts(contents)

        # 4. Store in ChromaDB with metadata
        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for i, c in enumerate(chunks):
            doc_id = str(c.get("document_id") or "unknown")
            chunk_index = int(c.get("chunk_index") or 0)
            ids.append(f"{session_id}:{doc_id}:{chunk_index}:{i}")

            # Chroma metadata must be str/int/float/bool (no None).
            raw_meta: dict[str, Any] = {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "document_id": doc_id,
                "filename": str(c.get("filename") or ""),
                "chunk_index": chunk_index,
                # Optional fields (only include if present)
                "start": c.get("start"),
                "end": c.get("end"),
            }
            meta = {k: v for k, v in raw_meta.items() if v is not None}
            metadatas.append(meta)

        if ids:
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=contents,
                metadatas=metadatas,
            )

        return {
            "session_id": session_id,
            "documents_loaded": len(documents),
            "chunks_created": len(chunks),
            "stored": len(ids),
        }

    def retrieve(self, session_id: str, query: str, top_k: int = 5, filename: str | None = None, workspace_id: str | None = None) -> list[RAGChunk]:
        """
        Retrieve top-k relevant chunks for a query.

        Args:
            session_id: Session ID to filter chunks
            query: Query text for semantic search
            top_k: Number of chunks to retrieve
            filename: Optional filename to filter chunks by specific file

        Returns:
            List of chunk dicts with content, metadata, and distance
        """
        if not query.strip():
            return []

        top_k = max(1, min(int(top_k), 10))
        q_emb = self._embed_texts([query.strip()])[0]

        # Build where clause: always filter by session_id, optionally by filename
        res = self.collection.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            where=self._where(session_id, filename, workspace_id),
            include=["documents", "metadatas", "distances"],
        )

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        out: list[RAGChunk] = []
        for doc, meta, dist in zip(docs, metas, dists):
            out.append(self._chunk(doc, meta or {}, dist))
        return out

    def retrieve_all(
        self,
        session_id: str,
        filename: str | None = None,
        max_chars: int = 20_000,
        workspace_id: str | None = None,
    ) -> list[RAGChunk]:
        """Return ordered source chunks for whole-document requests."""
        res = self.collection.get(
            where=self._where(session_id, filename, workspace_id),
            include=["documents", "metadatas"],
        )
        items = sorted(
            zip(res.get("documents") or [], res.get("metadatas") or []),
            key=lambda item: (
                str((item[1] or {}).get("filename", "")),
                int((item[1] or {}).get("chunk_index", 0)),
            ),
        )

        out: list[RAGChunk] = []
        total = 0
        for document, metadata in items:
            if total and total + len(document) > max_chars:
                break
            out.append(self._chunk(document, metadata or {}, None))
            total += len(document)
        return out

    def file_chunk_counts(self, session_id: str, workspace_id: str | None = None) -> dict[str, int]:
        result = self.collection.get(
            where=self._where(session_id, workspace_id=workspace_id),
            include=["metadatas"],
        )
        counts: dict[str, int] = {}
        workspace_dir = (Path(settings.storage_dir).resolve() / "workspaces" / workspace_id).resolve() if workspace_id else None
        for metadata in result.get("metadatas") or []:
            if workspace_dir and Path(str((metadata or {}).get("document_id") or "")).parent != workspace_dir:
                continue
            filename = str((metadata or {}).get("filename") or "")
            if filename:
                counts[filename] = counts.get(filename, 0) + 1
        return counts

    def delete_file(self, session_id: str, filename: str, workspace_id: str | None = None) -> int:
        where = (
            {"$and": [
                {"workspace_id": workspace_id},
                {"document_id": str((Path(settings.storage_dir).resolve() / "workspaces" / workspace_id / filename).resolve())},
            ]}
            if workspace_id else self._where(session_id, filename)
        )
        existing = self.collection.get(where=where, include=[])
        count = len(existing.get("ids") or [])
        if count:
            self.collection.delete(where=where)
        return count

    def clear_session(self, session_id: str) -> None:
        """Delete all Chroma chunks owned by a legacy session."""
        self.collection.delete(where={"session_id": session_id})

    def backfill_legacy_workspace_metadata(self, workspace_id: str) -> int:
        """Attach old session-only chunks to Default without re-embedding."""
        result = self.collection.get(include=["metadatas"])
        updates = [(item_id, {**(meta or {}), "workspace_id": workspace_id})
                   for item_id, meta in zip(result.get("ids") or [], result.get("metadatas") or [])
                   if not (meta or {}).get("workspace_id")]
        if updates:
            self.collection.update(ids=[item[0] for item in updates], metadatas=[item[1] for item in updates])
        return len(updates)

    def workspace_snapshot(self, workspace_id: str) -> dict:
        return self.collection.get(
            where={"workspace_id": workspace_id},
            include=["embeddings", "documents", "metadatas"],
        )

    def delete_workspace_chunks(self, workspace_id: str) -> None:
        self.collection.delete(where={"workspace_id": workspace_id})

    def restore_workspace_chunks(self, snapshot: dict) -> None:
        if snapshot.get("ids"):
            self.collection.upsert(
                ids=snapshot["ids"],
                embeddings=snapshot["embeddings"],
                documents=snapshot["documents"],
                metadatas=snapshot["metadatas"],
            )
