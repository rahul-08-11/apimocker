import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def _db_path() -> str:
    # Railway typically provides a persistent volume only if configured.
    # Default to a local file in the project directory.
    return os.environ.get("MOCKER_DB_PATH", str(Path(__file__).resolve().parent.parent / "mocker.sqlite3"))


def init_db() -> None:
    with sqlite3.connect(_db_path()) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
              user_id TEXT PRIMARY KEY,
              admin_token TEXT NOT NULL,
              name TEXT NOT NULL,
              created_at_utc TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS routes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              method TEXT NOT NULL,
              path TEXT NOT NULL,
              query_json TEXT,
              status INTEGER NOT NULL,
              delay_ms INTEGER NOT NULL DEFAULT 0,
              headers_json TEXT,
              response_json TEXT,
              FOREIGN KEY(user_id) REFERENCES workspaces(user_id)
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(routes)").fetchall()}
        if "query_json" not in cols:
            conn.execute("ALTER TABLE routes ADD COLUMN query_json TEXT;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_routes_user_id ON routes(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_routes_user_method_path ON routes(user_id, method, path);")


@contextmanager
def db():
    conn = sqlite3.connect(_db_path())
    try:
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    finally:
        conn.close()

