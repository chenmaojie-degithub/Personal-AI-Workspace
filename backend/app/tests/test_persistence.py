from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import database
from app.main import create_app
from app.providers.base import LLMResponse, LLMUsage, ProviderToolCall
from app.rag.models import RAGChunk


class SequenceProvider:
    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        return self.responses.pop(0)


def response(
    content: str,
    usage: LLMUsage | None,
    tool_calls: tuple[ProviderToolCall, ...] = (),
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        model="deepseek-flash",
        provider="deepseek",
        usage=usage,
    )


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = (Path(self.temp_dir.name) / "test.sqlite3").as_posix()
        self.database_url = f"sqlite:///{database_path}"
        self.database_setting = patch.object(database.settings, "database_url", self.database_url)
        self.database_setting.start()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        self.database_setting.stop()
        self.temp_dir.cleanup()

    def post_chat(self, provider: SequenceProvider, content: str = "hello", **settings: bool):
        with patch("app.api.routes.chat.create_llm_provider", return_value=provider):
            return self.client.post(
                "/chat",
                json={
                    "messages": [{"role": "user", "content": content}],
                    "settings": settings,
                },
            )

    def test_normal_chat_messages_usage_and_query_endpoints(self) -> None:
        chat = self.post_chat(SequenceProvider(response("answer", LLMUsage(10, 4, 14))))
        session_id = chat.json()["session_id"]

        messages = self.client.get(f"/sessions/{session_id}/messages").json()
        summary = self.client.get("/usage/summary").json()

        self.assertEqual([item["role"] for item in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["content"], "hello")
        self.assertEqual(messages[1]["content"], "answer")
        self.assertEqual(
            summary,
            {
                "request_count": 1,
                "total_prompt_tokens": 10,
                "total_completion_tokens": 4,
                "total_tokens": 14,
            },
        )

    def test_sessions_list_uses_first_user_message_and_latest_activity(self) -> None:
        first = self.post_chat(SequenceProvider(response("answer A", None)), "FastAPI 是什么").json()["session_id"]
        second = self.post_chat(SequenceProvider(response("answer B", None)), "介绍 PostgreSQL").json()["session_id"]

        sessions = self.client.get("/sessions")
        self.assertEqual(sessions.status_code, 200)
        self.assertEqual([item["session_id"] for item in sessions.json()], [second, first])
        self.assertEqual([item["title"] for item in sessions.json()], ["介绍 PostgreSQL", "FastAPI 是什么"])
        self.assertTrue(all(item["updated_at"] for item in sessions.json()))

    def test_delete_session_removes_only_its_messages_and_usage(self) -> None:
        first = self.post_chat(SequenceProvider(response("answer A", LLMUsage(5, 2, 7))), "A").json()["session_id"]
        second = self.post_chat(SequenceProvider(response("answer B", LLMUsage(3, 1, 4))), "B").json()["session_id"]

        deleted = self.client.delete(f"/sessions/{first}")

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted_messages"], 2)
        self.assertEqual(deleted.json()["deleted_usage"], 1)
        self.assertEqual(self.client.get(f"/sessions/{first}/messages").json(), [])
        self.assertEqual(len(self.client.get(f"/sessions/{second}/messages").json()), 2)
        self.assertEqual(self.client.get("/usage/summary").json()["total_tokens"], 4)
        self.assertEqual([item["session_id"] for item in self.client.get("/sessions").json()], [second])

    def test_tool_call_saves_accumulated_usage(self) -> None:
        tool_call = ProviderToolCall("call-1", "search_web", '{"query":"test"}')
        provider = SequenceProvider(
            response("", LLMUsage(20, 5, 25), (tool_call,)),
            response("done", LLMUsage(30, 7, 37)),
        )

        self.post_chat(provider, "search", web_search=True)

        self.assertEqual(self.client.get("/usage/summary").json()["total_tokens"], 62)

    def test_rag_chat_saves_usage(self) -> None:
        provider = SequenceProvider(response("from document", LLMUsage(40, 8, 48)))
        with patch("app.api.routes.chat._should_use_rag", return_value=True), patch(
            "app.api.routes.chat.RAGService"
        ) as rag_service, patch("app.api.routes.chat.create_llm_provider", return_value=provider):
            rag_service.return_value.retrieve.return_value = [
                RAGChunk("document text", "note.txt", "doc-1", 0, 0.1)
            ]
            self.client.post("/chat", json={"messages": [{"role": "user", "content": "question"}]})

        self.assertEqual(self.client.get("/usage/summary").json()["total_tokens"], 48)

    def test_null_usage_saves_messages_but_no_usage_row(self) -> None:
        chat = self.post_chat(SequenceProvider(response("answer", None)))
        session_id = chat.json()["session_id"]

        self.assertEqual(len(self.client.get(f"/sessions/{session_id}/messages").json()), 2)
        self.assertEqual(self.client.get("/usage/summary").json()["request_count"], 0)

    def test_postgresql_url_without_driver_has_clear_error(self) -> None:
        with patch.object(database.settings, "database_url", "postgresql://localhost/ai_chat"), patch.dict(
            sys.modules, {"psycopg": None}
        ):
            with self.assertRaisesRegex(RuntimeError, "psycopg"):
                database.get_usage_summary()


if __name__ == "__main__":
    unittest.main()
