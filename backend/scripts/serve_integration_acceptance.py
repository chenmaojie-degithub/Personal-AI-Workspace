"""Actual FastAPI/SQLite/Chroma, offline Provider/Embedding, disposable files only.

Run from backend: python -m scripts.serve_integration_acceptance
Loopback port 18800; Vue should use its own origin 5179. Never deploy this harness.
"""
import gc
import json
import os
from pathlib import Path
import tempfile
import time
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch


def main():
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="paw-integration-") as directory, ExitStack() as stack:
        root = Path(directory)
        # Config's relative .env must resolve inside this empty temporary directory.
        os.chdir(root)
        os.environ.update({
            "DATABASE_URL": "sqlite:///" + (root / "business.sqlite3").as_posix(),
            "STORAGE_DIR": str(root / "storage"), "CHROMA_PERSIST_DIR": str(root / "chroma"),
            "MEMORY_ENABLED": "true", "MEMORY_DATABASE_PATH": str(root / "memory.sqlite3"),
            "CORS_ORIGINS": "http://127.0.0.1:5179", "LLM_PROVIDER": "deepseek",
            **{name: "" for name in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                                    "OPENAI_EMBEDDING_API_KEY", "EXA_API_KEY", "POSTGRES_TARGET_PASSWORD")},
        })
        import pytest
        import uvicorn
        from conftest import install_network_guard
        from app.core import database
        from app.core.config import settings
        from app.providers.base import LLMResponse, LLMStreamEvent, LLMUsage, ProviderToolCall
        from app.providers.registry import ModelEntry
        from app.tests.test_citations import ReplayProvider, catalog

        guard = pytest.MonkeyPatch()
        attempts = install_network_guard(guard)
        stack.callback(guard.undo)
        stats = {"provider_calls": 0, "web_calls": 0}

        class OfflineEmbeddings:
            def embed(self, texts):
                return [[1.0, 0.5, 0.25] for _ in texts]

        class IntegrationProvider(ReplayProvider):
            def query(self, messages):
                return next((item["content"] for item in reversed(messages) if item["role"] == "user"), "").lower()

            def answer(self, messages):
                text = "Offline integration answer."
                for item in messages:
                    if item["role"] == "user" and item["content"].startswith("WORKSPACE_MEMORY_JSON\n"):
                        text += " Memory: " + "; ".join(row["value"] for row in json.loads(item["content"].split("\n", 1)[1])) + "."
                for source in catalog(messages):
                    text += " " + (source.get("filename") or source.get("title") or "Evidence") + " " + source["marker"]
                return text

            def complete(self, messages, tools=None, max_tokens=None):
                stats["provider_calls"] += 1
                query = self.query(messages)
                if "timeout" in query:
                    raise TimeoutError("Synthetic Provider timeout")
                if "fail-model" in query:
                    raise RuntimeError("Synthetic Provider failure")
                if self.agent or messages[0]["content"].startswith("Create a concise public execution plan"):
                    self.agent = True
                    return replace(super().complete(messages, tools, max_tokens), usage=LLMUsage(8, 2, 10))
                return LLMResponse(self.answer(messages), (), "integration-mock", "offline", LLMUsage(8, 2, 10))

            def stream(self, messages, tools=None, max_tokens=None):
                stats["provider_calls"] += 1
                query = self.query(messages)
                if "timeout" in query:
                    raise TimeoutError("Synthetic Provider timeout")
                if not self.agent and "search" in query and not catalog(messages):
                    yield LLMStreamEvent("tool_call", tool_call=ProviderToolCall("web", "search_web", '{"query":"synthetic search"}'))
                else:
                    text = self.answer(messages)
                    if "invalid-citation" in query:
                        text += " 【999】"
                    for index in range(0, len(text), 4):
                        time.sleep(0.35 if "slow" in query else 0.01)
                        yield LLMStreamEvent("message", content=text[index:index + 4])
                    if "disconnect" in query:
                        raise RuntimeError("Synthetic Provider disconnect")
                yield LLMStreamEvent("usage", usage=LLMUsage(5, 1, 6))
                yield LLMStreamEvent("done", provider="offline", model="integration-mock")

        def web(query):
            stats["web_calls"] += 1
            return {"results": [{"title": "Synthetic web evidence", "url": "https://example.test/integration",
                                 "snippet": "Synthetic evidence, not live search"}]}

        for module in ("app.api.routes.chat", "app.api.routes.chat_stream", "app.agents.orchestrator"):
            stack.enter_context(patch(module + ".create_llm_provider", side_effect=lambda *args: IntegrationProvider()))
        entries = [ModelEntry("deepseek", "offline", "integration-mock", True, True)]
        stack.enter_context(patch("app.providers.registry.models", return_value=entries))
        stack.enter_context(patch("app.api.routes.models.models", return_value=entries))
        stack.enter_context(patch("app.rag.service.create_embedding_provider", return_value=OfflineEmbeddings()))
        stack.enter_context(patch("app.tools.registry.web_search", side_effect=web))
        from app.main import create_app
        app = create_app()
        database.list_workspaces()
        database.update_workspace(database.DEFAULT_WORKSPACE_ID, {"name": "Offline integration acceptance", "tool_settings": {"web_search": True}})

        @app.get("/__acceptance/state")
        def state():
            return {"marker": "paw-integration-offline-v1", "database": "temporary-sqlite", **stats,
                    "blocked_network_attempts": len(attempts), "memory_enabled": settings.memory_enabled}

        @app.post("/__acceptance/control")
        def control(body: dict):
            # Test-only controls, never included by the production app.
            if "memory_enabled" in body:
                settings.memory_enabled = bool(body["memory_enabled"])
            if "token_budget" in body:
                settings.agent_token_budget = int(body["token_budget"])
            return state()

        print("OFFLINE INTEGRATION: disposable SQLite/Chroma; no real credentials or providers; port 18800", flush=True)
        try:
            uvicorn.run(app, host="127.0.0.1", port=18800, log_level="warning")
        finally:
            from chromadb.api.client import SharedSystemClient
            for system in list(SharedSystemClient._identifier_to_system.values()):
                system.stop()
            SharedSystemClient.clear_system_cache()
            gc.collect()
            os.chdir(original_cwd)


if __name__ == "__main__":
    main()
