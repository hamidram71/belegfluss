"""Persisted match results and the human review queue.

Every match is stored with its full result. Sets the agent approves are stored as
``auto_approved`` (auditable, but not in the queue); everything else waits in the queue until a
reviewer approves or rejects it. A decision can be made once; the record keeps who decided,
when and why.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from belegfluss.agent.models import MatchResult
from belegfluss.domain.discrepancies import Decision
from belegfluss.domain.models import Model


class MatchStatus(StrEnum):
    OPEN = "open"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"


class MatchRecord(Model):
    match_id: str
    created_at: datetime
    invoice_document_id: str | None
    delivery_note_document_id: str | None
    result: MatchResult
    status: MatchStatus
    reviewer: str | None = None
    comment: str | None = None
    decided_at: datetime | None = None


class AlreadyDecidedError(ValueError):
    """The match is not open (auto-approved or already decided)."""


class MatchStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, match_id: str) -> Path:
        return self.root / f"{match_id}.json"

    def _write(self, record: MatchRecord) -> None:
        self._path(record.match_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def add(
        self,
        result: MatchResult,
        invoice_document_id: str | None = None,
        delivery_note_document_id: str | None = None,
    ) -> MatchRecord:
        record = MatchRecord(
            match_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC),
            invoice_document_id=invoice_document_id,
            delivery_note_document_id=delivery_note_document_id,
            result=result,
            status=(
                MatchStatus.AUTO_APPROVED
                if result.decision is Decision.APPROVE
                else MatchStatus.OPEN
            ),
        )
        self._write(record)
        return record

    def get(self, match_id: str) -> MatchRecord | None:
        try:
            uuid.UUID(match_id)
        except ValueError:
            return None
        path = self._path(match_id)
        if not path.exists():
            return None
        return MatchRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def all(self) -> list[MatchRecord]:
        records = [
            MatchRecord.model_validate(json.loads(p.read_text(encoding="utf-8")))
            for p in self.root.glob("*.json")
        ]
        return sorted(records, key=lambda r: r.created_at)

    def queue(self) -> list[MatchRecord]:
        return [r for r in self.all() if r.status is MatchStatus.OPEN]

    def decide(
        self, match_id: str, approve: bool, reviewer: str, comment: str | None
    ) -> MatchRecord:
        record = self.get(match_id)
        if record is None:
            raise KeyError(match_id)
        if record.status is not MatchStatus.OPEN:
            raise AlreadyDecidedError(f"match is {record.status.value}")
        decided = record.model_copy(
            update={
                "status": MatchStatus.APPROVED if approve else MatchStatus.REJECTED,
                "reviewer": reviewer,
                "comment": comment,
                "decided_at": datetime.now(UTC),
            }
        )
        self._write(decided)
        return decided
