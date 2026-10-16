from __future__ import annotations

import asyncio

import pytest

from backend.adapters.llm.base import ExplanationRequest, ExplanationResult
from backend.adapters.llm.bedrock import BedrockExplanationAdapter
from backend.services.explanation_validator import ExplanationValidator


def _request(*, outcome: str = "RECOMMEND", fee: float | None = 2.99) -> ExplanationRequest:
    return ExplanationRequest(
        outcome=outcome,
        customer_name="Alex Morgan",
        topic="savings",
        product_id="SAVINGS_PLUS" if outcome == "RECOMMEND" else None,
        product_name="Savings Plus" if outcome == "RECOMMEND" else None,
        product_fee=fee,
        currency="EUR" if fee is not None else None,
        product_benefits=("automatic savings rules",) if outcome == "RECOMMEND" else (),
        guidance_text="Use the approved guidance.",
        guidance_id="GUIDE-SAVINGS-001",
        propensity_score=0.91 if outcome == "RECOMMEND" else None,
        complaint_status="RESOLVED",
    )


def _result(text: str, *, fee: float | None = 2.99) -> ExplanationResult:
    return ExplanationResult(
        text=text,
        model_name="test-model",
        model_version="test-v1",
        structured_facts={
            "product_id": "SAVINGS_PLUS",
            "product_name": "Savings Plus",
            "monthly_fee": fee,
            "currency": "EUR" if fee is not None else None,
            "benefits": ["automatic savings rules"],
            "propensity_score": 0.91,
        },
    )


def _validate(text: str, *, fee: float | None = 2.99):
    return ExplanationValidator().validate(
        _result(text, fee=fee),
        outcome="RECOMMEND" if fee is not None else "SUPPRESS",
        product_id="SAVINGS_PLUS" if fee is not None else None,
        expected_fee=fee,
        expected_currency="EUR" if fee is not None else None,
        evidence_refs=["GUIDE-SAVINGS-001"],
        required_guidance_id="GUIDE-SAVINGS-001",
    )


def test_validator_accepts_approved_fee_and_currency() -> None:
    result = _validate("Discuss Savings Plus and disclose the approved EUR 2.99 monthly fee.")

    assert result.valid is True


@pytest.mark.parametrize(
    "text",
    [
        "Discuss Savings Plus and disclose the approved EUR 999 monthly fee.",
        "Discuss Savings Plus and disclose the approved USD 2.99 monthly fee.",
        "Savings Plus includes a guaranteed return for the customer.",
    ],
)
def test_validator_rejects_unapproved_prose_claims(text: str) -> None:
    result = _validate(text)

    assert result.valid is False


def test_validator_rejects_numeric_claim_when_no_fee_is_approved() -> None:
    result = _validate("Acknowledge the concern and resolve the issue in 2 steps.", fee=None)

    assert result.valid is False


@pytest.mark.asyncio
async def test_bedrock_adapter_offloads_synchronous_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = BedrockExplanationAdapter(client=object(), model_id="test-model")
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(function, *args):
        calls.append((function, args))
        return "Use the approved guidance."

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    result = await adapter.explain(_request())

    assert result.text == "Use the approved guidance."
    assert calls[0][0] == adapter._converse


@pytest.mark.asyncio
async def test_bedrock_adapter_maps_converse_response_to_bounded_facts() -> None:
    class FakeClient:
        def converse(self, **kwargs):
            assert kwargs["modelId"] == "test-model"
            assert kwargs["inferenceConfig"] == {"temperature": 0, "maxTokens": 256}
            return {"output": {"message": {"content": [{"text": "Use the guidance."}]}}}

    adapter = BedrockExplanationAdapter(client=FakeClient(), model_id="test-model")

    result = await adapter.explain(_request())

    assert result.text == "Use the guidance."
    assert result.model_name == "amazon-bedrock"
    assert result.structured_facts["monthly_fee"] == 2.99
