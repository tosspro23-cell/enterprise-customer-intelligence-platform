from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExplanationRequest:
    outcome: str
    customer_name: str
    topic: str
    product_id: str | None
    product_name: str | None
    product_fee: float | None
    currency: str | None
    product_benefits: tuple[str, ...]
    guidance_text: str | None
    guidance_id: str | None
    propensity_score: float | None
    complaint_status: str


@dataclass(frozen=True)
class ExplanationResult:
    text: str
    model_name: str
    model_version: str
    structured_facts: dict


class LLMUnavailable(RuntimeError):
    pass


class ExplanationAdapter:
    async def explain(self, request: ExplanationRequest) -> ExplanationResult:
        raise NotImplementedError
