from __future__ import annotations

from .base import ExplanationAdapter, ExplanationRequest, ExplanationResult


class DeterministicExplanationAdapter(ExplanationAdapter):
    def __init__(self, *, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail

    async def explain(self, request: ExplanationRequest) -> ExplanationResult:
        import asyncio

        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            from .base import LLMUnavailable

            raise LLMUnavailable("explanation adapter unavailable")
        if request.outcome == "SUPPRESS":
            text = (
                f"Acknowledge {request.customer_name}'s concern about monthly fees, "
                "clarify the impact, and resolve the issue before discussing another product."
            )
        elif request.outcome == "UNAVAILABLE":
            text = "The recommendation service is temporarily unavailable; continue with the customer's request and do not present an offer."
        elif request.outcome == "NO_ELIGIBLE_OPTION":
            text = "No eligible option is available for this customer at the moment; explain the next supported step without presenting an offer."
        else:
            text = (
                f"Explain how {request.product_name} could support the customer's savings goal, "
                "confirm the customer's interest, and disclose the approved fee before any action."
            )
        facts = {
            "product_id": request.product_id,
            "product_name": request.product_name,
            "monthly_fee": request.product_fee,
            "currency": request.currency,
            "benefits": list(request.product_benefits),
            "propensity_score": request.propensity_score,
        }
        return ExplanationResult(
            text=text,
            model_name="deterministic-explanation",
            model_version="fake-v1",
            structured_facts=facts,
        )
