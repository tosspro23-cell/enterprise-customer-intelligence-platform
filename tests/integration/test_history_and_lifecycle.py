from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_server_publish_and_ui_ack_are_distinct_and_monotonic(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    call_id = view["call"]["call_id"]
    await platform.resolve_complaint(auth, call_id)
    view = await platform.request_commercial(auth, call_id)
    decision_id = view["assistance"]["decisions"][0]["decision_id"]
    committed_seq = view["call"]["ui_seq"]
    view = await platform.acknowledge(auth, call_id, decision_id)
    assert view["assistance"]["decisions"][0]["delivery_state"] == "UI_ACKNOWLEDGED"
    assert view["call"]["ui_seq"] > committed_seq
    view = await platform.mark_server_published(auth, call_id, decision_id)
    assert view["assistance"]["decisions"][0]["delivery_state"] == "UI_ACKNOWLEDGED"


@pytest.mark.asyncio
async def test_customer_history_is_scoped_to_authorized_customer(platform):
    auth = platform.test_agent
    view = await platform.start_call(auth, "C001")
    call_id = view["call"]["call_id"]
    await platform.end_call(auth, call_id)
    await platform.post_call(auth, call_id)
    assert len(platform.get_history(auth, "C001")) == 1
    with pytest.raises(PermissionError):
        platform.get_history(platform.test_reader, "C002")
