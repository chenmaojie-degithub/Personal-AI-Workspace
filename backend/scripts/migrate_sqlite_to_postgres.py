from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = BACKEND_ROOT / "data" / "ai_chat.sqlite3"
TABLE_COLUMNS = {
    "chat_messages": ("id", "session_id", "role", "content", "created_at"),
    "token_usage": (
        "id",
        "session_id",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "created_at",
    ),
}


def _stats(connection) -> dict[str, int]:
    return {
        "chat_messages": connection.execute(
            "SELECT COUNT(*) FROM chat_messages"
        ).fetchone()[0],
        "token_usage": connection.execute(
            "SELECT COUNT(*) FROM token_usage"
        ).fetchone()[0],
        "total_tokens": connection.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage"
        ).fetchone()[0],
    }


def migrate() -> None:
    load_dotenv(BACKEND_ROOT / ".env")
    password = os.getenv("POSTGRES_TARGET_PASSWORD")
    if not password:
        raise RuntimeError("POSTGRES_TARGET_PASSWORD is missing")
    if not SQLITE_PATH.is_file():
        raise FileNotFoundError(f"SQLite database not found: {SQLITE_PATH}")

    with closing(sqlite3.connect(SQLITE_PATH)) as source:
        source.row_factory = sqlite3.Row
        source_stats = _stats(source)
        print(f"SQLite before: {source_stats}")

        with psycopg.connect(
            host="127.0.0.1",
            port=5432,
            dbname="ai_chat",
            user="ai_chat",
            password=password,
        ) as target:
            target_stats_before = _stats(target)
            print(f"PostgreSQL before: {target_stats_before}")

            with target.cursor() as cursor:
                for table, columns in TABLE_COLUMNS.items():
                    rows = source.execute(
                        f"SELECT {', '.join(columns)} FROM {table} ORDER BY id"
                    ).fetchall()
                    statement = sql.SQL(
                        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT (id) DO NOTHING"
                    ).format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                    )
                    cursor.executemany(
                        statement,
                        [tuple(row[column] for column in columns) for row in rows],
                    )
                    cursor.execute(
                        sql.SQL(
                            "SELECT setval(pg_get_serial_sequence({}, 'id'), "
                            "GREATEST(COALESCE(MAX(id), 1), 1), MAX(id) IS NOT NULL) FROM {}"
                        ).format(sql.Literal(table), sql.Identifier(table))
                    )

            target_stats_after = _stats(target)
            print(f"PostgreSQL after: {target_stats_after}")
            if target_stats_after != source_stats:
                raise RuntimeError(
                    "Migration verification failed: PostgreSQL statistics do not match SQLite"
                )

    print("Migration verified; SQLite source was preserved")


if __name__ == "__main__":
    migrate()
