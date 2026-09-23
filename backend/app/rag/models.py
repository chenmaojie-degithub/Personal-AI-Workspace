from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RAGChunk:
    content: str
    filename: str
    document_id: str
    chunk_index: int
    distance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
