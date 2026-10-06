from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Literal

Permission = Literal[
    "READ_CALL",
    "SUBSCRIBE_CALL",
    "INGEST_TRANSCRIPT",
    "UPDATE_COMPLAINT",
    "END_CALL",
    "RUN_POSTCALL",
    "DELETE_DERIVED",
]

BusinessOutcome = Literal[
    "RECOMMEND",
    "SUPPRESS",
    "UNAVAILABLE",
    "NO_ELIGIBLE_OPTION",
]

DeliveryState = Literal[
    "GENERATING",
    "VALIDATED",
    "PUBLISH_COMMITTED",
    "SERVER_PUBLISHED",
    "UI_ACKNOWLEDGED",
    "INVALIDATED",
    "WITHDRAWN",
    "EXPIRED",
    "FAILED",
]

TERMINAL_DELIVERY_STATES = {"INVALIDATED", "WITHDRAWN", "EXPIRED", "FAILED"}
VISIBLE_DELIVERY_STATES = {"PUBLISH_COMMITTED", "SERVER_PUBLISHED", "UI_ACKNOWLEDGED"}


def payload_hash(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    principal_id: str
    tenant_id: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    allowed_customer_ids: frozenset[str]
    purpose_of_use: str
    correlation_id: str
    authz_version: int
    issued_at: datetime


@dataclass(frozen=True)
class CallBinding:
    call_id: str
    customer_id: str
    tenant_id: str
    created_at: datetime


@dataclass(frozen=True)
class TranscriptSegment:
    call_id: str
    segment_id: str
    revision: int
    is_final: bool
    speaker: Literal["CUSTOMER", "AGENT"]
    text: str
    language: str
    source_timestamp: datetime
    payload_hash: str


@dataclass
class SegmentProcessingState:
    segment_id: str
    revision: int
    stored: bool = True
    derivation_status: Literal["PENDING", "SUCCEEDED", "FAILED", "OBSOLETE"] = "PENDING"
    last_error: str | None = None
    attempt: int = 0


@dataclass(frozen=True)
class CanonicalTranscriptSnapshot:
    call_id: str
    transcript_version: int
    content_hash: str
    segments: tuple[TranscriptSegment, ...]


@dataclass(frozen=True)
class SentimentAspect:
    aspect: str
    label: Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"]
    score: float
    evidence_segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SentimentState:
    overall_label: Literal["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"] = "UNKNOWN"
    overall_score: float = 0.0
    aspects: dict[str, SentimentAspect] = field(default_factory=dict)
    model_group: str = "deterministic-en-v1"
    as_of_transcript_version: int = 0


@dataclass(frozen=True)
class ComplaintState:
    status: Literal["OPEN", "RESOLVED", "UNKNOWN"]
    source: Literal["AUTHORITATIVE_MOCK_API", "INITIAL_FIXTURE"]
    version: int
    as_of: datetime
    expires_at: datetime
    resolved_through_transcript_version: int | None = None


@dataclass(frozen=True)
class ComplaintSignal:
    active: bool
    evidence_segment_ids: tuple[str, ...] = ()
    evidence_transcript_versions: tuple[int, ...] = ()
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CustomerContext:
    customer_id: str
    name: str
    segment: str
    language: str
    tenure_months: int


@dataclass(frozen=True)
class DependencyRef:
    name: str
    snapshot_id: str
    version: str
    as_of: datetime
    expires_at: datetime


@dataclass(frozen=True)
class DecisionDependencies:
    complaint: DependencyRef | None = None
    eligibility: DependencyRef | None = None
    propensity: DependencyRef | None = None
    product_facts: DependencyRef | None = None
    guidance: DependencyRef | None = None


@dataclass
class Decision:
    decision_id: str
    call_id: str
    kind: Literal["HANDLING_GUIDANCE", "COMMERCIAL_RECOMMENDATION"]
    business_outcome: BusinessOutcome
    delivery_state: DeliveryState
    based_on_state_version: int
    based_on_authz_version: int
    based_on_transcript_version: int
    dependencies: DecisionDependencies
    created_at: datetime
    expires_at: datetime
    publication_seq: int | None = None
    product_id: str | None = None
    generated_text: str | None = None
    structured_facts: dict = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    invalidation_reason: str | None = None
    transport_attempts: int = 0


@dataclass
class CallState:
    call_id: str
    customer_id: str
    status: Literal["ACTIVE", "TRANSFERRED", "ENDED", "DELETED"]
    state_version: int
    ui_seq: int
    canonical_transcript_version: int
    derived_transcript_version: int
    derivation_status: Literal["PENDING", "COMPLETE", "FAILED"]
    transcript: dict[str, TranscriptSegment]
    processing: dict[str, SegmentProcessingState]
    transcript_event_versions: dict[str, int]
    sentiment: SentimentState
    complaint: ComplaintState
    complaint_signal: ComplaintSignal
    customer_context: CustomerContext | None
    commercial_context: dict = field(default_factory=dict)
    pending_decision_ids: set[str] = field(default_factory=set)
    published_decision_ids: set[str] = field(default_factory=set)
    decisions: dict[str, Decision] = field(default_factory=dict)
    last_updated_at: datetime | None = None

    def canonical_snapshot(self) -> CanonicalTranscriptSnapshot:
        ordered = tuple(
            self.transcript[key]
            for key in sorted(self.transcript)
        )
        content = payload_hash(
            *[
                f"{s.segment_id}:{s.revision}:{s.payload_hash}:{s.text}"
                for s in ordered
            ]
        )
        return CanonicalTranscriptSnapshot(
            call_id=self.call_id,
            transcript_version=self.canonical_transcript_version,
            content_hash=content,
            segments=ordered,
        )


@dataclass(frozen=True)
class InteractionRecord:
    interaction_id: str
    call_id: str
    customer_id: str
    transcript_version: int
    enrichment_version: int
    transcript_snapshot_id: str
    content_hash: str
    summary: str
    overall_sentiment: str
    aspect_sentiment: dict[str, str]
    themes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    created_at: datetime


def is_visible(decision: Decision) -> bool:
    return decision.delivery_state in VISIBLE_DELIVERY_STATES
