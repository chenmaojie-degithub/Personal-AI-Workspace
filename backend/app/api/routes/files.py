from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import settings
from app.core.database import DEFAULT_WORKSPACE_ID, get_workspace
from app.rag.service import RAGService

router = APIRouter(prefix="/files", tags=["files"])
_STATUS_FILENAME = ".rag_index_status.json"


def _session_dir(session_id: str) -> Path:
    if not session_id or session_id in {".", ".."} or "/" in session_id or "\\" in session_id:
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return Path(settings.storage_dir).resolve() / session_id


def _workspace_dir(workspace_id: str) -> Path:
    if not get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    root = (Path(settings.storage_dir).resolve() / "workspaces").resolve()
    target = (root / workspace_id).resolve()
    if target.parent != root:
        raise HTTPException(status_code=400, detail="Invalid workspace_id")
    return target


def _load_status(session_dir: Path) -> dict[str, dict]:
    path = session_dir / _STATUS_FILENAME
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_status(session_dir: Path, status: dict[str, dict]) -> None:
    path = session_dir / _STATUS_FILENAME
    temporary = session_dir / f"{_STATUS_FILENAME}.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    session_id: str | None = Form(default=None),
    workspace_id: str | None = Form(default=None),
) -> dict:
    """
    Store uploaded files and ingest supported knowledge files into RAG.

    CSV and XLSX files remain Workspace data-analysis inputs and are not embedded.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    sid = session_id or str(uuid4())

    session_dir = _workspace_dir(workspace_id) if workspace_id else _session_dir(sid)
    session_dir.mkdir(parents=True, exist_ok=True)

    if workspace_id:
        names = [os.path.basename(item.filename or "") for item in files]
        if len(names) != len(set(names)) or any((session_dir / name).exists() for name in names):
            raise HTTPException(status_code=409, detail="A file with this name already exists in the workspace")

    saved: list[dict] = []
    saved_paths: list[Path] = []
    for f in files:
        filename = os.path.basename(f.filename or "")
        if not filename:
            raise HTTPException(status_code=400, detail="File missing filename")

        # Minimal validation (expand later)
        if len(filename) > 200:
            raise HTTPException(status_code=400, detail=f"Filename too long: {filename}")

        target = session_dir / filename
        content = await f.read()
        target.write_bytes(content)
        saved_paths.append(target)

        saved.append(
            {
                "file_id": filename,
                "filename": filename,
                "bytes": len(content),
                "content_type": f.content_type,
                "analysis_ready": target.suffix.lower() in {".csv", ".xlsx"},
            }
        )

    ingest_summary: dict | None = None
    ingest_error: str | None = None
    try:
        rag_paths = [path for path in saved_paths if path.suffix.lower() not in {".csv", ".xlsx"}]
        if rag_paths:
            rag = RAGService()
            ingest_summary = (
                rag.ingest_files(session_id=sid, file_paths=rag_paths, workspace_id=workspace_id)
                if workspace_id else rag.ingest_files(session_id=sid, file_paths=rag_paths)
            )
    except Exception as e:
        ingest_error = f"{type(e).__name__}: {e}"

    status = _load_status(session_dir)
    for item in saved:
        status[item["filename"]] = {"ingest_error": ingest_error}
        item["status"] = "failed" if ingest_error else "indexed"
    _save_status(session_dir, status)

    return {
        "session_id": sid,
        "workspace_id": workspace_id,
        "stored": saved,
        "ingest": ingest_summary,
        "ingest_error": ingest_error,
    }


@router.get("")
def list_files(session_id: str | None = None, workspace_id: str | None = None) -> dict:
    """
    Skeleton list endpoint for session files.
    """
    if not workspace_id and not session_id:
        raise HTTPException(status_code=422, detail="session_id or workspace_id is required")
    session_dir = _workspace_dir(workspace_id) if workspace_id else _session_dir(session_id)
    rag = RAGService()

    def describe(directory: Path, sid: str, wid: str | None) -> list[dict]:
        if not directory.exists():
            return []
        chunk_counts = rag.file_chunk_counts(sid, workspace_id=wid) if wid else rag.file_chunk_counts(sid)
        status = _load_status(directory)
        return [
        {
            "filename": p.name,
            "session_id": None if wid else sid,
            "bytes": p.stat().st_size,
            "status": (
                "indexed"
                if chunk_counts.get(p.name, 0) > 0
                else "failed"
                if status.get(p.name, {}).get("ingest_error")
                else "not_indexed"
            ),
            "chunk_count": chunk_counts.get(p.name, 0),
            "ingest_error": status.get(p.name, {}).get("ingest_error"),
        }
        for p in directory.iterdir()
        if p.is_file() and not p.name.startswith(".")
        ]

    files = describe(session_dir, session_id or "", workspace_id)
    if workspace_id == DEFAULT_WORKSPACE_ID:
        root = Path(settings.storage_dir).resolve()
        for legacy_dir in root.iterdir() if root.exists() else []:
            if legacy_dir.is_dir() and legacy_dir.name != "workspaces":
                files.extend(describe(legacy_dir, legacy_dir.name, None))
    return {"session_id": session_id, "workspace_id": workspace_id, "files": files}


@router.delete("/{filename}")
def delete_file(filename: str, session_id: str | None = None, workspace_id: str | None = None) -> dict:
    safe_filename = os.path.basename(filename)
    if not safe_filename or safe_filename != filename or safe_filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not workspace_id and not session_id:
        raise HTTPException(status_code=422, detail="session_id or workspace_id is required")
    session_dir = _workspace_dir(workspace_id) if workspace_id else _session_dir(session_id)
    target = session_dir / safe_filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    tombstone = session_dir / f".{uuid4()}.deleting"
    target.replace(tombstone)
    try:
        deleted_chunks = (
            RAGService().delete_file(session_id or "", safe_filename, workspace_id=workspace_id)
            if workspace_id else RAGService().delete_file(session_id, safe_filename)
        )
    except Exception as exc:
        tombstone.replace(target)
        raise HTTPException(
            status_code=500,
            detail=f"Chroma delete failed; storage file was restored: {type(exc).__name__}: {exc}",
        ) from exc

    try:
        tombstone.unlink()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Vector data was deleted but storage cleanup failed: {type(exc).__name__}: {exc}",
        ) from exc

    status = _load_status(session_dir)
    status.pop(safe_filename, None)
    _save_status(session_dir, status)
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "filename": safe_filename,
        "deleted_chunks": deleted_chunks,
    }
