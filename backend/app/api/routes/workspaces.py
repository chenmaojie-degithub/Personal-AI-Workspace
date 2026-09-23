from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.database import (
    DEFAULT_WORKSPACE_ID, create_workspace, delete_workspace_business,
    get_workspace, list_workspaces, update_workspace,
)
from app.models.workspace import Workspace, WorkspaceCreate, WorkspacePatch
from app.providers.registry import resolve_model
from app.rag.service import RAGService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _validate_model(model_id: str | None) -> None:
    if model_id is not None:
        try:
            resolve_model(model_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[Workspace])
def workspaces() -> list[dict]:
    return list_workspaces()


@router.post("", response_model=Workspace, status_code=201)
def add_workspace(body: WorkspaceCreate) -> dict:
    _validate_model(body.default_model_id)
    return create_workspace(**body.model_dump(exclude={"tool_settings"}), tool_settings=body.tool_settings.model_dump())


@router.get("/{workspace_id}", response_model=Workspace)
def workspace(workspace_id: str) -> dict:
    item = get_workspace(workspace_id)
    if not item:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return item


@router.patch("/{workspace_id}", response_model=Workspace)
def edit_workspace(workspace_id: str, body: WorkspacePatch) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("name", "description", "system_prompt") if field in changes):
        raise HTTPException(status_code=422, detail="Workspace text fields cannot be null")
    if "default_model_id" in changes:
        _validate_model(changes["default_model_id"])
    if changes.get("tool_settings") is None and "tool_settings" in changes:
        raise HTTPException(status_code=422, detail="tool_settings cannot be null")
    item = update_workspace(workspace_id, changes)
    if not item:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return item


@router.delete("/{workspace_id}")
def remove_workspace(workspace_id: str) -> dict:
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise HTTPException(status_code=403, detail="Default Workspace cannot be deleted")
    if not get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")

    root = (Path(settings.storage_dir).resolve() / "workspaces").resolve()
    target = (root / workspace_id).resolve()
    if target.parent != root:
        raise HTTPException(status_code=400, detail="Invalid workspace_id")
    tombstone = root / f".{uuid4()}.deleting"
    rag = RAGService()
    snapshot = rag.workspace_snapshot(workspace_id)
    staged = target.is_dir()
    try:
        if staged:
            target.replace(tombstone)
        rag.delete_workspace_chunks(workspace_id)
        result = delete_workspace_business(workspace_id)
    except Exception as exc:
        try:
            rag.restore_workspace_chunks(snapshot)
            if staged and tombstone.exists():
                tombstone.replace(target)
        except Exception as restore_exc:
            raise HTTPException(status_code=500, detail=f"Workspace deletion failed and compensation needs attention: {restore_exc}") from exc
        raise HTTPException(status_code=500, detail=f"Workspace deletion rolled back: {exc}") from exc
    if staged:
        try:
            shutil.rmtree(tombstone)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Workspace removed but staged file cleanup needs attention: {exc}") from exc
    shutil.rmtree(Path(settings.storage_dir).resolve() / "analysis_charts" / workspace_id, ignore_errors=True)
    return {"id": workspace_id, **result, "deleted_chunks": len(snapshot["ids"])}
