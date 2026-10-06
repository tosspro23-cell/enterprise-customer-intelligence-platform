from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from backend.adapters.persistence.sqlite import SQLiteStore


class TraceRecorder:
    def __init__(self, store: SQLiteStore, clock) -> None:
        self.store = store
        self.clock = clock

    def record(
        self,
        *,
        call_id: str,
        correlation_id: str,
        state_version: int | None,
        stage: str,
        status: str,
        input_ref: str | None = None,
        output_ref: str | None = None,
        model_version: str | None = None,
        error_code: str | None = None,
        started_at: datetime | None = None,
    ) -> dict:
        ended_at = self.clock.now()
        trace = {
            "trace_id": str(uuid4()),
            "call_id": call_id,
            "correlation_id": correlation_id,
            "state_version": state_version,
            "stage": stage,
            "started_at": (started_at or ended_at).isoformat(),
            "ended_at": ended_at.isoformat(),
            "status": status,
            "input_ref": input_ref,
            "output_ref": output_ref,
            "model_version": model_version,
            "error_code": error_code,
        }
        self.store.write_trace(trace)
        return trace
