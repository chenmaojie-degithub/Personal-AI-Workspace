from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import database


class DocumentMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        path = (Path(self.temp_dir.name) / "documents.sqlite3").as_posix()
        self.setting = patch.object(database.settings, "database_url", f"sqlite:///{path}")
        self.setting.start()

    def tearDown(self) -> None:
        self.setting.stop()
        self.temp_dir.cleanup()

    def test_document_lifecycle_and_workspace_scope(self) -> None:
        workspace = database.create_workspace("Documents")
        item = database.create_document_record(
            filename="report.pdf", content_type="application/pdf", byte_size=123,
            content_sha256="abc123", workspace_id=workspace["id"], session_id="session-1",
        )
        self.assertEqual(item["status"], "uploaded")
        self.assertEqual(item["extension"], ".pdf")
        self.assertIsNone(database.get_document_record(item["id"], database.DEFAULT_WORKSPACE_ID))

        database.update_document_record(item["id"], status="indexed", chunk_count=7)
        restored = database.find_document_by_hash("abc123", workspace_id=workspace["id"])
        self.assertEqual((restored["status"], restored["chunk_count"]), ("indexed", 7))
        self.assertEqual(database.find_document_by_name("report.pdf", workspace_id=workspace["id"])["id"], item["id"])
        self.assertTrue(database.delete_document_record(item["id"]))
        self.assertEqual(database.list_document_records(workspace_id=workspace["id"]), [])

    def test_duplicate_filename_is_rejected_per_scope(self) -> None:
        workspace = database.create_workspace("Documents")
        arguments = dict(
            filename="same.txt", content_type="text/plain", byte_size=3,
            content_sha256="first", workspace_id=workspace["id"],
        )
        database.create_document_record(**arguments)
        with self.assertRaises(Exception):
            database.create_document_record(**{**arguments, "content_sha256": "second"})


if __name__ == "__main__":
    unittest.main()
