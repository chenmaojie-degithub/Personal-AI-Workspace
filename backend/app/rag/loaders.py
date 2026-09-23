from __future__ import annotations

from pathlib import Path
from typing import Any
from unicodedata import normalize

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None


def load_text_file(file_path: Path) -> str:
    """
    Load plain text file.

    TODO: Add encoding detection, error handling.
    """
    return file_path.read_text(encoding="utf-8")


_PDF_RADICAL_REPLACEMENTS = str.maketrans({"⺠": "民", "⻘": "青", "⻚": "页"})


def _normalize_pdf_text(text: str) -> str:
    return normalize("NFKC", text).translate(_PDF_RADICAL_REPLACEMENTS)


def load_pdf_file(file_path: Path) -> str:
    """
    Load PDF file and extract text content.
    """
    if PdfReader is None:
        return f"[PDF support not available: pypdf library not installed]"

    try:
        reader = PdfReader(file_path)
        pages_text = []
        for page in reader.pages:
            text = page.extract_text(extraction_mode="layout")
            if text:
                pages_text.append(_normalize_pdf_text(text))
        return "\n\n".join(pages_text)
    except Exception as e:
        return f"[Error reading PDF {file_path.name}: {e}]"


def load_docx_file(file_path: Path) -> str:
    """
    Load DOCX file and extract text content.
    """
    if Document is None:
        return f"[DOCX support not available: python-docx library not installed]"

    try:
        doc = Document(file_path)
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
        return "\n\n".join(paragraphs)
    except Exception as e:
        return f"[Error reading DOCX {file_path.name}: {e}]"


def _infer_content_type(file_path: Path) -> str:
    """
    Infer content type from file extension.
    """
    suffix = file_path.suffix.lower()
    content_type_map = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
    }
    return content_type_map.get(suffix, "application/octet-stream")


def load_file(file_path: Path) -> dict[str, Any]:
    """
    Load a file and extract text content.

    Supports:
      - Text files (.txt)
      - Markdown files (.md, .markdown)
      - PDF files (.pdf) - requires pypdf
      - DOCX files (.docx) - requires python-docx

    Returns dict with:
      - content: str
      - filename: str
      - content_type: str (inferred from extension)
    """
    suffix = file_path.suffix.lower()
    content_type = _infer_content_type(file_path)

    if suffix == ".txt":
        content = load_text_file(file_path)
    elif suffix in [".md", ".markdown"]:
        # Markdown files are read as text but marked with markdown content type
        try:
            content = load_text_file(file_path)
        except Exception as e:
            content = f"[Error reading Markdown {file_path.name}: {e}]"
    elif suffix == ".pdf":
        content = load_pdf_file(file_path)
    elif suffix == ".docx":
        content = load_docx_file(file_path)
    else:
        # Fallback: try as text
        try:
            content = load_text_file(file_path)
            # If successful, keep inferred content type or default to text/plain
            if content_type == "application/octet-stream":
                content_type = "text/plain"
        except Exception:
            content = f"[Unsupported file type: {suffix}. Supported formats: .txt, .md, .pdf, .docx]"

    return {
        "content": content,
        "filename": file_path.name,
        "content_type": content_type,
    }


def load_files(file_paths: list[Path]) -> list[dict[str, Any]]:
    """
    Load multiple files and return list of document dicts.
    """
    documents: list[dict[str, Any]] = []

    for fp in file_paths:
        try:
            doc = load_file(fp)
            doc["document_id"] = str(fp)  # Use path as ID for now
            documents.append(doc)
        except Exception as e:
            # Log error but continue
            documents.append(
                {
                    "content": f"[Error loading {fp.name}: {e}]",
                    "filename": fp.name,
                    "content_type": "text/plain",
                    "document_id": str(fp),
                    "error": str(e),
                }
            )

    return documents
