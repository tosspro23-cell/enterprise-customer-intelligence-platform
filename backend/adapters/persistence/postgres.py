from __future__ import annotations

import json
from datetime import datetime
from threading import RLock
from typing import Any, Callable

from backend.domain.models import InteractionRecord


INTERACTION_COLUMNS = (
    "interaction_id",
    "call_id",
    "customer_id",
    "transcript_version",
    "enrichment_version",
    "transcript_snapshot_id",
    "content_hash",
    "summary",
    "overall_sentiment",
    "aspect_sentiment_json",
    "themes_json",
    "evidence_refs_json",
    "created_at",
)


class PostgresStore:
    """PostgreSQL adapter preserving the SQLite persistence contract.

    The adapter uses one synchronous connection to match the current modular
    monolith. It is a persistence boundary, not yet a connection-pool or
    multi-worker live-state implementation. Per-call PostgreSQL advisory locks
    make post-call writes and deletion serialize across processes.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not dsn.strip():
            raise ValueError("DATABASE_URL must not be empty")
        self.dsn = dsn
        self._lock = RLock()
        if connection_factory is None:
            try:
                import psycopg
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "PostgreSQL persistence requires the postgres-runtime dependency"
                ) from exc
            self._connection = psycopg.connect(dsn)
        else:
            self._connection = connection_factory(dsn)
        # Reads must not leave an implicit transaction open between calls. Writes
        # use explicit ``connection.transaction()`` blocks below, so autocommit
        # gives both paths predictable boundaries on a long-lived app process.
        self._connection.autocommit = True
        self._create_schema()

    def _create_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                call_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                state_version INTEGER,
                stage TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                ended_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL,
                input_ref TEXT,
                output_ref TEXT,
                model_version TEXT,
                error_code TEXT
            )
            """,
            """
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
                aspect_sentiment_json JSONB NOT NULL,
                themes_json JSONB NOT NULL,
                evidence_refs_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                UNIQUE(call_id, transcript_version, enrichment_version),
                UNIQUE(call_id, transcript_version, content_hash)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS current_interactions (
                call_id TEXT PRIMARY KEY,
                interaction_id TEXT NOT NULL REFERENCES interactions(interaction_id),
                transcript_version INTEGER NOT NULL,
                enrichment_version INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tombstones (
                call_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                deletion_epoch TEXT NOT NULL,
                deleted_at TIMESTAMPTZ NOT NULL
            )
            """,
            """
            INSERT INTO schema_migrations(version)
            VALUES (%s)
            ON CONFLICT(version) DO NOTHING
            """,
        )
        with self._lock, self._connection.transaction():
            with self._connection.cursor() as cursor:
                for statement in statements[:-1]:
                    cursor.execute(statement)
                cursor.execute(statements[-1], (self.SCHEMA_VERSION,))

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def write_trace(self, trace: dict[str, Any]) -> None:
        with self._lock, self._connection.transaction():
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO traces(
                        trace_id, call_id, correlation_id, state_version, stage,
                        started_at, ended_at, status, input_ref, output_ref,
                        model_version, error_code
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(trace_id) DO UPDATE SET
                        call_id=excluded.call_id,
                        correlation_id=excluded.correlation_id,
                        state_version=excluded.state_version,
                        stage=excluded.stage,
                        started_at=excluded.started_at,
                        ended_at=excluded.ended_at,
                        status=excluded.status,
                        input_ref=excluded.input_ref,
                        output_ref=excluded.output_ref,
                        model_version=excluded.model_version,
                        error_code=excluded.error_code
                    """,
                    (
                        trace["trace_id"],
                        trace["call_id"],
                        trace["correlation_id"],
                        trace.get("state_version"),
                        trace["stage"],
                        trace["started_at"],
                        trace["ended_at"],
                        trace["status"],
                        trace.get("input_ref"),
                        trace.get("output_ref"),
                        trace.get("model_version"),
                        trace.get("error_code"),
                    ),
                )

    def _lock_call(self, cursor, call_id: str) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (call_id,))

    def is_deleted(self, call_id: str) -> bool:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM tombstones WHERE call_id = %s", (call_id,))
                return cursor.fetchone() is not None

    def write_interaction(self, record: InteractionRecord) -> tuple[InteractionRecord, bool]:
        """Write once, advance the current pointer only for newer lineage."""

        with self._lock, self._connection.transaction():
            with self._connection.cursor() as cursor:
                self._lock_call(cursor, record.call_id)
                cursor.execute("SELECT 1 FROM tombstones WHERE call_id = %s", (record.call_id,))
                if cursor.fetchone() is not None:
                    raise RuntimeError("call is deleted; post-call write blocked")

                cursor.execute(
                    """
                    SELECT interaction_id, content_hash FROM interactions
                    WHERE call_id = %s AND transcript_version = %s
                      AND enrichment_version = %s
                    """,
                    (record.call_id, record.transcript_version, record.enrichment_version),
                )
                existing = cursor.fetchone()
                if existing is not None and existing[1] != record.content_hash:
                    raise ValueError("post-call content hash conflict")

                inserted = existing is None
                canonical_interaction_id = (
                    record.interaction_id if inserted else existing[0]
                )
                if inserted:
                    cursor.execute(
                        """
                        INSERT INTO interactions(
                            interaction_id, call_id, customer_id, transcript_version,
                            enrichment_version, transcript_snapshot_id, content_hash,
                            summary, overall_sentiment, aspect_sentiment_json,
                            themes_json, evidence_refs_json, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  %s::jsonb, %s::jsonb, %s::jsonb, %s)
                        """,
                        (
                            record.interaction_id,
                            record.call_id,
                            record.customer_id,
                            record.transcript_version,
                            record.enrichment_version,
                            record.transcript_snapshot_id,
                            record.content_hash,
                            record.summary,
                            record.overall_sentiment,
                            json.dumps(record.aspect_sentiment, sort_keys=True),
                            json.dumps(record.themes),
                            json.dumps(record.evidence_refs),
                            record.created_at,
                        ),
                    )

                cursor.execute(
                    """
                    INSERT INTO current_interactions(
                        call_id, interaction_id, transcript_version, enrichment_version
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT(call_id) DO UPDATE SET
                        interaction_id=excluded.interaction_id,
                        transcript_version=excluded.transcript_version,
                        enrichment_version=excluded.enrichment_version
                    WHERE (excluded.transcript_version, excluded.enrichment_version) >
                          (current_interactions.transcript_version,
                           current_interactions.enrichment_version)
                    """,
                    (
                        record.call_id,
                        canonical_interaction_id,
                        record.transcript_version,
                        record.enrichment_version,
                    ),
                )
                if inserted:
                    return record, True
                cursor.execute(
                    f"""
                    SELECT {', '.join(f'i.{name}' for name in INTERACTION_COLUMNS)}
                    FROM interactions i
                    WHERE i.interaction_id = %s
                    """,
                    (canonical_interaction_id,),
                )
                canonical = cursor.fetchone()
                if canonical is None:
                    raise RuntimeError("canonical interaction disappeared during retry")
                return self._record_from_row(canonical), False

    @staticmethod
    def _value(row: Any, key: str, index: int) -> Any:
        return row[key] if isinstance(row, dict) else row[index]

    @classmethod
    def _interaction_dict(cls, row: Any) -> dict[str, Any]:
        result = {
            name: cls._value(row, name, index)
            for index, name in enumerate(INTERACTION_COLUMNS)
        }
        for name in ("aspect_sentiment_json", "themes_json", "evidence_refs_json"):
            if not isinstance(result[name], str):
                result[name] = json.dumps(result[name], sort_keys=name == "aspect_sentiment_json")
        if isinstance(result["created_at"], datetime):
            result["created_at"] = result["created_at"].isoformat()
        return result

    @classmethod
    def _record_from_row(cls, row: Any) -> InteractionRecord:
        values = cls._interaction_dict(row)
        created_at = values["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return InteractionRecord(
            interaction_id=values["interaction_id"],
            call_id=values["call_id"],
            customer_id=values["customer_id"],
            transcript_version=values["transcript_version"],
            enrichment_version=values["enrichment_version"],
            transcript_snapshot_id=values["transcript_snapshot_id"],
            content_hash=values["content_hash"],
            summary=values["summary"],
            overall_sentiment=values["overall_sentiment"],
            aspect_sentiment=json.loads(values["aspect_sentiment_json"]),
            themes=tuple(json.loads(values["themes_json"])),
            evidence_refs=tuple(json.loads(values["evidence_refs_json"])),
            created_at=created_at,
        )

    def current_interaction(self, call_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {', '.join(f'i.{name}' for name in INTERACTION_COLUMNS)}
                    FROM interactions i
                    JOIN current_interactions c ON c.interaction_id = i.interaction_id
                    WHERE i.call_id = %s
                    """,
                    (call_id,),
                )
                row = cursor.fetchone()
                return self._interaction_dict(row) if row else None

    def history(self, customer_id: str) -> list[dict[str, Any]]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {', '.join(f'i.{name}' for name in INTERACTION_COLUMNS)}
                    FROM interactions i
                    JOIN current_interactions c ON c.interaction_id = i.interaction_id
                    WHERE i.customer_id = %s
                    ORDER BY i.created_at
                    """,
                    (customer_id,),
                )
                return [self._interaction_dict(row) for row in cursor.fetchall()]

    def delete_derived(
        self,
        call_id: str,
        customer_id: str,
        deletion_epoch: str,
        deleted_at: datetime,
    ) -> None:
        with self._lock, self._connection.transaction():
            with self._connection.cursor() as cursor:
                self._lock_call(cursor, call_id)
                cursor.execute(
                    """
                    INSERT INTO tombstones(call_id, customer_id, deletion_epoch, deleted_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(call_id) DO NOTHING
                    """,
                    (call_id, customer_id, deletion_epoch, deleted_at),
                )
                cursor.execute("DELETE FROM current_interactions WHERE call_id = %s", (call_id,))
                cursor.execute("DELETE FROM interactions WHERE call_id = %s", (call_id,))

    def traces(self, call_id: str) -> list[dict[str, Any]]:
        columns = (
            "trace_id", "call_id", "correlation_id", "state_version", "stage",
            "started_at", "ended_at", "status", "input_ref", "output_ref",
            "model_version", "error_code",
        )
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {', '.join(columns)} FROM traces WHERE call_id = %s ORDER BY started_at",
                    (call_id,),
                )
                rows = cursor.fetchall()
                return [
                    {
                        name: self._normalise_value(self._value(row, name, index))
                        for index, name in enumerate(columns)
                    }
                    for row in rows
                ]

    @staticmethod
    def _normalise_value(value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value
