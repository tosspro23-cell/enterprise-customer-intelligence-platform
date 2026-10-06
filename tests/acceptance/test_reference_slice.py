from __future__ import annotations

import asyncio

import pytest

from backend.adapters.llm.fake import DeterministicExplanationAdapter
from backend.services.eligibility import DeterministicEligibilityService
from backend.domain.auth import AuthorizationError
from backend.orchestration.realtime import ConflictError, PlatformError


async def _call_with_fee_complaint(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    call_id = view["call"]["call_id"]
    await platform.ingest_segment(
        auth, call_id, segment_id="service", revision=1, is_final=True,
        speaker="CUSTOMER", text="The support team has been very helpful."
    )
    view = await platform.ingest_segment(
        auth, call_id, segment_id="fees", revision=1, is_final=True,
        speaker="CUSTOMER", text="The monthly fee is terrible and unfair."
    )
    return auth, call_id, view


@pytest.mark.asyncio
async def test_complete_demo_has_aspect_grounding_and_idempotent_post_call(platform):
    auth, call_id, view = await _call_with_fee_complaint(platform)
    assert view["sentiment"]["aspects"]["fees"]["label"] == "NEGATIVE"
    assert view["sentiment"]["aspects"]["service"]["label"] == "POSITIVE"
    assert view["complaint"]["status"] == "OPEN"

    suppressed = await platform.request_commercial(auth, call_id)
    decision = suppressed["assistance"]["decisions"][0]
    assert decision["business_outcome"] == "SUPPRESS"
    assert decision["product_id"] is None
    assert "GUIDE-FEE-001" in decision["evidence_refs"]

    await platform.resolve_complaint(auth, call_id)
    recommended = await platform.request_commercial(auth, call_id)
    decision = recommended["assistance"]["decisions"][0]
    assert decision["business_outcome"] == "RECOMMEND"
    assert decision["structured_facts"]["monthly_fee"] == 4.99
    assert decision["structured_facts"]["propensity_score"] == 0.91

    await platform.end_call(auth, call_id)
    first = await platform.post_call(auth, call_id)
    second = await platform.post_call(auth, call_id)
    assert first["inserted"] is True
    assert second["inserted"] is False
    assert first["record"]["transcript_snapshot_id"] == second["record"]["transcript_snapshot_id"]


@pytest.mark.asyncio
async def test_transcript_revision_conflict_and_obsolete_revision_are_safe(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    call_id = view["call"]["call_id"]
    await platform.ingest_segment(auth, call_id, segment_id="s1", revision=2, is_final=True, speaker="CUSTOMER", text="The fee is high.")
    before = await platform.get_view(auth, call_id)
    ignored = await platform.ingest_segment(auth, call_id, segment_id="s1", revision=1, is_final=True, speaker="CUSTOMER", text="old text")
    assert ignored["call"]["canonical_transcript_version"] == before["call"]["canonical_transcript_version"]
    with pytest.raises(ConflictError):
        await platform.ingest_segment(auth, call_id, segment_id="s1", revision=2, is_final=True, speaker="CUSTOMER", text="different payload")


@pytest.mark.asyncio
async def test_read_permission_cannot_ingest(platform):
    view = await platform.start_call(platform.test_agent, "C001")
    with pytest.raises(AuthorizationError):
        await platform.ingest_segment(
            platform.test_reader, view["call"]["call_id"], segment_id="s1", revision=1,
            is_final=True, speaker="CUSTOMER", text="not allowed"
        )


@pytest.mark.asyncio
async def test_stale_generation_is_invalidated_before_old_result_can_publish(platform):
    auth, call_id, _ = await _call_with_fee_complaint(platform)
    await platform.resolve_complaint(auth, call_id)
    platform.llm = DeterministicExplanationAdapter(delay=0.05)
    pending = asyncio.create_task(platform.request_commercial(auth, call_id))
    await asyncio.sleep(0.01)
    changed = await platform.ingest_segment(
        auth, call_id, segment_id="new-complaint", revision=1, is_final=True,
        speaker="CUSTOMER", text="There is another terrible problem with the fee."
    )
    result = await pending
    assert result["assistance"]["decisions"] == []
    assert changed["complaint_signal"]["active"] is True
    state = await platform.get_view(auth, call_id)
    assert state["assistance"]["decisions"] == []
    assert len(state["pending_decision_ids"]) == 0


@pytest.mark.asyncio
async def test_end_call_invalidates_visible_decision_and_late_callback_cannot_restore(platform):
    auth, call_id, _ = await _call_with_fee_complaint(platform)
    await platform.resolve_complaint(auth, call_id)
    view = await platform.request_commercial(auth, call_id)
    decision_id = view["assistance"]["decisions"][0]["decision_id"]
    await platform.end_call(auth, call_id)
    after_end = await platform.get_view(auth, call_id)
    assert after_end["assistance"]["decisions"] == []
    await platform.mark_server_published(auth, call_id, decision_id)
    after_callback = await platform.get_view(auth, call_id)
    assert after_callback["assistance"]["decisions"] == []


@pytest.mark.asyncio
async def test_dependency_expiry_removes_visible_decision_without_new_event(platform):
    from backend.services.clock import FrozenClock

    platform.clock = FrozenClock()
    platform.traces.clock = platform.clock
    auth, call_id, _ = await _call_with_fee_complaint(platform)
    await platform.resolve_complaint(auth, call_id)
    view = await platform.request_commercial(auth, call_id)
    assert view["assistance"]["decisions"]
    platform.clock.advance(seconds=16)
    expired = await platform.get_view(auth, call_id)
    assert expired["assistance"]["decisions"] == []


@pytest.mark.asyncio
async def test_delete_blocks_post_call_and_late_content(platform):
    auth, call_id, _ = await _call_with_fee_complaint(platform)
    await platform.end_call(auth, call_id)
    await platform.delete_derived(auth, call_id)
    with pytest.raises(PlatformError):
        await platform.post_call(auth, call_id)
    assert platform.store.history("C001") == []


@pytest.mark.asyncio
async def test_unavailable_and_no_eligible_are_visible_business_outcomes(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    unavailable_call = view["call"]["call_id"]
    await platform.resolve_complaint(auth, unavailable_call)
    platform.propensity.fail = True
    unavailable = await platform.request_commercial(auth, unavailable_call)
    assert unavailable["assistance"]["decisions"][0]["business_outcome"] == "UNAVAILABLE"
    assert unavailable["assistance"]["decisions"][0]["product_id"] is None

    platform.propensity.fail = False
    platform.eligibility = DeterministicEligibilityService(no_eligible=True)
    second = await platform.start_call(auth, "C001")
    no_option = await platform.resolve_complaint(auth, second["call"]["call_id"])
    no_option = await platform.request_commercial(auth, second["call"]["call_id"])
    assert no_option["assistance"]["decisions"][0]["business_outcome"] == "NO_ELIGIBLE_OPTION"


@pytest.mark.asyncio
async def test_authorization_revocation_invalidates_late_generation(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    call_id = view["call"]["call_id"]
    await platform.resolve_complaint(auth, call_id)
    platform.llm = DeterministicExplanationAdapter(delay=0.05)
    pending = asyncio.create_task(platform.request_commercial(auth, call_id))
    await asyncio.sleep(0.01)
    platform.registry.revoke("agent", "SUBSCRIBE_CALL")
    result = await pending
    assert result["assistance"]["decisions"] == []


@pytest.mark.asyncio
async def test_resolution_coverage_does_not_clear_newer_complaint_evidence(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    call_id = view["call"]["call_id"]
    await platform.ingest_segment(auth, call_id, segment_id="old", revision=1, is_final=True, speaker="CUSTOMER", text="The fee is terrible.")
    await platform.resolve_complaint(auth, call_id)
    resolved = await platform.get_view(auth, call_id)
    assert resolved["complaint_signal"]["active"] is False
    newer = await platform.ingest_segment(auth, call_id, segment_id="new", revision=1, is_final=True, speaker="CUSTOMER", text="The fee is unfair again.")
    assert newer["complaint"]["resolved_through_transcript_version"] == 1
    assert newer["call"]["canonical_transcript_version"] == 2
    assert newer["complaint_signal"]["active"] is True


@pytest.mark.asyncio
async def test_post_call_revised_transcript_creates_new_current_lineage(platform):
    auth, call_id, _ = await _call_with_fee_complaint(platform)
    await platform.end_call(auth, call_id)
    first = await platform.post_call(auth, call_id)
    revised = await platform.ingest_segment(
        auth, call_id, segment_id="fees", revision=2, is_final=True,
        speaker="CUSTOMER", text="The monthly fee is now clear and acceptable."
    )
    assert revised["call"]["status"] == "ENDED"
    second = await platform.post_call(auth, call_id)
    assert second["inserted"] is True
    assert second["record"]["transcript_version"] > first["record"]["transcript_version"]
    assert platform.store.current_interaction(call_id)["transcript_version"] == second["record"]["transcript_version"]
