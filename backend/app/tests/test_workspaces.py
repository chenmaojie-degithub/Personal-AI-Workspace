from __future__ import annotations

import sqlite3
import gc
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from chromadb.api.client import SharedSystemClient

from app.api.routes.chat import _build_system_prompt, orchestrate_chat, resolve_workspace_request
from app.core import database
from app.core.config import settings
from app.main import create_app
from app.models.chat import ChatMessage, ChatRequest
from app.providers.base import LLMResponse, LLMUsage
from app.rag.service import RAGService
from app.tools.registry import get_enabled_tool_specs


class FakeEmbeddings:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), float(text.count("FastAPI")), 1.0] for text in texts]


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(settings, "database_url", f"sqlite:///{(self.root / 'business.sqlite3').as_posix()}"),
            patch.object(settings, "storage_dir", str(self.root / "storage")),
            patch.object(settings, "chroma_persist_dir", str(self.root / "chroma")),
            patch.object(settings, "chroma_collection", "workspace_test_chunks"),
            patch("app.rag.service.create_embedding_provider", return_value=FakeEmbeddings()),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        if hasattr(self, "rag"):
            system = self.rag.client._system
            self.rag.collection = None
            self.rag.client = None
            system.stop()
            SharedSystemClient.clear_system_cache()
            del self.rag
            gc.collect()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_legacy_backfill_is_idempotent_and_sessions_are_isolated(self) -> None:
        path = self.root / "business.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, created_at TEXT)")
            connection.execute("CREATE TABLE token_usage (id INTEGER PRIMARY KEY, session_id TEXT, provider TEXT, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, created_at TEXT)")
            connection.execute("INSERT INTO chat_messages VALUES (1, 'legacy', 'user', 'old chat', '2025-01-01')")
            connection.execute("INSERT INTO token_usage VALUES (1, 'legacy', 'deepseek', 'm', 2, 3, 5, '2025-01-01')")
            connection.commit()

        default = self.client.get("/workspaces").json()[0]
        self.assertTrue(default["is_default"])
        self.assertEqual(self.client.get("/workspaces").json()[0]["id"], default["id"])
        self.assertEqual([item["session_id"] for item in self.client.get("/sessions", params={"workspace_id": default["id"]}).json()], ["legacy"])

        a = self.client.post("/workspaces", json={"name": "Programming", "default_model_id": "deepseek", "system_prompt": "Answer as a programming tutor.", "tool_settings": {"think_mode": True}}).json()
        b = self.client.post("/workspaces", json={"name": "English"}).json()
        self.assertNotEqual(a["id"], b["id"])
        database.save_chat_turn("a-chat", "FastAPI question", "answer", "deepseek", "m", LLMUsage(2, 3, 5), a["id"])
        database.save_chat_turn("b-chat", "English question", "answer", "deepseek", "m", LLMUsage(2, 3, 5), b["id"])
        self.assertEqual([item["session_id"] for item in self.client.get("/sessions", params={"workspace_id": a["id"]}).json()], ["a-chat"])
        self.assertEqual(self.client.get("/sessions/a-chat/messages", params={"workspace_id": b["id"]}).json(), [])
        with self.assertRaisesRegex(ValueError, "different workspace"):
            database.save_chat_turn("a-chat", "wrong", "wrong", None, None, None, b["id"])
        self.assertEqual(len(database.list_messages("a-chat")), 2)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id='legacy'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT SUM(total_tokens) FROM token_usage WHERE session_id='legacy'").fetchone()[0], 5)

        req = resolve_workspace_request(ChatRequest(workspace_id=a["id"], messages=[ChatMessage(role="user", content="hi")]))
        self.assertEqual(req.model_id, "deepseek")
        self.assertTrue(req.settings.think_mode)
        self.assertIn("Answer as a programming tutor.", _build_system_prompt(req, []))
        overridden = resolve_workspace_request(ChatRequest(workspace_id=a["id"], model_id="openrouter/free", messages=[ChatMessage(role="user", content="hi")]))
        self.assertEqual(overridden.model_id, "openrouter/free")
        updated = self.client.patch(f"/workspaces/{a['id']}", json={"tool_settings": {"web_search": True, "think_mode": True}})
        self.assertEqual(updated.status_code, 200)
        configured = resolve_workspace_request(ChatRequest(workspace_id=a["id"], messages=[ChatMessage(role="user", content="search")]))
        self.assertEqual([tool.name for tool in get_enabled_tool_specs(configured.settings)], ["search_web"])
        disabled = resolve_workspace_request(ChatRequest(
            workspace_id=b["id"], messages=[ChatMessage(role="user", content="search")],
            settings={"web_search": True},
        ))
        self.assertFalse(disabled.settings.web_search)
        captured = []
        class CaptureProvider:
            def complete(self, messages, tools=None):
                captured.append((messages, tools))
                return LLMResponse(content="ok", tool_calls=(), model="deepseek-test", provider="deepseek", usage=None)
        with patch("app.api.routes.chat.create_llm_provider", return_value=CaptureProvider()):
            result = orchestrate_chat(ChatRequest(workspace_id=a["id"], session_id="prompt-test", messages=[ChatMessage(role="user", content="hello")]))
        self.assertIsNone(result.error)
        self.assertIn("Answer as a programming tutor.", captured[0][0][0]["content"])
        self.assertEqual(captured[0][1][0]["function"]["name"], "search_web")
        self.assertEqual(self.client.delete(f"/workspaces/{default['id']}").status_code, 403)

    def test_workspace_rag_isolation_and_compensated_delete(self) -> None:
        a = self.client.post("/workspaces", json={"name": "Programming"}).json()
        b = self.client.post("/workspaces", json={"name": "English"}).json()
        for workspace, content in [(a, b"FastAPI belongs to Programming"), (b, b"English vocabulary practice")]:
            response = self.client.post("/files/upload", data={"workspace_id": workspace["id"], "session_id": f"session-{workspace['name']}"}, files={"files": ("note.txt", content, "text/plain")})
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["ingest_error"])
        rag = self.rag = RAGService()
        self.assertEqual(len(rag.retrieve("new-session", "FastAPI", workspace_id=a["id"])), 1)
        self.assertEqual(len(rag.retrieve("new-session", "FastAPI", workspace_id=b["id"])), 1)
        self.assertIn("FastAPI", rag.retrieve("new-session", "FastAPI", workspace_id=a["id"])[0].content)
        self.assertNotIn("FastAPI", rag.retrieve("new-session", "FastAPI", workspace_id=b["id"])[0].content)
        self.assertEqual(len(self.client.get("/files", params={"workspace_id": a["id"]}).json()["files"]), 1)
        with patch("app.api.routes.workspaces.delete_workspace_business", side_effect=RuntimeError("simulated database failure")):
            self.assertEqual(self.client.delete(f"/workspaces/{a['id']}").status_code, 500)
        self.assertTrue((self.root / "storage" / "workspaces" / a["id"] / "note.txt").exists())
        self.assertEqual(len(rag.workspace_snapshot(a["id"])["ids"]), 1)
        self.assertIsNotNone(database.get_workspace(a["id"]))
        chart_dir = self.root / "storage" / "analysis_charts" / a["id"]
        chart_dir.mkdir(parents=True)
        (chart_dir / "chart.png").write_bytes(b"chart")
        self.assertEqual(self.client.delete(f"/workspaces/{a['id']}").status_code, 200)
        self.assertEqual(rag.workspace_snapshot(a["id"])["ids"], [])
        self.assertFalse((self.root / "storage" / "workspaces" / a["id"]).exists())
        self.assertFalse(chart_dir.exists())
        self.assertEqual(len(self.client.get("/files", params={"workspace_id": b["id"]}).json()["files"]), 1)
        removed_file = self.client.delete("/files/note.txt", params={"workspace_id": b["id"]})
        self.assertEqual(removed_file.status_code, 200)
        self.assertEqual(rag.workspace_snapshot(b["id"])["ids"], [])
        self.assertFalse((self.root / "storage" / "workspaces" / b["id"] / "note.txt").exists())

    def test_session_manual_title_persists_and_is_workspace_scoped(self) -> None:
        a = self.client.post("/workspaces", json={"name": "A"}).json()
        b = self.client.post("/workspaces", json={"name": "B"}).json()
        database.save_chat_turn("a-chat", "First A question", "answer", None, None, None, a["id"])
        database.save_chat_turn("b-chat", "First B question", "answer", None, None, None, b["id"])
        url = "/sessions/a-chat"
        self.assertEqual(self.client.get("/sessions", params={"workspace_id": a["id"]}).json()[0]["title"], "First A question")
        self.assertEqual(self.client.patch(url, params={"workspace_id": b["id"]}, json={"title": "wrong"}).status_code, 404)
        for title in ("  ", "x" * 101):
            self.assertEqual(self.client.patch(url, params={"workspace_id": a["id"]}, json={"title": title}).status_code, 422)
        renamed = self.client.patch(url, params={"workspace_id": a["id"]}, json={"title": "  Study FastAPI  "})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["title"], "Study FastAPI")
        database.save_chat_turn("a-chat", "Later A question", "answer", None, None, None, a["id"])
        self.assertEqual(self.client.get("/sessions", params={"workspace_id": a["id"]}).json()[0]["title"], "Study FastAPI")
        self.assertEqual(self.client.get("/sessions", params={"workspace_id": b["id"]}).json()[0]["title"], "First B question")
        self.assertEqual(len(self.client.get("/sessions/a-chat/messages", params={"workspace_id": a["id"]}).json()), 4)

    def test_existing_chat_sessions_table_gains_title_without_losing_rows(self) -> None:
        path = self.root / "business.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            connection.execute("INSERT INTO chat_sessions VALUES ('old-session', ?, '2025-01-01', '2025-01-01')", (database.DEFAULT_WORKSPACE_ID,))
            connection.commit()
        database.list_sessions()
        with closing(sqlite3.connect(path)) as connection:
            self.assertIn("title", [column[1] for column in connection.execute("PRAGMA table_info(chat_sessions)")])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chat_sessions WHERE session_id = 'old-session'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
