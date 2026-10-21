"""Serve the actual app with offline model/search doubles and disposable data.

Run from backend: .venv/Scripts/python.exe -m scripts.serve_citation_replay
Open the regular Vite frontend. Prompts containing 'invalid', 'disconnect', or
'slow' exercise validation, provider failure, or client cancellation. Never use
this harness as a production server; all chat/search responses are test data.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import uvicorn
import httpx

from app.core import database
from app.main import create_app
from app.tests.test_citations import KNOWLEDGE_RESULT, WEB_RESULTS, ReplayProvider


class BrowserReplayProvider(ReplayProvider):
    def stream(self, messages, tools=None, max_tokens=None):
        prompt = next(item["content"] for item in reversed(messages) if item["role"] == "user").lower()
        self.invalid = "[999]" if "invalid" in prompt else None
        self.fail = "disconnect" in prompt
        for event in super().stream(messages, tools, max_tokens):
            if event.type == "message":
                time.sleep(0.2 if "slow" in prompt else 0.015)
            yield event


def main():
    with tempfile.TemporaryDirectory(prefix="paw-citation-replay-") as directory, ExitStack() as stack:
        root = Path(directory)
        for key, value in {
            "database_url": "sqlite:///" + (root / "replay.sqlite3").as_posix(),
            "storage_dir": str(root / "storage"),
            "chroma_persist_dir": str(root / "chroma"),
            "cors_origins": "http://127.0.0.1:5173,http://localhost:5173",
        }.items():
            stack.enter_context(patch.object(database.settings, key, value))
        stack.enter_context(patch("app.api.routes.chat_stream.create_llm_provider", side_effect=lambda *args: BrowserReplayProvider()))
        stack.enter_context(patch("app.agents.orchestrator.create_llm_provider", side_effect=lambda *args: BrowserReplayProvider(agent=True)))
        stack.enter_context(patch("app.api.routes.chat.create_llm_provider", side_effect=AssertionError("Only streaming replay is configured")))
        stack.enter_context(patch("app.tools.registry.web_search", return_value={"results": WEB_RESULTS}))
        stack.enter_context(patch("app.tools.registry.search_knowledge", return_value=KNOWLEDGE_RESULT))
        stack.enter_context(patch("app.services.search_providers.ExaProvider.search", side_effect=AssertionError("Live Exa forbidden")))
        database.list_workspaces()
        database.update_workspace(database.DEFAULT_WORKSPACE_ID, {"name": "Offline citation acceptance", "tool_settings": {"web_search": True}})
        print("OFFLINE REPLAY ONLY: temporary database; no real Exa/LLM requests", flush=True)
        uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="warning")


def check_http():
    """Run against this offline server only, via actual loopback TCP/HTTP."""
    def events(response):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        kind = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                yield kind, json.loads(line[6:])

    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
        workspace = client.get("/workspaces").json()[0]
        assert workspace["name"] == "Offline citation acceptance", "Refusing to call a non-replay server"
        for scenario in ("direct", "agent", "invalid", "disconnect", "cancel", "close"):
            session = "http-citations-" + scenario
            prompt = "search the web for agent frameworks"
            if scenario in {"agent", "invalid", "disconnect", "cancel"}:
                prompt = "Research and compare web sources with the knowledge document " + scenario
            if scenario in {"cancel", "close"}:
                prompt += " slow"
            body = {"session_id": session, "workspace_id": workspace["id"], "messages": [{"role": "user", "content": prompt}]}
            observed = []
            run_id = None
            with client.stream("POST", "/chat/stream", json=body) as response:
                for kind, data in events(response):
                    observed.append((kind, data))
                    if kind == "agent_run":
                        run_id = data["run_id"]
                    if kind == "message" and scenario == "cancel":
                        assert run_id
                        cancelled = client.post(f"/agent-runs/{run_id}/cancel", params={"workspace_id": workspace["id"]})
                        assert cancelled.status_code == 200
                        scenario = "cancelled"
                    if kind == "message" and scenario == "close":
                        break
            if scenario == "close":
                time.sleep(0.5)  # Allow ASGI to observe the closed TCP response.
            history = client.get(f"/sessions/{session}/messages", params={"workspace_id": workspace["id"]}).json()
            kinds = [kind for kind, _ in observed]
            content = "".join(data["content"] for kind, data in observed if kind == "message")
            if scenario in {"direct", "agent"}:
                sources = [data for kind, data in observed if kind == "source"]
                assert kinds[-1] == "done" and "error" not in kinds
                assert "Qwen-Agent 【3】" in content and sources[2]["url"] == WEB_RESULTS[2]["url"]
                assert kinds.index("source") < kinds.index("message")
                assert history[-1]["content"] == content and history[-1]["sources"] == sources
            else:
                assert not history and "done" not in kinds
                if scenario in {"invalid", "disconnect"}:
                    assert "error" in kinds
                if scenario == "invalid":
                    assert "[999]" not in content
                if scenario == "cancelled":
                    assert any(kind == "agent_status" and data["status"] == "cancelled" for kind, data in observed)
            print(f"PASS HTTP {scenario}: {len(observed)} SSE events", flush=True)


if __name__ == "__main__":
    check_http() if "--check" in sys.argv else main()
