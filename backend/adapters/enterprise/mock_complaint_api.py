from __future__ import annotations

from datetime import datetime, timedelta

from backend.domain.models import ComplaintState


class MockComplaintAPI:
    def initial(self, now: datetime) -> ComplaintState:
        return ComplaintState(
            status="OPEN",
            source="INITIAL_FIXTURE",
            version=1,
            as_of=now,
            expires_at=now + timedelta(seconds=30),
            resolved_through_transcript_version=None,
        )

    def resolved(self, now: datetime, version: int, through_transcript_version: int) -> ComplaintState:
        return ComplaintState(
            status="RESOLVED",
            source="AUTHORITATIVE_MOCK_API",
            version=version,
            as_of=now,
            expires_at=now + timedelta(seconds=30),
            resolved_through_transcript_version=through_transcript_version,
        )

    def open(self, now: datetime, version: int) -> ComplaintState:
        return ComplaintState(
            status="OPEN",
            source="AUTHORITATIVE_MOCK_API",
            version=version,
            as_of=now,
            expires_at=now + timedelta(seconds=30),
            resolved_through_transcript_version=None,
        )
