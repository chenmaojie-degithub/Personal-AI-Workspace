from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.database import create_project_folder, list_project_tree, move_project_item, rename_project_folder
from app.models.project import ProjectFolder, ProjectFolderCreate, ProjectFolderPatch, ProjectMove, ProjectTree

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/tree", response_model=ProjectTree)
def project_tree(workspace_id: str) -> dict:
    try:
        return list_project_tree(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/folders", response_model=ProjectFolder, status_code=201)
def add_folder(payload: ProjectFolderCreate) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty")
    try:
        return create_project_folder(payload.workspace_id, name, payload.parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/folders/{folder_id}", response_model=ProjectFolder)
def update_folder(folder_id: str, payload: ProjectFolderPatch, workspace_id: str) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty")
    folder = rename_project_folder(folder_id, workspace_id, name)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found in workspace")
    return folder


@router.post("/move", response_model=ProjectTree)
def move_item(payload: ProjectMove) -> dict:
    try:
        return move_project_item(
            payload.workspace_id, payload.item_type, payload.item_id, payload.parent_id, payload.position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
