"""V1.1 lifecycle checks: temporary stores only, never production databases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Barrier
from types import SimpleNamespace

import pytest

from app.api.routes.chat import orchestrate_request
from app.core.config import settings
from app.models.chat import ChatRequest
from app.services.memory import MemoryConflict, MemoryService, memory_messages
from app.tests.test_memory import memory_env, MemoryProvider


def test_workspace_delete_retains_memory_and_preview_exposes_only_counts(memory_env, monkeypatch):
    client, a, b, service = memory_env
    row = service.create(a, "language", "synthetic private value", confirmed=True)
    service.create(b, "language", "other private value", confirmed=True)
    monkeypatch.setattr("app.api.routes.workspaces.RAGService", lambda: SimpleNamespace(
        workspace_snapshot=lambda _: {"ids": []}, delete_workspace_chunks=lambda _: None,
        restore_workspace_chunks=lambda _: None))
    assert client.delete(f"/workspaces/{a}").status_code == 200
    assert service.get(a, row["id"]) == row
    assert client.get(f"/workspaces/{a}/memories").status_code == 404
    preview = client.get("/memory/maintenance/orphans")
    assert preview.status_code == 200
    assert preview.json() == {"orphans": [{"workspace_id": a, "count": 1}], "record_count": 1,
                              "action": "retain", "atomic_snapshot": False}
    assert "private value" not in preview.text and row["id"] not in preview.text
    assert service.get(a, row["id"]) == row  # Inspection cannot clear anything.
    response = orchestrate_request(ChatRequest(workspace_id=a, messages=[{"role": "user", "content": "language"}]))
    assert response.error == "Workspace not found"


@pytest.mark.parametrize("inventory", [[], RuntimeError("synthetic inventory failure")])
def test_failed_inventory_never_classifies_every_memory_as_orphan(memory_env, monkeypatch, inventory):
    client, workspace, _, service = memory_env
    row = service.create(workspace, "language", "中文", confirmed=True)
    def get_inventory():
        if isinstance(inventory, Exception):
            raise inventory
        return inventory
    monkeypatch.setattr("app.api.routes.memories.list_workspaces", get_inventory)
    result = client.get("/memory/maintenance/orphans")
    assert result.status_code == 503 and "orphans" not in result.json()
    assert service.get(workspace, row["id"]) == row


def test_disabled_lifecycle_does_not_read_business_inventory(memory_env, monkeypatch):
    client, _, _, _ = memory_env
    monkeypatch.setattr(settings, "memory_enabled", False)
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError("Inventory must not be opened")
    monkeypatch.setattr("app.api.routes.memories.list_workspaces", forbidden)
    assert client.get("/memory/maintenance/orphans").status_code == 503
    assert calls == []


@pytest.mark.parametrize("operation", ["create", "update"])
def test_concurrent_duplicate_or_stale_write(memory_env, operation):
    _, workspace, _, service = memory_env
    row = service.create(workspace, "language", "initial", confirmed=True) if operation == "update" else None
    barrier = Barrier(2)
    def write(index):
        barrier.wait(timeout=5)
        try:
            if row:
                return MemoryService().update(workspace, row["id"], f"value {index}", expected_version=1, confirmed=True)
            return MemoryService().create(workspace, "language", "中文", confirmed=True)
        except MemoryConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, [1, 2]))
    if row:
        assert results.count("conflict") == 1
        assert service.get(workspace, row["id"])["version"] == 2
    else:
        assert results[0]["id"] == results[1]["id"]
        assert len(service.list(workspace)) == 1


def test_old_snapshot_and_restored_backup_can_retain_deleted_memory(memory_env, tmp_path):
    _, workspace, _, service = memory_env
    row = service.create(workspace, "language", "中文", confirmed=True)
    old_snapshot = memory_messages(workspace, "language")
    backup = tmp_path / "export.sqlite3"
    with closing(sqlite3.connect(service.path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    assert service.delete(workspace, row["id"], expected_version=1)
    assert memory_messages(workspace, "language") == []
    assert "中文" in old_snapshot[1]["content"]  # Existing Run snapshot is not retroactively erased.
    restored = tmp_path / "independent-restored.sqlite3"
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert target.execute("SELECT id FROM memories").fetchall() == [(row["id"],)]
    assert service.get(workspace, row["id"]) is None  # Never overwrite the active store.


def test_memory_disabled_preserves_plain_chat(memory_env, monkeypatch):
    _, workspace, _, service = memory_env
    service.create(workspace, "language", "中文", confirmed=True)
    monkeypatch.setattr(settings, "memory_enabled", False)
    provider = MemoryProvider(agent=False)
    monkeypatch.setattr("app.api.routes.chat.create_llm_provider", lambda _: provider)
    result = orchestrate_request(ChatRequest(workspace_id=workspace, messages=[{"role": "user", "content": "What is my language?"}]))
    assert not result.error and result.assistant_message.content == "answer"
    assert all("WORKSPACE_MEMORY" not in item["content"] for item in provider.received[0])
