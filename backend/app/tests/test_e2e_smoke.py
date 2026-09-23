from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure `backend/` is on sys.path when tests are executed via `pytest`.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app
from app.core.config import settings


def test_e2e_smoke_health_files_chat_without_openai(tmp_path: Path, monkeypatch):
    """Light e2e smoke: ensures routes are wired and behave deterministically.

    This test does NOT call OpenAI.
    - /health should work
    - /files/upload should index with local embeddings without an OpenAI key
    - /chat should return a structured error when the chat provider key is missing
    """

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "chroma_persist_dir", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{(tmp_path / 'business.sqlite3').as_posix()}")
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    monkeypatch.setattr(settings, "openai_api_key", None)

    app = create_app()
    client = TestClient(app)

    # health
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    # upload
    r = client.post(
        "/files/upload",
        files={"files": ("note.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 200
    payload = r.json()
    assert "session_id" in payload
    assert payload.get("stored")
    assert payload["ingest"]["stored"] == 1
    assert payload["ingest_error"] is None

    session_id = payload["session_id"]

    # list files
    r = client.get("/files", params={"session_id": session_id})
    assert r.status_code == 200
    files_payload = r.json()
    assert files_payload["session_id"] == session_id
    assert any(f["filename"] == "note.txt" for f in files_payload["files"])

    # chat (should return error but still be a valid response model)
    r = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "messages": [{"role": "user", "content": "Summarize my uploaded file."}],
            "settings": {
                "web_search": False,
                "image_generation": False,
                "data_analysis": False,
                "think_mode": False,
            },
        },
    )
    assert r.status_code == 200
    chat_payload = r.json()
    assert chat_payload["session_id"] == session_id
    assert chat_payload["assistant_message"] is None
    assert chat_payload["error"]
