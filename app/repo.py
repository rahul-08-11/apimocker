import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .db import db


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_workspace(user_id: str, admin_token: str, name: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO workspaces(user_id, admin_token, name, created_at_utc) VALUES (?, ?, ?, ?)",
            (user_id, admin_token, name, utc_now_iso()),
        )


def get_workspace(user_id: str) -> Optional[Dict[str, Any]]:
    with db() as conn:
        row = conn.execute("SELECT * FROM workspaces WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def list_workspaces(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    with db() as conn:
        rows = conn.execute(
            "SELECT user_id, name, created_at_utc FROM workspaces ORDER BY created_at_utc DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def check_admin(user_id: str, admin_token: str) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM workspaces WHERE user_id = ? AND admin_token = ?",
            (user_id, admin_token),
        ).fetchone()
        return row is not None


def replace_routes(user_id: str, routes: List[Dict[str, Any]]) -> None:
    with db() as conn:
        conn.execute("DELETE FROM routes WHERE user_id = ?", (user_id,))
        for r in routes:
            conn.execute(
                """
                INSERT INTO routes(user_id, method, path, query_json, status, delay_ms, headers_json, response_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    r["method"].upper(),
                    r["path"],
                    json.dumps(r.get("query") or {}),
                    int(r.get("status", 200)),
                    int(r.get("delay_ms", 0) or 0),
                    json.dumps(r.get("headers") or {}),
                    json.dumps(r.get("response")),
                ),
            )


def list_routes(user_id: str) -> List[Dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT method, path, query_json, status, delay_ms, headers_json, response_json FROM routes WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "method": row["method"],
                    "path": row["path"],
                    "query": json.loads(row["query_json"] or "{}"),
                    "status": row["status"],
                    "delay_ms": row["delay_ms"],
                    "headers": json.loads(row["headers_json"] or "{}"),
                    "response": json.loads(row["response_json"]) if row["response_json"] is not None else None,
                }
            )
        return out

