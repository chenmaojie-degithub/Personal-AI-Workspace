from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.database import delete_session, get_usage_summary, list_messages, list_sessions, rename_session, session_workspace_id
from app.models.chat import SessionTitlePatch, StoredMessage, StoredSession, UsageSummary

router = APIRouter(tags=["history"])


@router.get("/sessions", response_model=list[StoredSession])
def sessions(workspace_id: str | None = None) -> list[dict]:
    return list_sessions(workspace_id)


@router.patch("/sessions/{session_id}", response_model=StoredSession)
def update_session_title(session_id: str, payload: SessionTitlePatch, workspace_id: str | None = None) -> dict:
    title = payload.title.strip()
    if not title or len(title) > 100:
        raise HTTPException(status_code=422, detail="Title must contain 1–100 characters after trimming")
    session = rename_session(session_id, workspace_id, title)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found in workspace")
    return session


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str, workspace_id: str | None = None) -> dict[str, str | int]:
    if workspace_id and session_workspace_id(session_id) != workspace_id:
        raise HTTPException(status_code=404, detail="Session not found in workspace")
    return {"session_id": session_id, **delete_session(session_id)}


@router.get("/sessions/{session_id}/messages", response_model=list[StoredMessage])
def session_messages(session_id: str, workspace_id: str | None = None) -> list[dict]:
    return list_messages(session_id, workspace_id)


@router.get("/usage/summary", response_model=UsageSummary)
def usage_summary() -> dict[str, int]:
    return get_usage_summary()
