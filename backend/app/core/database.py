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

CREATE TABLE IF NOT EXISTS project_folders (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    parent_id TEXT REFERENCES project_folders(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_folders_parent
ON project_folders (workspace_id, parent_id, position);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    folder_id TEXT REFERENCES project_folders(id),
    position INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_workspace
ON chat_sessions (workspace_id, updated_at);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    goal TEXT NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_session
ON agent_runs (session_id, created_at);

CREATE TABLE IF NOT EXISTS agent_steps (
    id {id_type},
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    step_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    tool_name TEXT,
    status TEXT NOT NULL,
    input_json TEXT,
    output_preview TEXT,
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE (run_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run
ON agent_steps (run_id, step_index);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id),
    session_id TEXT,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    extension TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    content_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_workspace_name
ON documents (workspace_id, filename) WHERE workspace_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_session_name
ON documents (session_id, filename) WHERE workspace_id IS NULL AND session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_documents_workspace_hash
ON documents (workspace_id, content_sha256);
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
            session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_sessions)")}
            if "title" not in session_columns:
                connection.execute("ALTER TABLE chat_sessions ADD COLUMN title TEXT")
            if "folder_id" not in session_columns:
                connection.execute("ALTER TABLE chat_sessions ADD COLUMN folder_id TEXT REFERENCES project_folders(id)")
            if "position" not in session_columns:
                connection.execute("ALTER TABLE chat_sessions ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        else:
            for statement in schema.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS title TEXT")
            connection.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS folder_id TEXT REFERENCES project_folders(id)")
            connection.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
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
                last_position = cursor.execute(
                    f"""SELECT COALESCE(MAX(position), -1) AS position FROM (
                        SELECT position FROM chat_sessions WHERE workspace_id = {placeholder} AND folder_id IS NULL
                        UNION ALL
                        SELECT position FROM project_folders WHERE workspace_id = {placeholder} AND parent_id IS NULL
                    ) AS root_items""",
                    (resolved_workspace, resolved_workspace),
                ).fetchone()["position"]
                cursor.execute(
                    f"INSERT INTO chat_sessions (session_id, workspace_id, position, created_at, updated_at) VALUES ({', '.join([placeholder] * 5)})",
                    (session_id, resolved_workspace, last_position + 1, created_at, created_at),
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
                   CAST(MAX(m.created_at) AS TEXT) AS updated_at,
                   s.folder_id,
                   s.position
            FROM chat_messages AS m
            JOIN chat_sessions AS s ON s.session_id = m.session_id
            {workspace_filter}
            GROUP BY m.session_id, s.title, s.folder_id, s.position
            ORDER BY MAX(m.created_at) DESC, MAX(m.id) DESC
            """,
            (workspace_id,) if workspace_id else (),
        ).fetchall()
    return [dict(row) for row in rows]


def list_project_tree(workspace_id: str) -> dict[str, list[dict]]:
    """Return the persisted folder tree and its sessions for one workspace."""
    if not get_workspace(workspace_id):
        raise ValueError("Workspace not found")
    with _connection() as (connection, placeholder):
        folders = connection.execute(
            f"""SELECT id, workspace_id, parent_id, name, position,
                       CAST(created_at AS TEXT) AS created_at, CAST(updated_at AS TEXT) AS updated_at
                FROM project_folders WHERE workspace_id = {placeholder}
                ORDER BY position, created_at, id""",
            (workspace_id,),
        ).fetchall()
    sessions = list_sessions(workspace_id)
    sessions.sort(key=lambda item: (item["position"], item["updated_at"], item["session_id"]))
    return {"folders": [dict(row) for row in folders], "sessions": sessions}


def _ordered_project_items(cursor, placeholder: str, workspace_id: str, parent_id: str | None, excluded: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    parent_filter = f"parent_id = {placeholder}" if parent_id else "parent_id IS NULL"
    folder_rows = cursor.execute(
        f"SELECT id, position FROM project_folders WHERE workspace_id = {placeholder} AND {parent_filter}",
        (workspace_id, parent_id) if parent_id else (workspace_id,),
    ).fetchall()
    folder_filter = f"folder_id = {placeholder}" if parent_id else "folder_id IS NULL"
    session_rows = cursor.execute(
        f"SELECT session_id AS id, position FROM chat_sessions WHERE workspace_id = {placeholder} AND {folder_filter}",
        (workspace_id, parent_id) if parent_id else (workspace_id,),
    ).fetchall()
    items = [("folder", row["id"], row["position"]) for row in folder_rows]
    items += [("session", row["id"], row["position"]) for row in session_rows]
    items.sort(key=lambda item: (item[2], item[0], item[1]))
    return [(kind, identifier) for kind, identifier, _ in items if excluded != (kind, identifier)]


def _write_project_positions(cursor, placeholder: str, items: list[tuple[str, str]]) -> None:
    for position, (kind, identifier) in enumerate(items):
        table, column = ("project_folders", "id") if kind == "folder" else ("chat_sessions", "session_id")
        cursor.execute(
            f"UPDATE {table} SET position = {placeholder} WHERE {column} = {placeholder}",
            (position, identifier),
        )


def create_project_folder(workspace_id: str, name: str, parent_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    folder_id = str(uuid4())
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            if not cursor.execute(f"SELECT 1 FROM workspaces WHERE id = {placeholder}", (workspace_id,)).fetchone():
                raise ValueError("Workspace not found")
            if parent_id and not cursor.execute(
                f"SELECT 1 FROM project_folders WHERE id = {placeholder} AND workspace_id = {placeholder}",
                (parent_id, workspace_id),
            ).fetchone():
                raise ValueError("Parent folder not found in workspace")
            position = len(_ordered_project_items(cursor, placeholder, workspace_id, parent_id))
            cursor.execute(
                f"INSERT INTO project_folders (id, workspace_id, parent_id, name, position, created_at, updated_at) VALUES ({', '.join([placeholder] * 7)})",
                (folder_id, workspace_id, parent_id, name, position, now, now),
            )
    return next(item for item in list_project_tree(workspace_id)["folders"] if item["id"] == folder_id)


def rename_project_folder(folder_id: str, workspace_id: str, name: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as (connection, placeholder):
        cursor = connection.execute(
            f"UPDATE project_folders SET name = {placeholder}, updated_at = {placeholder} WHERE id = {placeholder} AND workspace_id = {placeholder}",
            (name, now, folder_id, workspace_id),
        )
        if cursor.rowcount == 0:
            return None
    return next(item for item in list_project_tree(workspace_id)["folders"] if item["id"] == folder_id)


def move_project_item(workspace_id: str, item_type: str, item_id: str, parent_id: str | None, position: int) -> dict[str, list[dict]]:
    """Move one folder/session and normalize the target order atomically."""
    if item_type not in {"folder", "session"}:
        raise ValueError("Invalid project item type")
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            if parent_id and not cursor.execute(
                f"SELECT 1 FROM project_folders WHERE id = {placeholder} AND workspace_id = {placeholder}",
                (parent_id, workspace_id),
            ).fetchone():
                raise ValueError("Target folder not found in workspace")
            if item_type == "folder":
                row = cursor.execute(
                    f"SELECT parent_id FROM project_folders WHERE id = {placeholder} AND workspace_id = {placeholder}",
                    (item_id, workspace_id),
                ).fetchone()
                if not row:
                    raise ValueError("Folder not found in workspace")
                ancestor = parent_id
                while ancestor:
                    if ancestor == item_id:
                        raise ValueError("A folder cannot be moved into itself or its descendants")
                    parent = cursor.execute(
                        f"SELECT parent_id FROM project_folders WHERE id = {placeholder} AND workspace_id = {placeholder}",
                        (ancestor, workspace_id),
                    ).fetchone()
                    ancestor = parent["parent_id"] if parent else None
                cursor.execute(
                    f"UPDATE project_folders SET parent_id = {placeholder}, updated_at = {placeholder} WHERE id = {placeholder}",
                    (parent_id, datetime.now(timezone.utc).isoformat(), item_id),
                )
            else:
                row = cursor.execute(
                    f"SELECT folder_id FROM chat_sessions WHERE session_id = {placeholder} AND workspace_id = {placeholder}",
                    (item_id, workspace_id),
                ).fetchone()
                if not row:
                    raise ValueError("Session not found in workspace")
                cursor.execute(
                    f"UPDATE chat_sessions SET folder_id = {placeholder} WHERE session_id = {placeholder}",
                    (parent_id, item_id),
                )
            items = _ordered_project_items(cursor, placeholder, workspace_id, parent_id, (item_type, item_id))
            target = max(0, min(position, len(items)))
            items.insert(target, (item_type, item_id))
            _write_project_positions(cursor, placeholder, items)
    return list_project_tree(workspace_id)


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
            cursor.execute(f"DELETE FROM documents WHERE workspace_id IS NULL AND session_id = {placeholder}", (session_id,))
            cursor.execute(f"DELETE FROM agent_steps WHERE run_id IN (SELECT id FROM agent_runs WHERE session_id = {placeholder})", (session_id,))
            cursor.execute(f"DELETE FROM agent_runs WHERE session_id = {placeholder}", (session_id,))
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


def create_agent_run(run_id: str, session_id: str, workspace_id: str, goal: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as (connection, placeholder):
        if not connection.execute(f"SELECT 1 FROM workspaces WHERE id = {placeholder}", (workspace_id,)).fetchone():
            raise ValueError("Workspace not found")
        connection.execute(
            f"INSERT INTO agent_runs (id, session_id, workspace_id, goal, plan_json, status, created_at, updated_at) VALUES ({', '.join([placeholder] * 8)})",
            (run_id, session_id, workspace_id, goal, "[]", "planning", now, now),
        )
    return get_agent_run(run_id, workspace_id) or {}


def update_agent_run(
    run_id: str,
    *,
    status: str | None = None,
    plan: list[dict] | None = None,
    provider: str | None = None,
    model: str | None = None,
    usage: LLMUsage | None = None,
    error: str | None = None,
    completed: bool = False,
) -> None:
    values: dict[str, object] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if status is not None:
        values["status"] = status
    if plan is not None:
        values["plan_json"] = json.dumps(plan, ensure_ascii=False)
    if provider is not None:
        values["provider"] = provider
    if model is not None:
        values["model"] = model
    if usage is not None:
        values.update({
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        })
    if error is not None:
        values["error"] = error[:2000]
    if completed:
        values["completed_at"] = values["updated_at"]
    with _connection() as (connection, placeholder):
        assignments = ", ".join(f"{name} = {placeholder}" for name in values)
        cursor = connection.execute(
            f"UPDATE agent_runs SET {assignments} WHERE id = {placeholder}",
            (*values.values(), run_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Agent run not found")


def upsert_agent_step(
    run_id: str,
    step_index: int,
    title: str,
    status: str,
    *,
    tool_name: str | None = None,
    input_data: dict | None = None,
    output_preview: str | None = None,
    error: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    terminal = status in {"completed", "failed", "cancelled", "skipped"}
    with _connection() as (connection, placeholder):
        existing = connection.execute(
            f"SELECT id, started_at FROM agent_steps WHERE run_id = {placeholder} AND step_index = {placeholder}",
            (run_id, step_index),
        ).fetchone()
        values = (
            title[:300], tool_name, status,
            json.dumps(input_data, ensure_ascii=False) if input_data is not None else None,
            output_preview[:4000] if output_preview is not None else None,
            error[:2000] if error is not None else None,
            now if terminal else None,
        )
        if existing:
            connection.execute(
                f"UPDATE agent_steps SET title = {placeholder}, tool_name = {placeholder}, status = {placeholder}, input_json = {placeholder}, output_preview = {placeholder}, error = {placeholder}, completed_at = {placeholder} WHERE id = {placeholder}",
                (*values, existing["id"]),
            )
        else:
            connection.execute(
                f"INSERT INTO agent_steps (run_id, step_index, title, tool_name, status, input_json, output_preview, error, started_at, completed_at) VALUES ({', '.join([placeholder] * 10)})",
                (run_id, step_index, *values[:6], now, values[6]),
            )


def get_agent_run(run_id: str, workspace_id: str | None = None) -> dict | None:
    with _connection() as (connection, placeholder):
        workspace_filter = f" AND workspace_id = {placeholder}" if workspace_id else ""
        parameters = (run_id, workspace_id) if workspace_id else (run_id,)
        row = connection.execute(
            f"SELECT *, CAST(created_at AS TEXT) AS created_at_text, CAST(updated_at AS TEXT) AS updated_at_text, CAST(completed_at AS TEXT) AS completed_at_text FROM agent_runs WHERE id = {placeholder}{workspace_filter}",
            parameters,
        ).fetchone()
        if not row:
            return None
        steps = connection.execute(
            f"SELECT step_index, title, tool_name, status, input_json, output_preview, error, CAST(started_at AS TEXT) AS started_at, CAST(completed_at AS TEXT) AS completed_at FROM agent_steps WHERE run_id = {placeholder} ORDER BY step_index",
            (run_id,),
        ).fetchall()
    result = dict(row)
    result["plan"] = json.loads(result.pop("plan_json"))
    result["created_at"] = result.pop("created_at_text")
    result["updated_at"] = result.pop("updated_at_text")
    result["completed_at"] = result.pop("completed_at_text")
    result["steps"] = []
    for step in steps:
        item = dict(step)
        item["input"] = json.loads(item.pop("input_json")) if item["input_json"] else None
        result["steps"].append(item)
    return result


def latest_agent_run(session_id: str, workspace_id: str) -> dict | None:
    with _connection() as (connection, placeholder):
        row = connection.execute(
            f"SELECT id FROM agent_runs WHERE session_id = {placeholder} AND workspace_id = {placeholder} ORDER BY created_at DESC LIMIT 1",
            (session_id, workspace_id),
        ).fetchone()
    return get_agent_run(row["id"], workspace_id) if row else None


def create_document_record(
    *,
    filename: str,
    content_type: str,
    byte_size: int,
    content_sha256: str,
    workspace_id: str | None = None,
    session_id: str | None = None,
    document_id: str | None = None,
) -> dict:
    if not workspace_id and not session_id:
        raise ValueError("workspace_id or session_id is required")
    if workspace_id and not get_workspace(workspace_id):
        raise ValueError("Workspace not found")
    identifier = document_id or str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as (connection, placeholder):
        connection.execute(
            f"INSERT INTO documents (id, workspace_id, session_id, filename, content_type, extension, byte_size, content_sha256, status, created_at, updated_at) VALUES ({', '.join([placeholder] * 11)})",
            (
                identifier, workspace_id, session_id, filename, content_type,
                Path(filename).suffix.lower(), byte_size, content_sha256,
                "uploaded", now, now,
            ),
        )
    return get_document_record(identifier) or {}


def update_document_record(
    document_id: str,
    *,
    status: str | None = None,
    chunk_count: int | None = None,
    error: str | None = None,
) -> None:
    values: dict[str, object] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if status is not None:
        values["status"] = status
    if chunk_count is not None:
        values["chunk_count"] = chunk_count
    if error is not None:
        values["error"] = error[:2000]
    elif status in {"indexed", "ready"}:
        values["error"] = None
    with _connection() as (connection, placeholder):
        assignments = ", ".join(f"{name} = {placeholder}" for name in values)
        cursor = connection.execute(
            f"UPDATE documents SET {assignments} WHERE id = {placeholder}",
            (*values.values(), document_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Document not found")


def get_document_record(document_id: str, workspace_id: str | None = None) -> dict | None:
    with _connection() as (connection, placeholder):
        workspace_filter = f" AND workspace_id = {placeholder}" if workspace_id else ""
        parameters = (document_id, workspace_id) if workspace_id else (document_id,)
        row = connection.execute(
            f"SELECT *, CAST(created_at AS TEXT) AS created_at_text, CAST(updated_at AS TEXT) AS updated_at_text FROM documents WHERE id = {placeholder}{workspace_filter}",
            parameters,
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["created_at"] = result.pop("created_at_text")
    result["updated_at"] = result.pop("updated_at_text")
    return result


def list_document_records(*, workspace_id: str | None = None, session_id: str | None = None) -> list[dict]:
    if not workspace_id and not session_id:
        raise ValueError("workspace_id or session_id is required")
    with _connection() as (connection, placeholder):
        if workspace_id:
            rows = connection.execute(
                f"SELECT id FROM documents WHERE workspace_id = {placeholder} ORDER BY created_at, id",
                (workspace_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                f"SELECT id FROM documents WHERE workspace_id IS NULL AND session_id = {placeholder} ORDER BY created_at, id",
                (session_id,),
            ).fetchall()
    return [record for row in rows if (record := get_document_record(row["id"]))]


def find_document_by_name(filename: str, *, workspace_id: str | None = None, session_id: str | None = None) -> dict | None:
    return next((item for item in list_document_records(workspace_id=workspace_id, session_id=session_id) if item["filename"] == filename), None)


def find_document_by_hash(content_sha256: str, *, workspace_id: str | None = None, session_id: str | None = None) -> dict | None:
    return next((item for item in list_document_records(workspace_id=workspace_id, session_id=session_id) if item["content_sha256"] == content_sha256), None)


def delete_document_record(document_id: str) -> bool:
    with _connection() as (connection, placeholder):
        cursor = connection.execute(f"DELETE FROM documents WHERE id = {placeholder}", (document_id,))
    return cursor.rowcount == 1


def delete_workspace_business(workspace_id: str) -> dict[str, int]:
    """Delete business rows in one transaction after external data has been staged."""
    if workspace_id == DEFAULT_WORKSPACE_ID:
        raise ValueError("Default Workspace cannot be deleted")
    with _connection() as (connection, placeholder):
        with closing(connection.cursor()) as cursor:
            cursor.execute(f"DELETE FROM documents WHERE workspace_id = {placeholder}", (workspace_id,))
            cursor.execute(f"DELETE FROM agent_steps WHERE run_id IN (SELECT id FROM agent_runs WHERE workspace_id = {placeholder})", (workspace_id,))
            cursor.execute(f"DELETE FROM agent_runs WHERE workspace_id = {placeholder}", (workspace_id,))
            cursor.execute(f"DELETE FROM token_usage WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE workspace_id = {placeholder})", (workspace_id,))
            usage = cursor.rowcount
            cursor.execute(f"DELETE FROM chat_messages WHERE session_id IN (SELECT session_id FROM chat_sessions WHERE workspace_id = {placeholder})", (workspace_id,))
            messages = cursor.rowcount
            cursor.execute(f"DELETE FROM chat_sessions WHERE workspace_id = {placeholder}", (workspace_id,))
            sessions = cursor.rowcount
            cursor.execute(f"DELETE FROM project_folders WHERE workspace_id = {placeholder}", (workspace_id,))
            cursor.execute(f"DELETE FROM workspaces WHERE id = {placeholder}", (workspace_id,))
            if cursor.rowcount != 1:
                raise ValueError("Workspace not found")
    return {"deleted_sessions": sessions, "deleted_messages": messages, "deleted_usage": usage}
