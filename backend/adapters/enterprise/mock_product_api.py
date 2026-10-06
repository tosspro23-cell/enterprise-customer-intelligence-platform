from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ProductFacts:
    product_id: str
    name: str
    monthly_fee: float
    currency: str
    benefits: tuple[str, ...]
    snapshot_id: str
    version: str
    as_of: datetime
    expires_at: datetime


class MockProductAPI:
    def get(self, product_id: str, now: datetime) -> ProductFacts:
        if product_id != "SAVINGS_PLUS":
            raise LookupError(f"unknown product: {product_id}")
        return ProductFacts(
            product_id=product_id,
            name="Savings Plus",
            monthly_fee=4.99,
            currency="EUR",
            benefits=("fee alerts", "automatic savings rules"),
            snapshot_id=f"product-{product_id}-{int(now.timestamp())}",
            version="2026.10",
            as_of=now,
            expires_at=now + timedelta(seconds=60),
        )
