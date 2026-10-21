from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import database
from app.providers.base import LLMUsage


class AgentPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        path = (Path(self.temp_dir.name) / "agent.sqlite3").as_posix()
        self.setting = patch.object(database.settings, "database_url", f"sqlite:///{path}")
        self.setting.start()

    def tearDown(self) -> None:
        self.setting.stop()
        self.temp_dir.cleanup()

    def test_run_and_steps_are_workspace_scoped_and_restorable(self) -> None:
        workspace = database.create_workspace("Agent Workspace")
        run = database.create_agent_run("run-1", "session-1", workspace["id"], "Compare two sources")
        self.assertEqual(run["status"], "planning")

        plan = [{"index": 1, "title": "Search the web"}]
        database.update_agent_run("run-1", status="running", plan=plan)
        database.upsert_agent_step(
            "run-1", 1, "Search the web", "running",
            tool_name="search_web", input_data={"query": "example"},
        )
        database.upsert_agent_step(
            "run-1", 1, "Search the web", "completed",
            tool_name="search_web", input_data={"query": "example"}, output_preview="one result",
        )
        database.update_agent_run(
            "run-1", status="completed", provider="deepseek", model="test",
            usage=LLMUsage(10, 5, 15), completed=True,
        )

        restored = database.latest_agent_run("session-1", workspace["id"])
        self.assertIsNotNone(restored)
        self.assertEqual(restored["plan"], plan)
        self.assertEqual(restored["total_tokens"], 15)
        self.assertEqual(restored["steps"][0]["status"], "completed")
        self.assertEqual(restored["steps"][0]["input"], {"query": "example"})
        self.assertIsNone(database.get_agent_run("run-1", database.DEFAULT_WORKSPACE_ID))

    def test_session_and_workspace_deletion_remove_agent_records(self) -> None:
        workspace = database.create_workspace("Disposable")
        database.create_agent_run("run-session", "session-delete", database.DEFAULT_WORKSPACE_ID, "Goal")
        database.upsert_agent_step("run-session", 1, "Step", "completed")
        database.delete_session("session-delete")
        self.assertIsNone(database.get_agent_run("run-session"))

        database.create_agent_run("run-workspace", "session-workspace", workspace["id"], "Goal")
        database.upsert_agent_step("run-workspace", 1, "Step", "completed")
        database.delete_workspace_business(workspace["id"])
        self.assertIsNone(database.get_agent_run("run-workspace"))


if __name__ == "__main__":
    unittest.main()
