from __future__ import annotations

import sqlite3
import json
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator
from uuid import uuid4

from app.core.config import settings
from app.providers.base import LLMUsage

DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
_initialized_databases: set[str] = set()
_schema_lock = Lock()

_SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id {id_type},
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
ON chat_messages (session_id, id);

CREATE TABLE IF NOT EXISTS token_usage (
    id {id_type},
    session_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL CHECK (completion_tokens >= 0),
    total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_token_usage_session
ON token_usage (session_id, id);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    default_model_id TEXT,
    tool_settings TEXT NOT NULL DEFAULT '{{}}',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_workspace
ON chat_sessions (workspace_id, updated_at);
"""


def _ensure_default_workspace(connection, placeholder: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            f"""INSERT INTO workspaces (id, name, description, system_prompt, default_model_id, tool_settings, created_at, updated_at)
            SELECT {', '.join([placeholder] * 8)} WHERE NOT EXISTS
            (SELECT 1 FROM workspaces WHERE id = {placeholder})""",
            (DEFAULT_WORKSPACE_ID, "Default Workspace", "", "", None, "{}", now, now, DEFAULT_WORKSPACE_ID),
        )
        # Old messages and usage are never copied or rewritten; only their session ids gain a parent.
        cursor.execute(
            f"""INSERT INTO chat_sessions (session_id, workspace_id, created_at, updated_at)
            SELECT old.session_id, {placeholder}, {placeholder}, {placeholder}
            FROM (SELECT session_id FROM chat_messages UNION SELECT session_id FROM token_usage) AS old
            WHERE NOT EXISTS (SELECT 1 FROM chat_sessions AS s WHERE s.session_id = old.session_id)""",
            (DEFAULT_WORKSPACE_ID, now, now),
        )


def _sqlite_path(database_url: str) -> Path:
    path = database_url.removeprefix("sqlite:///")
    if not path or path == ":memory:":
        raise RuntimeError("DATABASE_URL must point to a SQLite file")
    return Path(path).resolve()


def _initialize_schema(connection, placeholder: str, id_type: str, database_key: str) -> None:
    if database_key in _initialized_databases:
        return
    with _schema_lock:
        if database_key in _initialized_databases:
            return
        schema = _SCHEMA_TEMPLATE.format(id_type=id_type)
        if placeholder == "?":
            connection.executescript(schema)
            if "title" not in {row["name"] for row in connection.execute("PRAGMA table_info(chat_sessions)")}:
                connection.execute("ALTER TABLE chat_sessions ADD COLUMN title TEXT")
        else:
            for statement in schema.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS title TEXT")
        _ensure_default_workspace(connection, placeholder)
        connection.commit()
        _initialized_databases.add(database_key)


def _connect():
    database_url = settings.effective_database_url
    if database_url.startswith("sqlite:///"):
        database_path = _sqlite_path(database_url)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        _initialize_schema(connection, "?", "INTEGER PRIMARY KEY AUTOINCREMENT", database_url)
        return connection, "?"

    if database_url.startswith(("postgresql://", "postgres://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL DATABASE_URL requires the optional 'psycopg[binary]' package"
            ) from exc

        connect_kwargs = {"row_factory": dict_row}
        if settings.postgres_target_password:
            connect_kwargs["password"] = settings.postgres_target_password
        connection = psycopg.connect(database_url, **connect_kwargs)
        _initialize_schema(connection, "%s", "BIGSERIAL PRIMARY KEY", database_url)
        return connection, "%s"

    raise RuntimeError(
        "Unsupported DATABASE_URL scheme; use sqlite:/// or postgresql://"
    )


@contextmanager
def _connection() -> Iterator[tuple[object, str]]:
    connection, placeholder = _connect()
    try:
        yield connection, placeholder
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def save_chat_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    provider: str | None,
    model: str | None,
    usage: LLMUsage | None,
    workspace_id: str | None = None,
) -> None:
    """Save one successful user/assistant turn and its optional usage atomically."""
    created_at = datetime.now(timezone.utc).isoformat()
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            resolved_workspace = workspace_id or DEFAULT_WORKSPACE_ID
            cursor.execute(f"SELECT workspace_id FROM chat_sessions WHERE session_id = {placeholder}", (session_id,))
            existing = cursor.fetchone()
            if existing and existing["workspace_id"] != resolved_workspace:
                raise ValueError("Session belongs to a different workspace")
            if not existing:
                cursor.execute(
                    f"INSERT INTO chat_sessions (session_id, workspace_id, created_at, updated_at) VALUES ({', '.join([placeholder] * 4)})",
                    (session_id, resolved_workspace, created_at, created_at),
                )
            cursor.executemany(
                f"INSERT INTO chat_messages (session_id, role, content, created_at) VALUES ({', '.join([placeholder] * 4)})",
                [
                    (session_id, "user", user_content, created_at),
                    (session_id, "assistant", assistant_content, created_at),
                ],
            )
            if usage is not None and provider is not None and model is not None:
                cursor.execute(
                    f"""
                    INSERT INTO token_usage (
                        session_id, provider, model,
                        prompt_tokens, completion_tokens, total_tokens, created_at
                    ) VALUES ({', '.join([placeholder] * 7)})
                    """,
                    (
                        session_id,
                        provider,
                        model,
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        usage.total_tokens,
                        created_at,
                    ),
                )
            cursor.execute(
                f"UPDATE chat_sessions SET updated_at = {placeholder} WHERE session_id = {placeholder}",
                (created_at, session_id),
            )


def list_messages(session_id: str, workspace_id: str | None = None) -> list[dict]:
    with _connection() as (connection, placeholder):
        workspace_filter = (
            f" AND EXISTS (SELECT 1 FROM chat_sessions AS s WHERE s.session_id = chat_messages.session_id AND s.workspace_id = {placeholder})"
            if workspace_id else ""
        )
        rows = connection.execute(
            f"""
            SELECT session_id, role, content, CAST(created_at AS TEXT) AS created_at
            FROM chat_messages
            WHERE session_id = {placeholder}
              {workspace_filter}
            ORDER BY id ASC
            """,
            (session_id, workspace_id) if workspace_id else (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_sessions(workspace_id: str | None = None) -> list[dict]:
    with _connection() as (connection, placeholder):
        workspace_filter = f"WHERE s.workspace_id = {placeholder}" if workspace_id else ""
        rows = connection.execute(
            f"""
            SELECT m.session_id,
                   COALESCE(NULLIF(TRIM(s.title), ''), (
                       SELECT first.content FROM chat_messages AS first
                       WHERE first.session_id = m.session_id AND first.role = 'user'
                       ORDER BY first.id ASC LIMIT 1
                   ), 'New Chat') AS title,
                   CAST(MAX(m.created_at) AS TEXT) AS updated_at
            FROM chat_messages AS m
            JOIN chat_sessions AS s ON s.session_id = m.session_id
            {workspace_filter}
            GROUP BY m.session_id, s.title
            ORDER BY MAX(m.created_at) DESC, MAX(m.id) DESC
            """,
            (workspace_id,) if workspace_id else (),
        ).fetchall()
    return [dict(row) for row in rows]


def rename_session(session_id: str, workspace_id: str | None, title: str) -> dict | None:
    """Set only the manual title of a session in the requested workspace."""
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            workspace_filter = f" AND workspace_id = {placeholder}" if workspace_id else ""
            parameters = (title, session_id, workspace_id) if workspace_id else (title, session_id)
            cursor.execute(
                f"UPDATE chat_sessions SET title = {placeholder} WHERE session_id = {placeholder}{workspace_filter}",
                parameters,
            )
            if cursor.rowcount == 0:
                return None
    return next((item for item in list_sessions(workspace_id) if item["session_id"] == session_id), None)


def delete_session(session_id: str) -> dict[str, int]:
    """Delete only this session's business records in one transaction."""
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            cursor.execute(f"DELETE FROM token_usage WHERE session_id = {placeholder}", (session_id,))
            deleted_usage = cursor.rowcount
            cursor.execute(f"DELETE FROM chat_messages WHERE session_id = {placeholder}", (session_id,))
            deleted_messages = cursor.rowcount
            cursor.execute(f"DELETE FROM chat_sessions WHERE session_id = {placeholder}", (session_id,))
    return {"deleted_messages": deleted_messages, "deleted_usage": deleted_usage}


def get_usage_summary() -> dict[str, int]:
    with _connection() as (connection, _placeholder):
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS request_count,
                COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM token_usage
            """
        ).fetchone()
    return dict(row)


def _workspace_row(row) -> dict:
    item = dict(row)
    item["tool_settings"] = json.loads(item["tool_settings"])
    item["is_default"] = item["id"] == DEFAULT_WORKSPACE_ID
    item["created_at"] = str(item["created_at"])
    item["updated_at"] = str(item["updated_at"])
    return item


def list_workspaces() -> list[dict]:
    with _connection() as (connection, _):
        rows = connection.execute("SELECT * FROM workspaces ORDER BY created_at, id").fetchall()
    return [_workspace_row(row) for row in rows]


def get_workspace(workspace_id: str) -> dict | None:
    with _connection() as (connection, placeholder):
        row = connection.execute(f"SELECT * FROM workspaces WHERE id = {placeholder}", (workspace_id,)).fetchone()
    return _workspace_row(row) if row else None


def create_workspace(name: str, description: str = "", system_prompt: str = "", default_model_id: str | None = None, tool_settings: dict | None = None) -> dict:
    workspace_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as (connection, placeholder):
        connection.execute(
            f"INSERT INTO workspaces (id, name, description, system_prompt, default_model_id, tool_settings, created_at, updated_at) VALUES ({', '.join([placeholder] * 8)})",
            (workspace_id, name, description, system_prompt, default_model_id, json.dumps(tool_settings or {}), now, now),
        )
    return get_workspace(workspace_id)


def update_workspace(workspace_id: str, changes: dict) -> dict | None:
    if not changes:
        return get_workspace(workspace_id)
    if "tool_settings" in changes:
        changes["tool_settings"] = json.dumps(changes["tool_settings"])
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _connection() as (connection, placeholder):
        assignments = ", ".join(f"{key} = {placeholder}" for key in changes)
        cursor = connection.execute(
            f"UPDATE workspaces SET {assignments} WHERE id = {placeholder}",
            (*changes.values(), workspace_id),
        )
        if not cursor.rowcount:
            return None
    return get_workspace(workspace_id)


def session_workspace_id(session_id: str) -> str | None:
    with _connection() as (connection, placeholder):
        row = connection.execute(f"SELECT workspace_id FROM chat_sessions WHERE session_id = {placeholder}", (session_id,)).fetchone()
    return row["workspace_id"] if row else None


def delete_workspace_business(workspace_id: str) -> dict[str, int]:
    """Delete business rows in one transaction after external data has been staged."""
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise ValueError("Default Workspace cannot be deleted")
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            cursor.execute(f"DELETE FROM token_usage WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE workspace_id = {placeholder})", (workspace_id,))
            usage = cursor.rowcount
            cursor.execute(f"DELETE FROM chat_messages WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE workspace_id = {placeholder})", (workspace_id,))
            messages = cursor.rowcount
            cursor.execute(f"DELETE FROM chat_sessions WHERE workspace_id = {placeholder}", (workspace_id,))
            sessions = cursor.rowcount
            cursor.execute(f"DELETE FROM workspaces WHERE id = {placeholder}", (workspace_id,))
            if cursor.rowcount != 1:
                raise ValueError("Workspace not found")
    return {"deleted_sessions": sessions, "deleted_messages": messages, "deleted_usage": usage}
