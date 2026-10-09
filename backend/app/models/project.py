from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.chat import StoredSession


class ProjectFolder(BaseModel):
    id: str
    workspace_id: str
    parent_id: str | None = None
    name: str
    position: int
    created_at: str
    updated_at: str


class ProjectTree(BaseModel):
    folders: list[ProjectFolder]
    sessions: list[StoredSession]


class ProjectFolderCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=100)
    parent_id: str | None = None


class ProjectFolderPatch(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectMove(BaseModel):
    workspace_id: str
    item_type: Literal["folder", "session"]
    item_id: str
    parent_id: str | None = None
    position: int = Field(ge=0)
