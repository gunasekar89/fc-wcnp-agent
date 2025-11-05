"""SQLite based state management for K-Agent."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    actor TEXT,
    action TEXT,
    status TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class SQLiteStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def insert_audit(self, event_id: str, actor: str, action: str, status: str, metadata: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(event_id, actor, action, status, metadata) VALUES (?, ?, ?, ?, ?)",
                (event_id, actor, action, status, metadata),
            )
            conn.commit()

    def fetch_audit(self, limit: int = 50) -> Iterable[Tuple[str, str, str, str, str, str]]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT event_id, actor, action, status, metadata, created_at FROM audit_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            yield from cursor.fetchall()
