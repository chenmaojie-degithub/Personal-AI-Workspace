from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from app.core.config import settings

DOCUMENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DATA_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
ALLOWED_TYPES = {**DOCUMENT_TYPES, **DATA_TYPES}


class DocumentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedFile:
    content_type: str
    byte_size: int
    content_sha256: str
    analysis_ready: bool


def size_limit(filename: str) -> int:
    suffix = Path(filename).suffix.lower()
    if suffix in DOCUMENT_TYPES:
        return settings.document_max_bytes
    if suffix in DATA_TYPES:
        return settings.data_file_max_bytes
    raise DocumentValidationError(f"Unsupported file type: {suffix or '(none)'}")


def validate_file(path: Path, expected_sha256: str | None = None) -> ValidatedFile:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise DocumentValidationError(f"Unsupported file type: {suffix or '(none)'}")
    byte_size = path.stat().st_size
    if byte_size <= 0:
        raise DocumentValidationError("File is empty")
    if byte_size > size_limit(path.name):
        raise DocumentValidationError("File exceeds the configured size limit")
    digest_builder = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise DocumentValidationError("File checksum changed while uploading")

    if suffix == ".pdf":
        with path.open("rb") as stream:
            header = stream.read(5)
        if header != b"%PDF-":
            raise DocumentValidationError("File content is not a valid PDF")
    elif suffix in {".docx", ".xlsx"}:
        required = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
        try:
            with ZipFile(path) as archive:
                if required not in archive.namelist():
                    raise DocumentValidationError(f"File content is not a valid {suffix[1:].upper()} document")
        except BadZipFile as exc:
            raise DocumentValidationError(f"File content is not a valid {suffix[1:].upper()} document") from exc
    elif suffix in {".txt", ".md", ".markdown", ".csv"}:
        try:
            with path.open("r", encoding="utf-8") as stream:
                while stream.read(1024 * 1024):
                    pass
        except UnicodeDecodeError as exc:
            raise DocumentValidationError("Text files must use UTF-8 encoding") from exc

    return ValidatedFile(ALLOWED_TYPES[suffix], byte_size, digest, suffix in DATA_TYPES)
