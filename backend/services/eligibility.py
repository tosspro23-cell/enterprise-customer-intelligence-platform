from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.adapters.enterprise.mock_customer_api import CustomerRecord


@dataclass(frozen=True)
class EligibilityResult:
    customer_id: str
    eligible_product_ids: tuple[str, ...]
    snapshot_id: str
    version: str
    as_of: datetime
    expires_at: datetime
    reason: str


class DeterministicEligibilityService:
    def __init__(self, *, no_eligible: bool = False) -> None:
        self.no_eligible = no_eligible

    def evaluate(self, customer: CustomerRecord, now: datetime) -> EligibilityResult:
        eligible = () if self.no_eligible else (("SAVINGS_PLUS",) if customer.segment == "PERSONAL" else ())
        return EligibilityResult(
            customer_id=customer.customer_id,
            eligible_product_ids=eligible,
            snapshot_id=f"eligibility-{customer.customer_id}-{int(now.timestamp() * 1000)}",
            version="eligibility-v1",
            as_of=now,
            expires_at=now + timedelta(seconds=10),
            reason="eligible" if eligible else "no eligible product",
        )
