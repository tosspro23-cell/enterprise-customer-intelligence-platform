from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from backend.domain.models import InteractionRecord


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


class SQLiteStore:
    """SQLite persistence with explicit transactions for content/tombstone races."""

    def __init__(self, path: str | Path = "./data/platform.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    call_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    state_version INTEGER,
                    stage TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_ref TEXT,
                    output_ref TEXT,
                    model_version TEXT,
                    error_code TEXT
                );
                CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY,
                    call_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    transcript_version INTEGER NOT NULL,
                    enrichment_version INTEGER NOT NULL,
                    transcript_snapshot_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    overall_sentiment TEXT NOT NULL,
                    aspect_sentiment_json TEXT NOT NULL,
                    themes_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(call_id, transcript_version, enrichment_version),
                    UNIQUE(call_id, transcript_version, content_hash)
                );
                CREATE TABLE IF NOT EXISTS current_interactions (
                    call_id TEXT PRIMARY KEY,
                    interaction_id TEXT NOT NULL,
                    transcript_version INTEGER NOT NULL,
                    enrichment_version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tombstones (
                    call_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    deletion_epoch TEXT NOT NULL,
                    deleted_at TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def write_trace(self, trace: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR REPLACE INTO traces
                (trace_id, call_id, correlation_id, state_version, stage,
                 started_at, ended_at, status, input_ref, output_ref,
                 model_version, error_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace["trace_id"], trace["call_id"], trace["correlation_id"],
                    trace.get("state_version"), trace["stage"], trace["started_at"],
                    trace["ended_at"], trace["status"], trace.get("input_ref"),
                    trace.get("output_ref"), trace.get("model_version"), trace.get("error_code"),
                ),
            )

    def is_deleted(self, call_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM tombstones WHERE call_id = ?", (call_id,)
            ).fetchone()
            return row is not None

    def write_interaction(self, record: InteractionRecord) -> tuple[InteractionRecord, bool]:
        """Write once and update current pointer only when lineage is newer."""
        payload = asdict(record)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                if self._connection.execute(
                    "SELECT 1 FROM tombstones WHERE call_id = ?", (record.call_id,)
                ).fetchone():
                    self._connection.rollback()
                    raise RuntimeError("call is deleted; post-call write blocked")

                existing = self._connection.execute(
                    """SELECT * FROM interactions
                       WHERE call_id = ? AND transcript_version = ?
                       AND enrichment_version = ?""",
                    (record.call_id, record.transcript_version, record.enrichment_version),
                ).fetchone()
                if existing and existing["content_hash"] != record.content_hash:
                    self._connection.rollback()
                    raise ValueError("post-call content hash conflict")

                inserted = existing is None
                if inserted:
                    self._connection.execute(
                        """INSERT INTO interactions
                        (interaction_id, call_id, customer_id, transcript_version,
                         enrichment_version, transcript_snapshot_id, content_hash,
                         summary, overall_sentiment, aspect_sentiment_json,
                         themes_json, evidence_refs_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            record.interaction_id, record.call_id, record.customer_id,
                            record.transcript_version, record.enrichment_version,
                            record.transcript_snapshot_id, record.content_hash,
                            record.summary, record.overall_sentiment,
                            json.dumps(record.aspect_sentiment, sort_keys=True),
                            json.dumps(record.themes), json.dumps(record.evidence_refs),
                            record.created_at.isoformat(),
                        ),
                    )

                current = self._connection.execute(
                    "SELECT * FROM current_interactions WHERE call_id = ?", (record.call_id,)
                ).fetchone()
                newer = current is None or (
                    record.transcript_version,
                    record.enrichment_version,
                ) > (current["transcript_version"], current["enrichment_version"])
                if newer:
                    self._connection.execute(
                        """INSERT INTO current_interactions
                        (call_id, interaction_id, transcript_version, enrichment_version)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(call_id) DO UPDATE SET
                          interaction_id=excluded.interaction_id,
                          transcript_version=excluded.transcript_version,
                          enrichment_version=excluded.enrichment_version""",
                        (record.call_id, record.interaction_id, record.transcript_version, record.enrichment_version),
                    )
                self._connection.commit()
                return record, inserted
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def current_interaction(self, call_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT i.* FROM interactions i
                   JOIN current_interactions c ON c.interaction_id = i.interaction_id
                   WHERE i.call_id = ?""", (call_id,)
            ).fetchone()
            return dict(row) if row else None

    def history(self, customer_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT i.* FROM interactions i
                   JOIN current_interactions c ON c.interaction_id = i.interaction_id
                   WHERE i.customer_id = ? ORDER BY i.created_at""", (customer_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_derived(self, call_id: str, customer_id: str, deletion_epoch: str, deleted_at: datetime) -> None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """INSERT INTO tombstones(call_id, customer_id, deletion_epoch, deleted_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(call_id) DO NOTHING""",
                    (call_id, customer_id, deletion_epoch, deleted_at.isoformat()),
                )
                self._connection.execute("DELETE FROM current_interactions WHERE call_id = ?", (call_id,))
                self._connection.execute("DELETE FROM interactions WHERE call_id = ?", (call_id,))
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def traces(self, call_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM traces WHERE call_id = ? ORDER BY started_at", (call_id,)
            ).fetchall()
            return [dict(row) for row in rows]
