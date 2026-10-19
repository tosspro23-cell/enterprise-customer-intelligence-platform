from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.adapters.persistence.postgres import PostgresStore
from backend.domain.auth import AuthorizationRegistry
from backend.domain.models import InteractionRecord
from backend.orchestration.realtime import Platform


POSTGRES_TEST_DSN = os.getenv("POSTGRES_TEST_DSN", "").strip()
pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_DSN,
    reason="set POSTGRES_TEST_DSN to run the PostgreSQL integration contract",
)


@pytest.fixture
def store() -> PostgresStore:
    instance = PostgresStore(POSTGRES_TEST_DSN)
    try:
        yield instance
    finally:
        instance.close()


def _record(
    *,
    call_id: str,
    customer_id: str = "C001",
    interaction_id: str | None = None,
    transcript_version: int = 1,
    content_hash: str | None = None,
    created_at: datetime | None = None,
) -> InteractionRecord:
    return InteractionRecord(
        interaction_id=interaction_id or f"interaction-{uuid4().hex}",
        call_id=call_id,
        customer_id=customer_id,
        transcript_version=transcript_version,
        enrichment_version=1,
        transcript_snapshot_id=f"snapshot-{call_id}-v{transcript_version}",
        content_hash=content_hash or f"hash-{transcript_version}",
        summary=f"summary-{transcript_version}",
        overall_sentiment="NEGATIVE",
        aspect_sentiment={"fees": "NEGATIVE"},
        themes=("fees",),
        evidence_refs=(f"segment-{transcript_version}",),
        created_at=created_at or datetime.now(timezone.utc),
    )


def test_postgres_preserves_idempotency_and_newer_current_lineage(store: PostgresStore) -> None:
    call_id = f"call-{uuid4().hex}"
    customer_id = f"customer-{uuid4().hex}"
    first = _record(call_id=call_id, customer_id=customer_id, transcript_version=1)

    saved, inserted = store.write_interaction(first)
    assert inserted is True
    assert saved.interaction_id == first.interaction_id

    retry, inserted = store.write_interaction(first)
    assert inserted is False
    assert retry.interaction_id == first.interaction_id

    retry_with_new_id = _record(
        call_id=call_id,
        customer_id=customer_id,
        interaction_id=f"retry-{uuid4().hex}",
        transcript_version=1,
        content_hash=first.content_hash,
    )
    canonical_retry, inserted = store.write_interaction(retry_with_new_id)
    assert inserted is False
    assert canonical_retry.interaction_id == first.interaction_id

    newer = _record(
        call_id=call_id,
        customer_id=customer_id,
        transcript_version=2,
        created_at=first.created_at + timedelta(microseconds=1),
    )
    store.write_interaction(newer)
    stale_retry, inserted = store.write_interaction(first)
    assert inserted is False
    assert stale_retry.interaction_id == first.interaction_id

    current = store.current_interaction(call_id)
    assert current is not None
    assert current["interaction_id"] == newer.interaction_id
    assert current["transcript_version"] == 2
    assert json.loads(current["aspect_sentiment_json"]) == {"fees": "NEGATIVE"}
    assert [item["interaction_id"] for item in store.history(customer_id)] == [newer.interaction_id]


def test_postgres_rejects_content_conflict_and_blocks_tombstone_resurrection(store: PostgresStore) -> None:
    call_id = f"call-{uuid4().hex}"
    customer_id = f"customer-{uuid4().hex}"
    original = _record(
        call_id=call_id,
        customer_id=customer_id,
        transcript_version=1,
        content_hash="stable-hash",
    )
    store.write_interaction(original)

    conflicting = _record(
        call_id=call_id,
        customer_id=customer_id,
        transcript_version=1,
        content_hash="different-hash",
    )
    with pytest.raises(ValueError, match="content hash conflict"):
        store.write_interaction(conflicting)

    deleted_at = datetime.now(timezone.utc)
    store.delete_derived(call_id, customer_id, "deletion-epoch-1", deleted_at)
    assert store.is_deleted(call_id) is True
    assert store.current_interaction(call_id) is None
    assert store.history(customer_id) == []
    with pytest.raises(RuntimeError, match="deleted"):
        store.write_interaction(original)


def test_postgres_trace_write_is_observable_and_idempotently_replaceable(store: PostgresStore) -> None:
    call_id = f"call-{uuid4().hex}"
    trace = {
        "trace_id": f"trace-{uuid4().hex}",
        "call_id": call_id,
        "correlation_id": "corr-1",
        "state_version": 3,
        "stage": "post_call_enrichment",
        "started_at": "2026-10-19T10:00:00+00:00",
        "ended_at": "2026-10-19T10:00:01+00:00",
        "status": "SUCCEEDED",
        "input_ref": "snapshot-1",
        "output_ref": "interaction-1",
        "model_version": "deterministic-en-v1",
        "error_code": None,
    }
    store.write_trace(trace)
    replaced = {**trace, "status": "FAILED", "error_code": "late-retry"}
    store.write_trace(replaced)

    traces = store.traces(call_id)
    assert len(traces) == 1
    assert traces[0]["status"] == "FAILED"
    assert traces[0]["error_code"] == "late-retry"


@pytest.mark.asyncio
async def test_platform_post_call_round_trip_uses_postgres_store(store: PostgresStore) -> None:
    registry = AuthorizationRegistry()
    auth = registry.register(
        "postgres-agent",
        permissions={
            "READ_CALL",
            "SUBSCRIBE_CALL",
            "INGEST_TRANSCRIPT",
            "UPDATE_COMPLAINT",
            "END_CALL",
            "RUN_POSTCALL",
            "DELETE_DERIVED",
        },
        allowed_customer_ids={"C001"},
    )
    platform = Platform(store=store, registry=registry)

    started = await platform.start_call(auth, "C001")
    call_id = started["call"]["call_id"]
    await platform.ingest_segment(
        auth,
        call_id,
        segment_id="postgres-segment",
        revision=1,
        is_final=True,
        speaker="CUSTOMER",
        text="I need help understanding this account charge.",
    )
    await platform.end_call(auth, call_id)
    result = await platform.post_call(auth, call_id)

    assert result["inserted"] is True
    assert result["current"]["call_id"] == call_id
    assert platform.store.history("C001")[0]["call_id"] == call_id
    assert platform.store.traces(call_id)[-1]["stage"] == "post_call_enrichment"
