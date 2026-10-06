from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta


class PropensityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PropensityResult:
    customer_id: str
    product_id: str
    score: float
    model_name: str
    model_version: str
    snapshot_id: str
    as_of: datetime
    expires_at: datetime


class MockPropensityService:
    """Fixed feature-contract mock: score predicts; it never authorizes a sale."""

    def __init__(self, *, score: float = 0.91, delay: float = 0.0, fail: bool = False) -> None:
        self.score = score
        self.delay = delay
        self.fail = fail

    async def score_customer(self, customer_id: str, product_id: str, now: datetime) -> PropensityResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise PropensityUnavailable("propensity service timeout")
        return PropensityResult(
            customer_id=customer_id,
            product_id=product_id,
            score=self.score,
            model_name="cross-sell-propensity",
            model_version="mock-v1",
            snapshot_id=f"propensity-{customer_id}-{int(now.timestamp() * 1000)}",
            as_of=now,
            expires_at=now + timedelta(seconds=10),
        )
