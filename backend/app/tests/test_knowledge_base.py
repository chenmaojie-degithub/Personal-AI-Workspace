from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chromadb.api.client import SharedSystemClient
from fastapi.testclient import TestClient

from app.api.routes import files as files_route
from app.core.config import settings
from app.main import create_app
from app.rag.service import RAGService


class FakeEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.storage_patch = patch.object(settings, "storage_dir", str(root / "storage"))
        self.chroma_patch = patch.object(settings, "chroma_persist_dir", str(root / "chroma"))
        self.collection_patch = patch.object(settings, "chroma_collection", "test_rag_chunks")
        self.database_patch = patch.object(settings, "database_url", f"sqlite:///{(root / 'business.sqlite3').as_posix()}")
        self.storage_patch.start()
        self.chroma_patch.start()
        self.collection_patch.start()
        self.database_patch.start()

        self.rag = RAGService()
        self.rag._embedding_provider = FakeEmbeddingProvider()
        self.service_patch = patch.object(files_route, "RAGService", return_value=self.rag)
        self.service_patch.start()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        self.service_patch.stop()
        system = self.rag.client._system
        self.rag.collection = None
        self.rag.client = None
        system.stop()
        SharedSystemClient.clear_system_cache()
        del self.rag
        gc.collect()
        self.collection_patch.stop()
        self.database_patch.stop()
        self.chroma_patch.stop()
        self.storage_patch.stop()
        self.temp_dir.cleanup()

    def test_upload_list_and_delete_file_with_chunks(self) -> None:
        upload = self.client.post(
            "/files/upload",
            files={"files": ("note.txt", b"knowledge base text", "text/plain")},
        )
        self.assertEqual(upload.status_code, 200)
        session_id = upload.json()["session_id"]
        document_id = upload.json()["stored"][0]["document_id"]
        self.assertNotEqual(document_id, "note.txt")
        self.assertEqual(upload.json()["stored"][0]["status"], "indexed")

        listing = self.client.get("/files", params={"session_id": session_id})
        item = listing.json()["files"][0]
        self.assertEqual(item["filename"], "note.txt")
        self.assertEqual(item["document_id"], document_id)
        self.assertEqual(item["status"], "indexed")
        self.assertGreater(item["chunk_count"], 0)
        self.assertEqual(self.rag.file_chunk_counts(session_id)["note.txt"], item["chunk_count"])
        self.assertEqual(self.rag.retrieve(session_id, "knowledge")[0].document_id, document_id)

        deleted = self.client.delete(f"/files/note.txt", params={"session_id": session_id})
        self.assertEqual(deleted.status_code, 200)
        self.assertGreater(deleted.json()["deleted_chunks"], 0)
        self.assertEqual(self.rag.file_chunk_counts(session_id).get("note.txt", 0), 0)
        self.assertEqual(
            self.client.get("/files", params={"session_id": session_id}).json()["files"],
            [],
        )
        self.assertFalse((Path(settings.storage_dir) / session_id / "note.txt").exists())

    def test_failed_ingest_is_visible_in_file_status(self) -> None:
        with patch.object(self.rag, "ingest_files", side_effect=RuntimeError("embedding unavailable")):
            upload = self.client.post(
                "/files/upload",
                files={"files": ("failed.txt", b"saved but not indexed", "text/plain")},
            )

        self.assertEqual(upload.status_code, 200)
        self.assertIsNotNone(upload.json()["ingest_error"])
        session_id = upload.json()["session_id"]
        item = self.client.get("/files", params={"session_id": session_id}).json()["files"][0]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["chunk_count"], 0)
        self.assertIn("embedding unavailable", item["ingest_error"])

    def test_upload_rejects_unsupported_invalid_and_duplicate_files(self) -> None:
        unsupported = self.client.post(
            "/files/upload", files={"files": ("payload.exe", b"binary", "application/octet-stream")},
        )
        self.assertEqual(unsupported.status_code, 400)

        fake_pdf = self.client.post(
            "/files/upload", files={"files": ("fake.pdf", b"not a pdf", "application/pdf")},
        )
        self.assertEqual(fake_pdf.status_code, 400)

        first = self.client.post(
            "/files/upload", files={"files": ("first.txt", b"same content", "text/plain")},
        )
        session_id = first.json()["session_id"]
        duplicate = self.client.post(
            "/files/upload", data={"session_id": session_id},
            files={"files": ("second.txt", b"same content", "text/plain")},
        )
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__":
    unittest.main()
