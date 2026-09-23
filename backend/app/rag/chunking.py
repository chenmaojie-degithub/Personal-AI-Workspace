from __future__ import annotations

import re
from typing import Any


def _is_markdown(text: str) -> bool:
    """
    Simple heuristic to detect if text is Markdown.
    """
    markdown_patterns = [
        r"^#{1,6}\s+",  # Headers
        r"```",  # Code blocks
        r"^\s*[-*+]\s+",  # Unordered lists
        r"^\s*\d+\.\s+",  # Ordered lists
        r"\[.*?\]\(.*?\)",  # Links
        r"\*\*.*?\*\*",  # Bold
        r"_.*?_",  # Italic
    ]
    # Check first 2000 characters for markdown patterns
    sample = text[:2000]
    return any(re.search(pattern, sample, re.MULTILINE) for pattern in markdown_patterns)


def _find_sentence_boundaries(text: str, start_pos: int, end_pos: int) -> list[int]:
    """
    Find sentence boundaries (., !, ? followed by whitespace) within a range.
    Returns list of positions where sentences end.
    """
    # Regex to find sentence endings: . ! ? followed by whitespace or end of string
    pattern = r"[.!?]+(?:\s+|$)"
    boundaries = []
    for match in re.finditer(pattern, text[start_pos:end_pos]):
        boundaries.append(start_pos + match.end())
    return boundaries


def _find_markdown_boundaries(text: str, start_pos: int, end_pos: int) -> list[int]:
    """
    Find Markdown structural boundaries (headers, code blocks, paragraph breaks).
    Returns list of positions where structural breaks occur.
    """
    boundaries = []
    sample = text[start_pos:end_pos]

    # Find headers (#, ##, ###, etc.)
    for match in re.finditer(r"^#{1,6}\s+", sample, re.MULTILINE):
        boundaries.append(start_pos + match.start())

    # Find code block boundaries (```)
    for match in re.finditer(r"```", sample):
        boundaries.append(start_pos + match.start())

    # Find paragraph breaks (double newline)
    for match in re.finditer(r"\n\n+", sample):
        boundaries.append(start_pos + match.end())

    return sorted(set(boundaries))


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[str]:
    """
    Improved text chunking strategy that respects sentence boundaries and Markdown structure.

    Features:
      - Respects sentence boundaries (., !, ?)
      - Preserves Markdown structure (headers, code blocks, paragraphs)
      - Handles overlap at natural boundaries
      - Falls back to simple chunking for very small chunks or when boundaries not found
    """
    if not text:
        return []

    # Fallback to simple chunking for very small chunks
    if chunk_size < 200:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start = end - chunk_overlap if end < len(text) else end
        return chunks

    is_markdown = _is_markdown(text)
    chunks: list[str] = []
    start = 0

    while start < len(text):
        target_end = min(start + chunk_size, len(text))

        # If we're at the end of text, just take the rest
        if target_end >= len(text):
            if start < len(text):
                chunks.append(text[start:])
            break

        # Find natural boundaries
        boundaries = []

        # Always look for sentence boundaries
        sentence_boundaries = _find_sentence_boundaries(text, start, target_end + chunk_overlap)
        boundaries.extend(sentence_boundaries)

        # If Markdown, also look for structural boundaries
        if is_markdown:
            markdown_boundaries = _find_markdown_boundaries(text, start, target_end + chunk_overlap)
            boundaries.extend(markdown_boundaries)

        # Also consider paragraph breaks
        para_match = re.search(r"\n\n+", text[start:target_end + chunk_overlap])
        if para_match:
            boundaries.append(start + para_match.end())

        # Remove duplicates and sort
        boundaries = sorted(set(boundaries))

        # Find the best boundary near target_end
        best_end = target_end
        for boundary in boundaries:
            # Prefer boundaries that are close to target_end but not too far
            if start < boundary <= target_end + chunk_overlap:
                if abs(boundary - target_end) < abs(best_end - target_end):
                    best_end = boundary
            elif boundary > target_end + chunk_overlap:
                break

        # Ensure we don't go backwards
        if best_end <= start:
            best_end = target_end

        # Extract chunk
        chunk = text[start:best_end].strip()
        if chunk:
            chunks.append(chunk)

        # Move start position for next chunk (with overlap)
        # Try to start overlap at a sentence boundary
        overlap_start = max(start, best_end - chunk_overlap)
        overlap_boundaries = [b for b in boundaries if overlap_start <= b < best_end]

        if overlap_boundaries:
            # Start overlap at the last sentence boundary before best_end
            start = overlap_boundaries[-1]
        else:
            # Fallback: simple overlap
            start = max(start + 1, best_end - chunk_overlap)

        # Safety check to prevent infinite loop
        if start >= len(text):
            break
        if start == best_end and best_end < len(text):
            # Force progress if we're stuck
            start = best_end

    return chunks


def chunk_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Chunk a list of documents (each with 'content' field).

    Returns list of chunk dicts with metadata preserved.
    """
    all_chunks: list[dict[str, Any]] = []

    for doc in documents:
        content = doc.get("content", "")
        if not content:
            continue

        doc_chunks = chunk_text(content)
        # NOTE: don't shadow the chunk_text() function name (Python scoping rules)
        for idx, chunk in enumerate(doc_chunks):
            chunk = {
                "content": chunk,
                "document_id": doc.get("document_id"),
                "filename": doc.get("filename"),
                "chunk_index": idx,
                "metadata": doc.get("metadata", {}),
            }
            all_chunks.append(chunk)

    return all_chunks
