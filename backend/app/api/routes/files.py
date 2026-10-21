from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.config import settings
from app.core.database import (
    DEFAULT_WORKSPACE_ID,
    create_document_record,
    delete_document_record,
    find_document_by_hash,
    find_document_by_name,
    get_workspace,
    list_document_records,
    update_document_record,
)
from app.rag.service import RAGService
from app.services.documents import DocumentValidationError, size_limit, validate_file

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
    if len(files) > settings.upload_max_files:
        raise HTTPException(status_code=400, detail=f"A maximum of {settings.upload_max_files} files can be uploaded at once")

    sid = session_id or str(uuid4())

    session_dir = _workspace_dir(workspace_id) if workspace_id else _session_dir(sid)
    session_dir.mkdir(parents=True, exist_ok=True)

    names = [os.path.basename(item.filename or "") for item in files]
    if any(not name or name != (item.filename or "") or name.startswith(".") for name, item in zip(names, files)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if any(len(name) > 200 for name in names):
        raise HTTPException(status_code=400, detail="Filename exceeds 200 characters")
    if len(names) != len(set(names)) or any((session_dir / name).exists() for name in names):
        raise HTTPException(status_code=409, detail="A file with this name already exists")

    prepared: list[dict] = []
    created: list[dict] = []
    temporary_paths: list[Path] = []
    try:
        for upload, filename in zip(files, names):
            limit = size_limit(filename)
            suffix = Path(filename).suffix.lower()
            temporary = session_dir / f".{uuid4().hex}.upload{suffix}"
            temporary_paths.append(temporary)
            digest = hashlib.sha256()
            byte_size = 0
            with temporary.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    byte_size += len(chunk)
                    if byte_size > limit:
                        raise DocumentValidationError(f"{filename} exceeds the configured size limit")
                    digest.update(chunk)
                    output.write(chunk)
            validated = validate_file(temporary, digest.hexdigest())
            if find_document_by_hash(validated.content_sha256, workspace_id=workspace_id, session_id=None if workspace_id else sid):
                raise HTTPException(status_code=409, detail=f"Duplicate document content: {filename}")
            if any(item["validated"].content_sha256 == validated.content_sha256 for item in prepared):
                raise HTTPException(status_code=409, detail=f"Duplicate document content in this upload: {filename}")
            prepared.append({"upload": upload, "filename": filename, "temporary": temporary, "validated": validated})

        for item in prepared:
            target = session_dir / item["filename"]
            item["temporary"].replace(target)
            item["path"] = target
            validated = item["validated"]
            record = create_document_record(
                filename=item["filename"], content_type=validated.content_type,
                byte_size=validated.byte_size, content_sha256=validated.content_sha256,
                workspace_id=workspace_id, session_id=sid,
            )
            item["record"] = record
            created.append(item)
    except HTTPException:
        for item in created:
            item["path"].unlink(missing_ok=True)
            delete_document_record(item["record"]["id"])
        raise
    except (DocumentValidationError, OSError, ValueError) as exc:
        for item in created:
            item["path"].unlink(missing_ok=True)
            delete_document_record(item["record"]["id"])
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        for item in created:
            item["path"].unlink(missing_ok=True)
            delete_document_record(item["record"]["id"])
        raise
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)

    saved: list[dict] = []
    errors: list[str] = []
    rag = RAGService()
    for item in created:
        validated = item["validated"]
        record = item["record"]
        status = "ready" if validated.analysis_ready else "parsing"
        chunks = 0
        error: str | None = None
        try:
            if validated.analysis_ready:
                update_document_record(record["id"], status="ready")
            else:
                update_document_record(record["id"], status="parsing")
                summary = rag.ingest_files(
                    session_id=sid, file_paths=[item["path"]], workspace_id=workspace_id,
                    document_metadata={item["filename"]: {
                        "document_id": record["id"], "content_type": validated.content_type,
                        "content_sha256": validated.content_sha256, "schema_version": 1,
                    }},
                )
                chunks = int(summary.get("stored", 0))
                status = "indexed"
                update_document_record(record["id"], status=status, chunk_count=chunks)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            errors.append(f"{item['filename']}: {error}")
            status = "failed"
            update_document_record(record["id"], status=status, error=error)
        saved.append({
            "file_id": record["id"], "document_id": record["id"], "filename": item["filename"],
            "bytes": validated.byte_size, "content_type": validated.content_type,
            "analysis_ready": validated.analysis_ready, "status": status,
            "chunk_count": chunks, "ingest_error": error,
        })

    ingest_error = "; ".join(errors) or None
    ingest_summary = {"stored": sum(item["chunk_count"] for item in saved)}

    status = _load_status(session_dir)
    for item in saved:
        status[item["filename"]] = {"ingest_error": item["ingest_error"]}
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
        records = list_document_records(workspace_id=wid, session_id=None if wid else sid)
        by_name = {item["filename"]: item for item in records}
        return [
        {
            "document_id": by_name.get(p.name, {}).get("id"),
            "filename": p.name,
            "session_id": None if wid else sid,
            "bytes": p.stat().st_size,
            "content_type": by_name.get(p.name, {}).get("content_type"),
            "content_sha256": by_name.get(p.name, {}).get("content_sha256"),
            "created_at": by_name.get(p.name, {}).get("created_at"),
            "status": by_name.get(p.name, {}).get("status") or (
                "indexed"
                if chunk_counts.get(p.name, 0) > 0
                else "failed"
                if status.get(p.name, {}).get("ingest_error")
                else "not_indexed"
            ),
            "chunk_count": by_name.get(p.name, {}).get("chunk_count", chunk_counts.get(p.name, 0)),
            "ingest_error": by_name.get(p.name, {}).get("error") or status.get(p.name, {}).get("ingest_error"),
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
    record = find_document_by_name(safe_filename, workspace_id=workspace_id, session_id=None if workspace_id else session_id)
    try:
        deleted_chunks = (
            RAGService().delete_file(session_id or "", safe_filename, workspace_id=workspace_id, document_id=record["id"] if record else None)
            if workspace_id else RAGService().delete_file(session_id, safe_filename, document_id=record["id"] if record else None)
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
    if record:
        delete_document_record(record["id"])
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "filename": safe_filename,
        "deleted_chunks": deleted_chunks,
    }
