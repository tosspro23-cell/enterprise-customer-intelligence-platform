from __future__ import annotations

import pytest

from backend.adapters.persistence.sqlite import SQLiteStore
from backend.domain.auth import AuthorizationRegistry
from backend.orchestration.realtime import Platform


@pytest.fixture
def platform(tmp_path):
    registry = AuthorizationRegistry()
    agent = registry.register(
        "agent",
        permissions={"READ_CALL", "SUBSCRIBE_CALL", "INGEST_TRANSCRIPT", "UPDATE_COMPLAINT", "END_CALL", "RUN_POSTCALL", "DELETE_DERIVED"},
        allowed_customer_ids={"C001", "C002"},
    )
    reader = registry.register(
        "reader",
        permissions={"READ_CALL", "SUBSCRIBE_CALL"},
        allowed_customer_ids={"C001"},
    )
    store = SQLiteStore(tmp_path / "platform.db")
    instance = Platform(store=store, registry=registry)
    instance.test_agent = agent
    instance.test_reader = reader
    yield instance
    instance.close()
