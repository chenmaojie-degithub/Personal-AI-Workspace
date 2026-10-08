from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import database
from app.main import create_app


class ProjectTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        path = (Path(self.temp.name) / "project-tree.sqlite3").as_posix()
        self.setting = patch.object(database.settings, "database_url", f"sqlite:///{path}")
        self.setting.start()
        self.client = TestClient(create_app())
        self.workspace = self.client.post("/workspaces", json={"name": "Projects"}).json()
        self.other = self.client.post("/workspaces", json={"name": "Other"}).json()
        database.save_chat_turn("one", "First", "Answer", None, None, None, self.workspace["id"])
        database.save_chat_turn("two", "Second", "Answer", None, None, None, self.workspace["id"])

    def tearDown(self) -> None:
        self.setting.stop()
        self.temp.cleanup()

    def add_folder(self, name: str, parent_id: str | None = None) -> dict:
        response = self.client.post(
            "/projects/folders",
            json={"workspace_id": self.workspace["id"], "name": name, "parent_id": parent_id},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def move(self, item_type: str, item_id: str, parent_id: str | None, position: int = 0):
        return self.client.post(
            "/projects/move",
            json={
                "workspace_id": self.workspace["id"], "item_type": item_type,
                "item_id": item_id, "parent_id": parent_id, "position": position,
            },
        )

    def test_hierarchy_and_session_order_persist(self) -> None:
        parent = self.add_folder("Agent")
        child = self.add_folder("Research", parent["id"])
        moved = self.move("session", "two", child["id"])
        self.assertEqual(moved.status_code, 200)
        session = next(item for item in moved.json()["sessions"] if item["session_id"] == "two")
        self.assertEqual(session["folder_id"], child["id"])
        refreshed = self.client.get("/projects/tree", params={"workspace_id": self.workspace["id"]}).json()
        self.assertEqual(next(item for item in refreshed["folders"] if item["id"] == child["id"])["parent_id"], parent["id"])
        self.assertEqual(next(item for item in refreshed["sessions"] if item["session_id"] == "two")["folder_id"], child["id"])

    def test_rejects_cross_workspace_and_folder_cycles(self) -> None:
        parent = self.add_folder("Parent")
        child = self.add_folder("Child", parent["id"])
        cross = self.client.post(
            "/projects/move",
            json={
                "workspace_id": self.other["id"], "item_type": "session", "item_id": "one",
                "parent_id": None, "position": 0,
            },
        )
        self.assertEqual(cross.status_code, 422)
        cycle = self.move("folder", parent["id"], child["id"])
        self.assertEqual(cycle.status_code, 422)
        tree = self.client.get("/projects/tree", params={"workspace_id": self.workspace["id"]}).json()
        self.assertIsNone(next(item for item in tree["folders"] if item["id"] == parent["id"])["parent_id"])


if __name__ == "__main__":
    unittest.main()
