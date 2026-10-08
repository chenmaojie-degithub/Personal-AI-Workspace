from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chromadb.api.client import SharedSystemClient

from app.core.config import settings
from app.rag.service import RAGService
from app.tools.knowledge import knowledge_citations, read_document, search_knowledge
from app.tools.registry import get_agent_tool_specs
from app.tools.registry import execute_tool_call
from app.models.chat import ChatSettings


class FakeEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class KnowledgeToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = self.root = Path(self.temp_dir.name)
        self.patches = [
            patch.object(settings, "chroma_persist_dir", str(root / "chroma")),
            patch.object(settings, "chroma_collection", "knowledge_tool_chunks"),
        ]
        for item in self.patches:
            item.start()
        self.rag = RAGService()
        self.rag._embedding_provider = FakeEmbeddingProvider()
        first = root / "first.txt"
        second = root / "second.txt"
        first.write_text("alpha workspace evidence", encoding="utf-8")
        second.write_text("beta private evidence", encoding="utf-8")
        self.rag.ingest_files(
            "session-1", [first], "workspace-1",
            {"first.txt": {"document_id": "doc-1", "schema_version": 1}},
        )
        self.rag.ingest_files(
            "session-2", [second], "workspace-2",
            {"second.txt": {"document_id": "doc-2", "schema_version": 1}},
        )
        self.service_patch = patch("app.tools.knowledge.get_rag_service", return_value=self.rag)
        self.service_patch.start()

    def tearDown(self) -> None:
        self.service_patch.stop()
        system = self.rag.client._system
        self.rag.collection = None
        self.rag.client = None
        system.stop()
        SharedSystemClient.clear_system_cache()
        del self.rag
        gc.collect()
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_search_and_read_are_workspace_scoped(self) -> None:
        result = search_knowledge("session-1", "workspace-1", "evidence")
        self.assertEqual([item["document_id"] for item in result["results"]], ["doc-1"])
        self.assertEqual(read_document("session-1", "workspace-1", "doc-2")["total_chunks"], 0)

        read = read_document("session-1", "workspace-1", "doc-1", max_chars=500)
        self.assertTrue(read["complete"])
        self.assertEqual(read["chunks"][0]["filename"], "first.txt")

    def test_results_create_only_knowledge_citations(self) -> None:
        result = search_knowledge("session-1", "workspace-1", "alpha")
        citations = knowledge_citations(result)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].type, "knowledge")
        self.assertIsNone(citations[0].url)
        self.assertEqual(citations[0].document_id, "doc-1")

    def test_agent_registry_uses_server_scoped_knowledge_tools(self) -> None:
        specs = {item.name: item for item in get_agent_tool_specs(ChatSettings(), "session-1", "workspace-1")}
        self.assertIn("search_knowledge", specs)
        self.assertIn("read_document", specs)
        self.assertNotIn("workspace_id", specs["search_knowledge"].parameters_schema["properties"])
        self.assertNotIn("session_id", specs["read_document"].parameters_schema["properties"])

        associated = {
            item.name: item
            for item in get_agent_tool_specs(ChatSettings(), "session-1", "workspace-1", ["doc-1"])
        }
        with self.assertRaisesRegex(ValueError, "associated"):
            execute_tool_call(associated, "read_document", '{"document_id":"doc-2"}')

    def test_agent_searches_only_all_associated_documents(self) -> None:
        for name, document_id, content in [
            ("third.txt", "doc-3", "gamma associated evidence"),
            ("private.txt", "doc-4", "private unassociated evidence"),
        ]:
            path = self.root / name
            path.write_text(content, encoding="utf-8")
            self.rag.ingest_files(
                "session-1", [path], "workspace-1",
                {name: {"document_id": document_id, "schema_version": 1}},
            )
        specs = {
            item.name: item
            for item in get_agent_tool_specs(ChatSettings(), "session-1", "workspace-1", ["doc-1", "doc-3"])
        }
        result = execute_tool_call(specs, "search_knowledge", '{"query":"evidence","top_k":10}')
        self.assertEqual({item["document_id"] for item in result["results"]}, {"doc-1", "doc-3"})

    def test_long_document_reads_in_ordered_segments(self) -> None:
        path = self.root / "long.txt"
        path.write_text("\n\n".join(f"Section {index}: " + "content " * 120 for index in range(20)), encoding="utf-8")
        self.rag.ingest_files(
            "session-1", [path], "workspace-1",
            {"long.txt": {"document_id": "doc-long", "schema_version": 1}},
        )
        first = read_document("session-1", "workspace-1", "doc-long", max_chars=500)
        self.assertFalse(first["complete"])
        self.assertIsNotNone(first["next_cursor"])
        second = read_document("session-1", "workspace-1", "doc-long", cursor=first["next_cursor"], max_chars=500)
        self.assertGreater(second["cursor"], first["cursor"])
        self.assertNotEqual(second["chunks"][0]["chunk_index"], first["chunks"][0]["chunk_index"])

    def test_pdf_page_metadata_becomes_a_knowledge_citation(self) -> None:
        citations = knowledge_citations({
            "type": "document_read",
            "chunks": [{
                "content": "Page evidence", "filename": "report.pdf", "document_id": "doc-pdf",
                "chunk_index": 2, "page_number": 7, "section": "Results",
            }],
        })
        self.assertEqual((citations[0].type, citations[0].page_number, citations[0].section), ("knowledge", 7, "Results"))

    def test_legacy_vectors_are_backfilled_without_reembedding(self) -> None:
        self.rag.collection.add(
            ids=["legacy:doc:0"], embeddings=[[20.0, 1.0, 0.0]], documents=["legacy evidence"],
            metadatas=[{"session_id": "legacy", "document_id": "legacy-doc", "filename": "legacy.txt", "chunk_index": 0}],
        )
        self.assertEqual(self.rag.backfill_legacy_workspace_metadata("workspace-1"), 1)
        result = self.rag.retrieve("new-session", "legacy", workspace_id="workspace-1", document_id="legacy-doc")
        self.assertEqual([item.document_id for item in result], ["legacy-doc"])


if __name__ == "__main__":
    unittest.main()
