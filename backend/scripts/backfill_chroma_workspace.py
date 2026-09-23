"""Idempotently tag old session-only Chroma chunks as Default Workspace.

Run from backend with: .venv/Scripts/python -m scripts.backfill_chroma_workspace
No embedding call, vector deletion, or file rewrite occurs.
"""

from app.core.database import DEFAULT_WORKSPACE_ID
from app.rag.service import RAGService


if __name__ == "__main__":
    count = RAGService().backfill_legacy_workspace_metadata(DEFAULT_WORKSPACE_ID)
    print(f"Legacy chunks tagged for Default Workspace: {count}")
