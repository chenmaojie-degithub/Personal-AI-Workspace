"""Explicit user operations only: no Agent tool can write long-term memory."""
from contextlib import contextmanager
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.database import get_workspace
from app.services.memory import MemoryConflict, MemoryService, MemoryUnavailable

router = APIRouter(prefix="/workspaces/{workspace_id}/memories", tags=["memory"])


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=1000)
    confirmed: bool = Field(strict=True)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1, strict=True)
    confirmed: bool = Field(strict=True)


@contextmanager
def scoped_service(workspace_id: str):
    try:
        service = MemoryService()  # Disabled path must not connect to any database.
        if not get_workspace(workspace_id):
            raise HTTPException(status_code=404, detail="Workspace not found")
        yield service
    except MemoryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (MemoryUnavailable, sqlite3.Error, OSError) as exc:
        raise HTTPException(status_code=503, detail="Memory unavailable; requires enabled isolated SQLite storage") from exc


@router.post("")
def create_memory(workspace_id: str, body: MemoryCreate) -> dict:
    with scoped_service(workspace_id) as service:
        return service.create(workspace_id, **body.model_dump())


@router.get("")
def list_memories(workspace_id: str, q: str = Query(default="", max_length=500),
                  limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> list[dict]:
    with scoped_service(workspace_id) as service:
        return service.list(workspace_id, q, limit=limit, offset=offset)


@router.get("/{memory_id}")
def get_memory(workspace_id: str, memory_id: str) -> dict:
    with scoped_service(workspace_id) as service:
        row = service.get(workspace_id, memory_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return row


@router.patch("/{memory_id}")
def update_memory(workspace_id: str, memory_id: str, body: MemoryUpdate) -> dict:
    with scoped_service(workspace_id) as service:
        row = service.update(workspace_id, memory_id, **body.model_dump())
        if row is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        return row


@router.delete("/{memory_id}", status_code=204)
def delete_memory(workspace_id: str, memory_id: str, expected_version: int = Query(ge=1)) -> Response:
    with scoped_service(workspace_id) as service:
        if not service.delete(workspace_id, memory_id, expected_version=expected_version):
            raise HTTPException(status_code=404, detail="Memory not found")
        return Response(status_code=204)
