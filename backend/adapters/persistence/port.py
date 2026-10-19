from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from backend.domain.models import InteractionRecord


class PersistenceStore(Protocol):
    """Durable contract shared by the reference and PostgreSQL adapters."""

    def close(self) -> None: ...

    def write_trace(self, trace: dict[str, Any]) -> None: ...

    def is_deleted(self, call_id: str) -> bool: ...

    def write_interaction(self, record: InteractionRecord) -> tuple[InteractionRecord, bool]: ...

    def current_interaction(self, call_id: str) -> dict[str, Any] | None: ...

    def history(self, customer_id: str) -> list[dict[str, Any]]: ...

    def delete_derived(
        self,
        call_id: str,
        customer_id: str,
        deletion_epoch: str,
        deleted_at: datetime,
    ) -> None: ...

    def traces(self, call_id: str) -> list[dict[str, Any]]: ...
