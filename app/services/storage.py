"""SQLite persistence: the audit trail + feedback log.

Every triage decision and every human override is persisted here. This one
table set is simultaneously the explainability record, the closed feedback
loop, and the source for the metrics page.

Raw sqlite3 (no ORM) keeps the dependency surface small and the SQL visible.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS triage_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    subject        TEXT,
    body           TEXT,
    customer_tier  TEXT,
    category       TEXT,
    priority       TEXT,
    assigned_team  TEXT,
    confidence     REAL,
    needs_review   INTEGER,
    reasons        TEXT,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id        TEXT NOT NULL,
    correct_category TEXT,
    correct_priority TEXT,
    correct_team     TEXT,
    reviewer         TEXT,
    note             TEXT,
    was_override     INTEGER,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ticket ON triage_events(ticket_id);
CREATE INDEX IF NOT EXISTS idx_feedback_ticket ON feedback(ticket_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def ping(self) -> bool:
        try:
            with self._conn() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    # --- writes -------------------------------------------------------------
    def record_triage(self, event: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO triage_events
                   (ticket_id, correlation_id, subject, body, customer_tier,
                    category, priority, assigned_team, confidence, needs_review,
                    reasons, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["ticket_id"],
                    event["correlation_id"],
                    event.get("subject"),
                    event.get("body"),
                    event.get("customer_tier"),
                    event.get("category"),
                    event.get("priority"),
                    event.get("assigned_team"),
                    event.get("confidence"),
                    1 if event.get("needs_review") else 0,
                    json.dumps(event.get("reasons", [])),
                    _now(),
                ),
            )

    def record_feedback(
        self,
        ticket_id: str,
        correct_category: str | None,
        correct_priority: str | None,
        correct_team: str | None,
        reviewer: str | None,
        note: str | None,
        was_override: bool,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO feedback
                   (ticket_id, correct_category, correct_priority, correct_team,
                    reviewer, note, was_override, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    ticket_id,
                    correct_category,
                    correct_priority,
                    correct_team,
                    reviewer,
                    note,
                    1 if was_override else 0,
                    _now(),
                ),
            )

    # --- reads --------------------------------------------------------------
    def latest_event(self, ticket_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM triage_events WHERE ticket_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (ticket_id,),
            ).fetchone()
        return dict(row) if row else None

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM triage_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            events = conn.execute("SELECT COUNT(*) FROM triage_events").fetchone()[0]
            reviews = conn.execute(
                "SELECT COUNT(*) FROM triage_events WHERE needs_review = 1"
            ).fetchone()[0]
            feedback = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            overrides = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE was_override = 1"
            ).fetchone()[0]
        return {
            "events": events,
            "needs_review": reviews,
            "feedback": feedback,
            "overrides": overrides,
        }
