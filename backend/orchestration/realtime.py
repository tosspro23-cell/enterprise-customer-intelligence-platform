from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.adapters.enterprise.mock_complaint_api import MockComplaintAPI
from backend.adapters.enterprise.mock_customer_api import MockCustomerAPI
from backend.adapters.enterprise.mock_product_api import MockProductAPI, ProductFacts
from backend.adapters.enterprise.mock_propensity_service import (
    MockPropensityService,
    PropensityResult,
    PropensityUnavailable,
)
from backend.adapters.guidance.local_index import GuidanceResult, LocalGuidanceIndex
from backend.adapters.llm.base import ExplanationRequest, LLMUnavailable
from backend.adapters.llm.fake import DeterministicExplanationAdapter
from backend.adapters.persistence.sqlite import SQLiteStore
from backend.domain.auth import AuthorizationError, AuthorizationRegistry
from backend.domain.models import (
    AuthContext,
    CallBinding,
    CallState,
    CanonicalTranscriptSnapshot,
    ComplaintSignal,
    CustomerContext,
    Decision,
    DecisionDependencies,
    DependencyRef,
    InteractionRecord,
    SentimentState,
    SegmentProcessingState,
    TranscriptSegment,
    TERMINAL_DELIVERY_STATES,
    VISIBLE_DELIVERY_STATES,
    is_visible,
    payload_hash,
)
from backend.services.clock import Clock
from backend.services.eligibility import DeterministicEligibilityService, EligibilityResult
from backend.services.explanation_validator import ExplanationValidator
from backend.services.sentiment import TextAspectSentimentAdapter
from backend.services.themes import detect_themes
from backend.telemetry.traces import TraceRecorder


class PlatformError(RuntimeError):
    pass


class NotFoundError(PlatformError):
    pass


class ConflictError(PlatformError):
    pass


class Platform:
    """Single-process reference platform with explicit per-call serialization."""

    DECISION_TTL = timedelta(seconds=15)

    def __init__(
        self,
        *,
        store: SQLiteStore | None = None,
        clock: Clock | None = None,
        registry: AuthorizationRegistry | None = None,
        customer_api: MockCustomerAPI | None = None,
        complaint_api: MockComplaintAPI | None = None,
        propensity: MockPropensityService | None = None,
        eligibility: DeterministicEligibilityService | None = None,
        product_api: MockProductAPI | None = None,
        guidance: LocalGuidanceIndex | None = None,
        sentiment: TextAspectSentimentAdapter | None = None,
        llm: Any | None = None,
    ) -> None:
        self.store = store or SQLiteStore(":memory:")
        self.clock = clock or Clock()
        self.registry = registry or AuthorizationRegistry()
        self.customer_api = customer_api or MockCustomerAPI()
        self.complaint_api = complaint_api or MockComplaintAPI()
        self.propensity = propensity or MockPropensityService()
        self.eligibility = eligibility or DeterministicEligibilityService()
        self.product_api = product_api or MockProductAPI()
        self.guidance = guidance or LocalGuidanceIndex()
        self.sentiment = sentiment or TextAspectSentimentAdapter()
        self.llm = llm or DeterministicExplanationAdapter()
        self.validator = ExplanationValidator()
        self.traces = TraceRecorder(self.store, self.clock)
        self.calls: dict[str, CallState] = {}
        self.bindings: dict[str, CallBinding] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def close(self) -> None:
        self.store.close()

    def _lock_for(self, call_id: str) -> asyncio.Lock:
        return self._locks.setdefault(call_id, asyncio.Lock())

    def _binding(self, call_id: str) -> CallBinding:
        try:
            return self.bindings[call_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown call: {call_id}") from exc

    def _state(self, call_id: str) -> CallState:
        try:
            return self.calls[call_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown call: {call_id}") from exc

    def _check(self, auth: AuthContext, call_id: str, permission: str) -> CallBinding:
        binding = self._binding(call_id)
        self.registry.check(auth, permission=permission, binding=binding)
        return binding

    async def start_call(self, auth: AuthContext, customer_id: str) -> dict:
        customer = self.customer_api.get(customer_id)
        call_id = f"call-{uuid4().hex[:12]}"
        binding = CallBinding(call_id, customer_id, auth.tenant_id, self.clock.now())
        self.registry.check(auth, permission="READ_CALL", binding=binding)
        now = self.clock.now()
        complaint = self.complaint_api.initial(now)
        state = CallState(
            call_id=call_id,
            customer_id=customer_id,
            status="ACTIVE",
            state_version=1,
            ui_seq=0,
            canonical_transcript_version=0,
            derived_transcript_version=0,
            derivation_status="COMPLETE",
            transcript={},
            processing={},
            sentiment=SentimentState(),
            complaint=complaint,
            complaint_signal=ComplaintSignal(False, updated_at=now),
            customer_context=CustomerContext(
                customer_id=customer.customer_id,
                name=customer.name,
                segment=customer.segment,
                language=customer.language,
                tenure_months=customer.tenure_months,
            ),
            last_updated_at=now,
        )
        self.bindings[call_id] = binding
        self.calls[call_id] = state
        self._lock_for(call_id)
        self.traces.record(
            call_id=call_id,
            correlation_id=auth.correlation_id,
            state_version=state.state_version,
            stage="call_started",
            status="SUCCEEDED",
            output_ref=customer_id,
        )
        return self._view_unlocked(state)

    async def ingest_segment(
        self,
        auth: AuthContext,
        call_id: str,
        *,
        segment_id: str,
        revision: int,
        is_final: bool,
        speaker: str,
        text: str,
        language: str = "en",
        source_timestamp: datetime | None = None,
    ) -> dict:
        binding = self._check(auth, call_id, "INGEST_TRANSCRIPT")
        if speaker not in {"CUSTOMER", "AGENT"}:
            raise ValueError("speaker must be CUSTOMER or AGENT")
        segment = TranscriptSegment(
            call_id=call_id,
            segment_id=segment_id,
            revision=revision,
            is_final=is_final,
            speaker=speaker,  # type: ignore[arg-type]
            text=text,
            language=language,
            source_timestamp=source_timestamp or self.clock.now(),
            payload_hash=payload_hash(segment_id, str(revision), str(is_final), speaker, text, language),
        )
        async with self._lock_for(call_id):
            # Revalidation here is required after waiting for the call lock.
            self.registry.check(auth, permission="INGEST_TRANSCRIPT", binding=binding)
            state = self._state(call_id)
            if state.status == "DELETED":
                raise PlatformError("deleted call cannot accept transcript")
            current = state.transcript.get(segment_id)
            if current and current.revision == revision:
                if current.payload_hash != segment.payload_hash:
                    raise ConflictError("same segment revision has a different payload")
                snapshot = state.canonical_snapshot()
            elif current and revision < current.revision:
                return self._view_unlocked(state)
            else:
                state.transcript[segment_id] = segment
                state.processing[segment_id] = SegmentProcessingState(segment_id, revision)
                state.canonical_transcript_version += 1
                state.state_version += 1
                state.derivation_status = "PENDING"
                state.last_updated_at = self.clock.now()
                self._invalidate_transcript_decisions(state, "canonical transcript changed")
                snapshot = state.canonical_snapshot()
                self.traces.record(
                    call_id=call_id,
                    correlation_id=auth.correlation_id,
                    state_version=state.state_version,
                    stage="transcript_accepted",
                    status="SUCCEEDED",
                    input_ref=f"{segment_id}:{revision}",
                )
        await self._derive_snapshot(auth.correlation_id, snapshot)
        async with self._lock_for(call_id):
            return self._view_unlocked(self._state(call_id))

    async def _derive_snapshot(self, correlation_id: str, snapshot: CanonicalTranscriptSnapshot) -> None:
        started = self.clock.now()
        try:
            sentiment = await self.sentiment.analyze(snapshot.segments, snapshot.transcript_version)
        except Exception as exc:
            async with self._lock_for(snapshot.call_id):
                state = self._state(snapshot.call_id)
                for item in state.processing.values():
                    if item.revision and item.derivation_status == "PENDING":
                        item.derivation_status = "FAILED"
                        item.last_error = str(exc)
                        item.attempt += 1
                if snapshot.transcript_version == state.canonical_transcript_version:
                    state.derivation_status = "FAILED"
                self.traces.record(
                    call_id=snapshot.call_id,
                    correlation_id=correlation_id,
                    state_version=state.state_version,
                    stage="transcript_derivation",
                    status="FAILED",
                    error_code="DERIVATION_FAILED",
                    started_at=started,
                )
            return
        async with self._lock_for(snapshot.call_id):
            state = self._state(snapshot.call_id)
            if snapshot.transcript_version != state.canonical_transcript_version:
                self.traces.record(
                    call_id=snapshot.call_id,
                    correlation_id=correlation_id,
                    state_version=state.state_version,
                    stage="transcript_derivation",
                    status="OBSOLETE",
                    input_ref=str(snapshot.transcript_version),
                    started_at=started,
                )
                return
            state.sentiment = sentiment
            state.derived_transcript_version = snapshot.transcript_version
            state.derivation_status = "COMPLETE"
            state.complaint_signal = self._complaint_signal(state, sentiment, snapshot)
            for item in state.processing.values():
                if item.revision and item.derivation_status == "PENDING":
                    item.derivation_status = "SUCCEEDED"
            state.state_version += 1
            state.last_updated_at = self.clock.now()
            self.traces.record(
                call_id=snapshot.call_id,
                correlation_id=correlation_id,
                state_version=state.state_version,
                stage="transcript_derivation",
                status="SUCCEEDED",
                input_ref=str(snapshot.transcript_version),
                output_ref=sentiment.overall_label,
                model_version=sentiment.model_group,
                started_at=started,
            )

    def _complaint_signal(
        self,
        state: CallState,
        sentiment: SentimentState,
        snapshot: CanonicalTranscriptSnapshot,
    ) -> ComplaintSignal:
        evidence: list[str] = []
        fee = sentiment.aspects.get("fees")
        if fee and fee.label == "NEGATIVE":
            evidence.extend(fee.evidence_segment_ids)
        for segment in snapshot.segments:
            lowered = segment.text.lower()
            if segment.speaker == "CUSTOMER" and any(
                word in lowered for word in ("complaint", "terrible", "unfair", "expensive", "problem")
            ):
                if segment.segment_id not in evidence:
                    evidence.append(segment.segment_id)
        active = bool(evidence)
        covered = state.complaint.resolved_through_transcript_version
        if state.complaint.status == "RESOLVED" and covered is not None and snapshot.transcript_version <= covered:
            active = False
            evidence = []
        return ComplaintSignal(
            active=active,
            evidence_segment_ids=tuple(evidence),
            evidence_transcript_versions=tuple(snapshot.transcript_version for _ in evidence),
            updated_at=self.clock.now(),
        )

    async def resolve_complaint(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "UPDATE_COMPLAINT")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="UPDATE_COMPLAINT", binding=binding)
            state = self._state(call_id)
            if state.status == "DELETED":
                raise PlatformError("deleted call")
            state.complaint = self.complaint_api.resolved(
                self.clock.now(), state.complaint.version + 1, state.canonical_transcript_version
            )
            state.complaint_signal = self._complaint_signal(state, state.sentiment, state.canonical_snapshot())
            state.state_version += 1
            state.last_updated_at = self.clock.now()
            self._invalidate_active_decisions(state, "complaint authority changed")
            self.traces.record(
                call_id=call_id,
                correlation_id=auth.correlation_id,
                state_version=state.state_version,
                stage="complaint_authority",
                status="SUCCEEDED",
                output_ref="RESOLVED",
            )
            return self._view_unlocked(state)

    async def open_complaint(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "UPDATE_COMPLAINT")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="UPDATE_COMPLAINT", binding=binding)
            state = self._state(call_id)
            state.complaint = self.complaint_api.open(self.clock.now(), state.complaint.version + 1)
            state.complaint_signal = self._complaint_signal(state, state.sentiment, state.canonical_snapshot())
            state.state_version += 1
            self._invalidate_active_decisions(state, "complaint reopened")
            return self._view_unlocked(state)

    async def request_commercial(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "SUBSCRIBE_CALL")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="SUBSCRIBE_CALL", binding=binding)
            state = self._state(call_id)
            if state.status != "ACTIVE":
                raise PlatformError("commercial assistance is only available during an active call")
            if state.derivation_status != "COMPLETE" or state.derived_transcript_version != state.canonical_transcript_version:
                raise PlatformError("conversation derivation is pending")
            decision_id = f"decision-{uuid4().hex[:12]}"
            decision = Decision(
                decision_id=decision_id,
                call_id=call_id,
                kind="COMMERCIAL_RECOMMENDATION",
                business_outcome="UNAVAILABLE",
                delivery_state="GENERATING",
                based_on_state_version=state.state_version,
                based_on_authz_version=auth.authz_version,
                based_on_transcript_version=state.canonical_transcript_version,
                dependencies=DecisionDependencies(
                    complaint=self._complaint_ref(state.complaint),
                ),
                created_at=self.clock.now(),
                expires_at=self.clock.now() + self.DECISION_TTL,
            )
            state.decisions[decision_id] = decision
            state.pending_decision_ids.add(decision_id)
            context = state.customer_context
            complaint = state.complaint
            signal = state.complaint_signal
            state_version = state.state_version
            transcript_version = state.canonical_transcript_version
        return await self._generate_decision(
            auth,
            binding,
            decision_id,
            context,
            complaint,
            signal,
            state_version,
            transcript_version,
        )

    async def _generate_decision(
        self,
        auth: AuthContext,
        binding: CallBinding,
        decision_id: str,
        context: CustomerContext | None,
        complaint,
        signal: ComplaintSignal,
        based_state_version: int,
        based_transcript_version: int,
    ) -> dict:
        if context is None:
            raise PlatformError("customer context unavailable")
        now = self.clock.now()
        propensity: PropensityResult | None = None
        propensity_error: str | None = None
        try:
            propensity = await self.propensity.score_customer(context.customer_id, "SAVINGS_PLUS", now)
        except PropensityUnavailable as exc:
            propensity_error = str(exc)
        eligibility = self.eligibility.evaluate(self.customer_api.get(context.customer_id), now)
        product: ProductFacts | None = None
        blocking_complaint = complaint.status != "RESOLVED" or signal.active or complaint.expires_at <= now
        if not blocking_complaint and propensity is not None and eligibility.eligible_product_ids:
            product = self.product_api.get(eligibility.eligible_product_ids[0], now)

        if blocking_complaint:
            outcome = "SUPPRESS"
            topic = "fees"
            purpose = "COMPLAINT_HANDLING"
        elif propensity_error:
            outcome = "UNAVAILABLE"
            topic = "savings"
            purpose = "PRODUCT_EXPLANATION"
        elif not eligibility.eligible_product_ids:
            outcome = "NO_ELIGIBLE_OPTION"
            topic = "savings"
            purpose = "PRODUCT_EXPLANATION"
        else:
            outcome = "RECOMMEND"
            topic = "savings"
            purpose = "PRODUCT_EXPLANATION"

        guidance = self.guidance.search(topic, purpose=purpose, now=now)
        evidence_refs = [guidance.guidance_id] if guidance else []
        if guidance is None and outcome == "RECOMMEND":
            outcome = "UNAVAILABLE"
            product = None

        request = ExplanationRequest(
            outcome=outcome,
            customer_name=context.name,
            topic=topic,
            product_id=product.product_id if product else None,
            product_name=product.name if product else None,
            product_fee=product.monthly_fee if product else None,
            currency=product.currency if product else None,
            product_benefits=product.benefits if product else (),
            guidance_text=guidance.text if guidance else None,
            guidance_id=guidance.guidance_id if guidance else None,
            propensity_score=propensity.score if outcome == "RECOMMEND" and propensity else None,
            complaint_status=complaint.status,
        )
        explanation = None
        llm_error: str | None = None
        try:
            explanation = await self.llm.explain(request)
        except LLMUnavailable as exc:
            llm_error = str(exc)
            if outcome == "SUPPRESS":
                explanation = type("Fallback", (), {
                    "text": "Guidance is temporarily unavailable; acknowledge the concern and do not present an additional product.",
                    "model_name": "approved-fallback",
                    "model_version": "fallback-v1",
                    "structured_facts": {"product_id": None, "product_name": None, "monthly_fee": None, "currency": None, "benefits": [], "propensity_score": None},
                })()
            else:
                outcome = "UNAVAILABLE"
                product = None
                request = ExplanationRequest(
                    outcome=outcome, customer_name=context.name, topic=topic,
                    product_id=None, product_name=None, product_fee=None, currency=None,
                    product_benefits=(), guidance_text=guidance.text if guidance else None,
                    guidance_id=guidance.guidance_id if guidance else None,
                    propensity_score=None, complaint_status=complaint.status,
                )
                try:
                    explanation = await self.llm.explain(request)
                except LLMUnavailable:
                    explanation = type("Fallback", (), {
                        "text": "The assistance service is temporarily unavailable; do not present a product offer.",
                        "model_name": "approved-fallback",
                        "model_version": "fallback-v1",
                        "structured_facts": {"product_id": None, "product_name": None, "monthly_fee": None, "currency": None, "benefits": [], "propensity_score": None},
                    })()

        dependencies = self._dependencies(complaint, eligibility, propensity, product, guidance, outcome)
        async with self._lock_for(binding.call_id):
            state = self._state(binding.call_id)
            decision = state.decisions.get(decision_id)
            if decision is None:
                raise NotFoundError(decision_id)
            try:
                self.registry.check(auth, permission="SUBSCRIBE_CALL", binding=binding)
            except AuthorizationError:
                self._invalidate_decision(state, decision, "authorization revoked")
                return self._view_unlocked(state)
            stale = (
                state.status != "ACTIVE"
                or state.state_version != based_state_version
                or state.canonical_transcript_version != based_transcript_version
                or state.derived_transcript_version != state.canonical_transcript_version
                or self.store.is_deleted(binding.call_id)
            )
            if stale:
                self._invalidate_decision(state, decision, "generation became stale")
                self.traces.record(
                    call_id=binding.call_id,
                    correlation_id=auth.correlation_id,
                    state_version=state.state_version,
                    stage="commercial_publication",
                    status="INVALIDATED",
                    input_ref=decision_id,
                )
                return self._view_unlocked(state)
            validation = self.validator.validate(
                explanation,
                outcome=outcome,
                product_id=product.product_id if product else None,
                expected_fee=product.monthly_fee if product else None,
                expected_currency=product.currency if product else None,
                evidence_refs=evidence_refs,
                required_guidance_id=guidance.guidance_id if guidance and outcome in {"RECOMMEND", "SUPPRESS"} else None,
            )
            if not validation.valid:
                self._fail_decision(state, decision, validation.reason or "validation failed")
                return self._view_unlocked(state)
            decision.business_outcome = outcome
            decision.dependencies = dependencies
            decision.product_id = product.product_id if product and outcome == "RECOMMEND" else None
            decision.generated_text = explanation.text
            decision.structured_facts = dict(explanation.structured_facts)
            if outcome != "RECOMMEND":
                decision.structured_facts["propensity_score"] = None
            decision.evidence_refs = evidence_refs
            decision.expires_at = self._decision_expiry(dependencies, self.clock.now())
            decision.delivery_state = "VALIDATED"
            decision.delivery_state = "PUBLISH_COMMITTED"
            state.pending_decision_ids.discard(decision_id)
            state.published_decision_ids.add(decision_id)
            state.ui_seq += 1
            decision.publication_seq = state.ui_seq
            state.last_updated_at = self.clock.now()
            self.traces.record(
                call_id=binding.call_id,
                correlation_id=auth.correlation_id,
                state_version=state.state_version,
                stage="commercial_publication",
                status="SUCCEEDED",
                input_ref=decision_id,
                output_ref=outcome,
                model_version=getattr(explanation, "model_version", None),
                error_code=llm_error,
            )
            return self._view_unlocked(state)

    def _dependencies(
        self,
        complaint,
        eligibility: EligibilityResult | None,
        propensity: PropensityResult | None,
        product: ProductFacts | None,
        guidance: GuidanceResult | None,
        outcome: str,
    ) -> DecisionDependencies:
        return DecisionDependencies(
            complaint=self._complaint_ref(complaint),
            eligibility=self._eligibility_ref(eligibility) if outcome in {"RECOMMEND", "NO_ELIGIBLE_OPTION"} else None,
            propensity=self._propensity_ref(propensity) if outcome == "RECOMMEND" else None,
            product_facts=self._product_ref(product) if outcome == "RECOMMEND" else None,
            guidance=self._guidance_ref(guidance) if guidance else None,
        )

    def _complaint_ref(self, complaint) -> DependencyRef:
        return DependencyRef("complaint", f"complaint-{complaint.version}", str(complaint.version), complaint.as_of, complaint.expires_at)

    @staticmethod
    def _eligibility_ref(result: EligibilityResult | None) -> DependencyRef | None:
        return None if result is None else DependencyRef("eligibility", result.snapshot_id, result.version, result.as_of, result.expires_at)

    @staticmethod
    def _propensity_ref(result: PropensityResult | None) -> DependencyRef | None:
        return None if result is None else DependencyRef("propensity", result.snapshot_id, result.model_version, result.as_of, result.expires_at)

    @staticmethod
    def _product_ref(result: ProductFacts | None) -> DependencyRef | None:
        return None if result is None else DependencyRef("product_facts", result.snapshot_id, result.version, result.as_of, result.expires_at)

    @staticmethod
    def _guidance_ref(result: GuidanceResult | None) -> DependencyRef | None:
        return None if result is None else DependencyRef("guidance", result.snapshot_id, result.version, result.as_of, result.expires_at)

    def _decision_expiry(self, dependencies: DecisionDependencies, now: datetime) -> datetime:
        expiries = [now + self.DECISION_TTL]
        for ref in (dependencies.complaint, dependencies.eligibility, dependencies.propensity, dependencies.product_facts, dependencies.guidance):
            if ref:
                expiries.append(ref.expires_at)
        return min(expiries)

    async def mark_server_published(self, auth: AuthContext, call_id: str, decision_id: str) -> dict:
        binding = self._check(auth, call_id, "SUBSCRIBE_CALL")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="SUBSCRIBE_CALL", binding=binding)
            state = self._state(call_id)
            decision = state.decisions[decision_id]
            decision.transport_attempts += 1
            if decision.delivery_state == "PUBLISH_COMMITTED":
                decision.delivery_state = "SERVER_PUBLISHED"
            # A callback after withdrawal is retained as an attempt only.
            return self._view_unlocked(state)

    async def acknowledge(self, auth: AuthContext, call_id: str, decision_id: str) -> dict:
        binding = self._check(auth, call_id, "SUBSCRIBE_CALL")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="SUBSCRIBE_CALL", binding=binding)
            state = self._state(call_id)
            decision = state.decisions[decision_id]
            if decision.delivery_state in {"PUBLISH_COMMITTED", "SERVER_PUBLISHED"}:
                decision.delivery_state = "UI_ACKNOWLEDGED"
                state.ui_seq += 1
            return self._view_unlocked(state)

    async def end_call(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "END_CALL")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="END_CALL", binding=binding)
            state = self._state(call_id)
            if state.status == "DELETED":
                raise PlatformError("deleted call")
            state.status = "ENDED"
            state.state_version += 1
            self._invalidate_active_decisions(state, "call ended")
            self.traces.record(
                call_id=call_id,
                correlation_id=auth.correlation_id,
                state_version=state.state_version,
                stage="call_ended",
                status="SUCCEEDED",
            )
            return self._view_unlocked(state)

    async def post_call(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "RUN_POSTCALL")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="RUN_POSTCALL", binding=binding)
            state = self._state(call_id)
            if state.status == "DELETED" or self.store.is_deleted(call_id):
                raise PlatformError("deleted call")
            if state.status not in {"ENDED", "TRANSFERRED"}:
                raise PlatformError("call must be ended before post-call processing")
            snapshot = state.canonical_snapshot()
            customer = state.customer_context
            sentiment = state.sentiment
            correlation_id = auth.correlation_id
        # Computation is deliberately outside the call lock.
        record = InteractionRecord(
            interaction_id=f"interaction-{call_id}-v{snapshot.transcript_version}-e1",
            call_id=call_id,
            customer_id=binding.customer_id,
            transcript_version=snapshot.transcript_version,
            enrichment_version=1,
            transcript_snapshot_id=f"snapshot-{call_id}-v{snapshot.transcript_version}",
            content_hash=snapshot.content_hash,
            summary=self._summary(snapshot),
            overall_sentiment=sentiment.overall_label,
            aspect_sentiment={name: aspect.label for name, aspect in sentiment.aspects.items()},
            themes=detect_themes(snapshot.segments),
            evidence_refs=tuple(segment.segment_id for segment in snapshot.segments),
            created_at=self.clock.now(),
        )
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="RUN_POSTCALL", binding=binding)
            state = self._state(call_id)
            if state.status == "DELETED" or self.store.is_deleted(call_id):
                raise PlatformError("deleted call blocks final write")
            if state.canonical_transcript_version != snapshot.transcript_version:
                raise ConflictError("transcript changed while post-call processing was running")
            saved, inserted = self.store.write_interaction(record)
            self.traces.record(
                call_id=call_id,
                correlation_id=correlation_id,
                state_version=state.state_version,
                stage="post_call_enrichment",
                status="SUCCEEDED",
                input_ref=record.transcript_snapshot_id,
                output_ref=record.interaction_id,
            )
            return {"record": self._record_dict(saved), "inserted": inserted, "current": self.store.current_interaction(call_id)}

    async def delete_derived(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "DELETE_DERIVED")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="DELETE_DERIVED", binding=binding)
            state = self._state(call_id)
            state.status = "DELETED"
            state.state_version += 1
            self._invalidate_active_decisions(state, "derived data deleted")
            self.store.delete_derived(call_id, binding.customer_id, str(uuid4()), self.clock.now())
            self.traces.record(
                call_id=call_id,
                correlation_id=auth.correlation_id,
                state_version=state.state_version,
                stage="derived_data_deleted",
                status="SUCCEEDED",
            )
            return self._view_unlocked(state)

    async def get_view(self, auth: AuthContext, call_id: str) -> dict:
        binding = self._check(auth, call_id, "READ_CALL")
        async with self._lock_for(call_id):
            self.registry.check(auth, permission="READ_CALL", binding=binding)
            state = self._state(call_id)
            self._expire_decisions(state)
            return self._view_unlocked(state)

    async def get_traces(self, auth: AuthContext, call_id: str) -> list[dict]:
        self._check(auth, call_id, "READ_CALL")
        return self.store.traces(call_id)

    def get_history(self, auth: AuthContext, customer_id: str) -> list[dict]:
        current = self.registry.get(auth.principal_id)
        if current.authz_version != auth.authz_version:
            raise AuthorizationError("authorization context is stale")
        if "READ_CALL" not in current.permissions or customer_id not in current.allowed_customer_ids:
            raise AuthorizationError("history access denied")
        return self.store.history(customer_id)

    def _expire_decisions(self, state: CallState) -> None:
        now = self.clock.now()
        for decision in state.decisions.values():
            if decision.delivery_state in VISIBLE_DELIVERY_STATES and decision.expires_at <= now:
                decision.delivery_state = "EXPIRED"
                state.published_decision_ids.discard(decision.decision_id)
                state.ui_seq += 1

    def _invalidate_transcript_decisions(self, state: CallState, reason: str) -> None:
        self._invalidate_active_decisions(state, reason, transcript_only=True)

    def _invalidate_active_decisions(self, state: CallState, reason: str, transcript_only: bool = False) -> None:
        changed_visible = False
        for decision in state.decisions.values():
            if decision.delivery_state in TERMINAL_DELIVERY_STATES:
                continue
            if decision.delivery_state in VISIBLE_DELIVERY_STATES:
                changed_visible = True
            decision.delivery_state = "WITHDRAWN" if decision.delivery_state in VISIBLE_DELIVERY_STATES else "INVALIDATED"
            decision.invalidation_reason = reason
            state.pending_decision_ids.discard(decision.decision_id)
            state.published_decision_ids.discard(decision.decision_id)
        if changed_visible:
            state.ui_seq += 1

    def _invalidate_decision(self, state: CallState, decision: Decision, reason: str) -> None:
        if decision.delivery_state in TERMINAL_DELIVERY_STATES:
            return
        was_visible = decision.delivery_state in VISIBLE_DELIVERY_STATES
        decision.delivery_state = "WITHDRAWN" if was_visible else "INVALIDATED"
        decision.invalidation_reason = reason
        state.pending_decision_ids.discard(decision.decision_id)
        state.published_decision_ids.discard(decision.decision_id)
        if was_visible:
            state.ui_seq += 1

    def _fail_decision(self, state: CallState, decision: Decision, reason: str) -> None:
        decision.delivery_state = "FAILED"
        decision.invalidation_reason = reason
        state.pending_decision_ids.discard(decision.decision_id)

    @staticmethod
    def _summary(snapshot: CanonicalTranscriptSnapshot) -> str:
        customer_text = [s.text for s in snapshot.segments if s.speaker == "CUSTOMER"]
        return " ".join(customer_text)[:500] or "No customer transcript was available."

    def _view_unlocked(self, state: CallState) -> dict:
        visible = [
            self._decision_dict(decision)
            for decision in state.decisions.values()
            if is_visible(decision)
        ]
        return {
            "call": {
                "call_id": state.call_id,
                "customer_id": state.customer_id,
                "status": state.status,
                "state_version": state.state_version,
                "ui_seq": state.ui_seq,
                "canonical_transcript_version": state.canonical_transcript_version,
                "derived_transcript_version": state.derived_transcript_version,
                "derivation_status": state.derivation_status,
            },
            "customer": self._customer_dict(state.customer_context),
            "transcript": [self._segment_dict(s) for s in state.canonical_snapshot().segments],
            "sentiment": {
                "overall_label": state.sentiment.overall_label,
                "overall_score": state.sentiment.overall_score,
                "as_of_transcript_version": state.sentiment.as_of_transcript_version,
                "aspects": {
                    name: {
                        "label": aspect.label,
                        "score": aspect.score,
                        "evidence_segment_ids": list(aspect.evidence_segment_ids),
                    }
                    for name, aspect in state.sentiment.aspects.items()
                },
            },
            "complaint": self._complaint_dict(state.complaint),
            "complaint_signal": {
                "active": state.complaint_signal.active,
                "evidence_segment_ids": list(state.complaint_signal.evidence_segment_ids),
                "evidence_transcript_versions": list(state.complaint_signal.evidence_transcript_versions),
            },
            "assistance": {
                "ui_seq": state.ui_seq,
                "decisions": visible,
            },
            "pending_decision_ids": sorted(state.pending_decision_ids),
        }

    @staticmethod
    def _customer_dict(customer: CustomerContext | None) -> dict | None:
        if customer is None:
            return None
        return {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "segment": customer.segment,
            "language": customer.language,
            "tenure_months": customer.tenure_months,
        }

    @staticmethod
    def _segment_dict(segment: TranscriptSegment) -> dict:
        return {
            "segment_id": segment.segment_id,
            "revision": segment.revision,
            "is_final": segment.is_final,
            "speaker": segment.speaker,
            "text": segment.text,
            "language": segment.language,
            "source_timestamp": segment.source_timestamp.isoformat(),
            "payload_hash": segment.payload_hash,
        }

    def _decision_dict(self, decision: Decision) -> dict:
        return {
            "decision_id": decision.decision_id,
            "kind": decision.kind,
            "business_outcome": decision.business_outcome,
            "delivery_state": decision.delivery_state,
            "based_on_state_version": decision.based_on_state_version,
            "based_on_authz_version": decision.based_on_authz_version,
            "based_on_transcript_version": decision.based_on_transcript_version,
            "expires_at": decision.expires_at.isoformat(),
            "publication_seq": decision.publication_seq,
            "product_id": decision.product_id,
            "generated_text": decision.generated_text,
            "structured_facts": decision.structured_facts,
            "evidence_refs": decision.evidence_refs,
            "delivery_attempts": decision.transport_attempts,
        }

    @staticmethod
    def _complaint_dict(complaint) -> dict:
        return {
            "status": complaint.status,
            "source": complaint.source,
            "version": complaint.version,
            "as_of": complaint.as_of.isoformat(),
            "expires_at": complaint.expires_at.isoformat(),
            "resolved_through_transcript_version": complaint.resolved_through_transcript_version,
        }

    @staticmethod
    def _record_dict(record: InteractionRecord) -> dict:
        return {
            "interaction_id": record.interaction_id,
            "call_id": record.call_id,
            "customer_id": record.customer_id,
            "transcript_version": record.transcript_version,
            "enrichment_version": record.enrichment_version,
            "transcript_snapshot_id": record.transcript_snapshot_id,
            "content_hash": record.content_hash,
            "summary": record.summary,
            "overall_sentiment": record.overall_sentiment,
            "aspect_sentiment": record.aspect_sentiment,
            "themes": list(record.themes),
            "evidence_refs": list(record.evidence_refs),
            "created_at": record.created_at.isoformat(),
        }
