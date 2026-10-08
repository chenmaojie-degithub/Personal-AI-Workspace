from __future__ import annotations

from typing import Literal, Any

from pydantic import BaseModel, Field

from app.providers.base import LLMUsage


ChatRole = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class ChatSettings(BaseModel):
    web_search: bool = False
    image_generation: bool = False
    data_analysis: bool = False
    think_mode: bool = False


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, description="Client-provided or previously returned session id.")
    workspace_id: str | None = None
    model_id: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    settings: ChatSettings = Field(default_factory=ChatSettings)


class ToolCallLog(BaseModel):
    name: str
    input: dict[str, Any] | None = None
    output_preview: str | None = None
    error: str | None = None


class CitationSource(BaseModel):
    type: Literal["knowledge", "web"] = "knowledge"
    title: str | None = None
    url: str | None = None
    filename: str | None = None
    document_id: str | None = None
    chunk_index: int | None = None
    page_number: int | None = None
    section: str | None = None
    content_preview: str | None = None
    distance: float | None = None


class ChartArtifact(BaseModel):
    url: str
    title: str


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: ChatMessage | None = None
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    sources: list[CitationSource] = Field(default_factory=list)
    charts: list[ChartArtifact] = Field(default_factory=list)
    usage: LLMUsage | None = None
    error: str | None = None


class StoredMessage(BaseModel):
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class StoredSession(BaseModel):
    session_id: str
    title: str
    updated_at: str


class SessionTitlePatch(BaseModel):
    title: str


class UsageSummary(BaseModel):
    request_count: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
