from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.chat import ChatSettings


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    system_prompt: str = Field(default="", max_length=12000)
    default_model_id: str | None = None
    tool_settings: ChatSettings = Field(default_factory=ChatSettings)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str | None = Field(default=None, max_length=12000)
    default_model_id: str | None = None
    tool_settings: ChatSettings | None = None


class Workspace(WorkspaceCreate):
    id: str
    is_default: bool
    created_at: str
    updated_at: str
