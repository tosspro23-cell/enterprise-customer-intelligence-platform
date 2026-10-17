from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from backend.adapters.llm.base import ExplanationResult


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None = None


class ExplanationValidator:
    """Reject explanations that add facts outside the approved context.

    The validator is intentionally conservative. It does not try to prove
    that every sentence is true, but it does reject numeric or currency claims
    that are not the approved fee and language that promises unsupported
    financial outcomes. Structured facts remain authoritative; prose cannot
    expand them.
    """

    _NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?(?![A-Za-z])")
    _CURRENCY_RE = re.compile(r"(?<![A-Za-z])(?:EUR|USD|GBP|€|\$|£)(?![A-Za-z])", re.IGNORECASE)
    _UNSUPPORTED_FINANCIAL_CLAIM_RE = re.compile(
        r"\bguarantee(?:d)?\s+(?:return|profit|yield|earnings?|savings?)\b"
        r"|\b(?:profit|yield|cashback)\b"
        r"|\b(?:interest|interests?)\s+(?:rate|income|payment)\b"
        r"|\bearn(?:s|ing)?\s+(?:interest|profit|yield)\b",
        re.IGNORECASE,
    )
    _CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}

    @classmethod
    def _numeric_claims(cls, text: str) -> list[Decimal]:
        claims: list[Decimal] = []
        for match in cls._NUMBER_RE.finditer(text):
            try:
                claims.append(Decimal(match.group(0).replace(",", ".")))
            except InvalidOperation:
                # The regex is deliberately narrow, but invalid values remain
                # an unapproved claim rather than being silently ignored.
                claims.append(Decimal("NaN"))
        return claims

    @classmethod
    def _currency_claims(cls, text: str) -> list[str]:
        return [
            cls._CURRENCY_SYMBOLS.get(token, token.upper())
            for token in cls._CURRENCY_RE.findall(text)
        ]

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
        numeric_claims = self._numeric_claims(result.text)
        approved_fee = Decimal(str(expected_fee)) if expected_fee is not None else None
        if any(
            approved_fee is None or claim.is_nan() or claim != approved_fee
            for claim in numeric_claims
        ):
            return ValidationResult(False, "explanation contains an unapproved numeric claim")
        currency_claims = self._currency_claims(result.text)
        if any(
            expected_currency is None or currency != expected_currency.upper()
            for currency in currency_claims
        ):
            return ValidationResult(False, "explanation contains an unapproved currency claim")
        if self._UNSUPPORTED_FINANCIAL_CLAIM_RE.search(result.text):
            return ValidationResult(False, "explanation contains an unsupported financial claim")
        return ValidationResult(True)
