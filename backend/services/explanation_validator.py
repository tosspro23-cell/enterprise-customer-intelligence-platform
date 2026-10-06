from __future__ import annotations

from dataclasses import dataclass

from backend.adapters.llm.base import ExplanationResult


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None = None


class ExplanationValidator:
    """Deterministic structural checks; it does not claim arbitrary prose is factual."""

    def validate(
        self,
        result: ExplanationResult,
        *,
        outcome: str,
        product_id: str | None,
        expected_fee: float | None,
        expected_currency: str | None,
        evidence_refs: list[str],
        required_guidance_id: str | None,
    ) -> ValidationResult:
        facts = result.structured_facts
        if outcome == "RECOMMEND":
            if not product_id or facts.get("product_id") != product_id:
                return ValidationResult(False, "protected product identity mismatch")
            if expected_fee is None or facts.get("monthly_fee") != expected_fee:
                return ValidationResult(False, "protected fee mismatch")
            if facts.get("currency") != expected_currency:
                return ValidationResult(False, "protected currency mismatch")
        else:
            if facts.get("propensity_score") is not None:
                return ValidationResult(False, "non-recommendation explanation exposed a score")
        if required_guidance_id is not None and required_guidance_id not in evidence_refs:
            return ValidationResult(False, "required guidance citation is missing")
        if not evidence_refs and outcome in {"SUPPRESS", "RECOMMEND"}:
            return ValidationResult(False, "evidence-required outcome has no citations")
        if not result.text.strip():
            return ValidationResult(False, "empty explanation")
        return ValidationResult(True)
