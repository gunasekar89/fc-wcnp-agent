"""Conversation history and audit log persistence for K-Agent."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ..models import AuditRecord
from .sqlite_db import SQLiteStorage


@dataclass
class ConversationTurn:
    role: str
    content: str
    metadata: dict = field(default_factory=dict)


class HistoryManager:
    def __init__(self, storage: SQLiteStorage, history_file: Path) -> None:
        self.storage = storage
        self.history_file = history_file
        if not self.history_file.exists():
            self.history_file.write_text("[]", encoding="utf-8")

    def append_turn(self, role: str, content: str, metadata: dict | None = None) -> None:
        history = self._load_history()
        history.append(ConversationTurn(role=role, content=content, metadata=metadata or {}))
        serialized = [turn.__dict__ for turn in history]
        self.history_file.write_text(json.dumps(serialized, indent=2), encoding="utf-8")

    def _load_history(self) -> List[ConversationTurn]:
        raw = json.loads(self.history_file.read_text(encoding="utf-8"))
        return [ConversationTurn(**item) for item in raw]

    def record_audit(self, record: AuditRecord) -> None:
        self.storage.insert_audit(
            event_id=record.event_id,
            actor=record.actor,
            action=record.action,
            status=record.status,
            metadata=json.dumps(record.metadata),
        )

    def recent_audit(self, limit: int = 20) -> List[AuditRecord]:
        rows = self.storage.fetch_audit(limit=limit)
        return [
            AuditRecord(
                event_id=row[0],
                actor=row[1],
                action=row[2],
                status=row[3],
                metadata=json.loads(row[4] or "{}"),
            )
            for row in rows
        ]

    def new_event_id(self) -> str:
        return str(uuid.uuid4())
