from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from .base import ExplanationAdapter, ExplanationRequest, ExplanationResult, LLMUnavailable


DEFAULT_BEDROCK_MODEL_ID = "us.amazon.nova-micro-v1:0"


class BedrockExplanationAdapter(ExplanationAdapter):
    """Bounded explanation adapter using Amazon Bedrock Runtime Converse."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        model_id: str | None = None,
        region_name: str | None = None,
        max_tokens: int = 256,
    ) -> None:
        self.model_id = model_id or os.getenv("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID)
        self.max_tokens = max_tokens
        if not self.model_id:
            raise LLMUnavailable("BEDROCK_MODEL_ID is not configured")
        if client is not None:
            self.client = client
            return
        try:
            import boto3
            from botocore.config import Config

            self.client = boto3.client(
                "bedrock-runtime",
                region_name=region_name or os.getenv("AWS_REGION"),
                config=Config(
                    connect_timeout=5,
                    read_timeout=20,
                    retries={"max_attempts": 1, "mode": "standard"},
                ),
            )
        except ImportError as exc:  # pragma: no cover - packaging boundary
            raise LLMUnavailable("boto3 is required for the Bedrock adapter") from exc
        except Exception as exc:  # pragma: no cover - requires AWS configuration
            raise LLMUnavailable(f"Bedrock client is unavailable: {exc}") from exc

    @staticmethod
    def _prompt(request: ExplanationRequest) -> tuple[str, str]:
        system = (
            "You produce a short customer-service handling suggestion. "
            "Use only the approved facts in the user message. Do not invent "
            "or reinterpret product, fee, currency, eligibility, score, or "
            "financial-return claims. Return only the suggestion text."
        )
        facts = {
            "outcome": request.outcome,
            "customer_name": request.customer_name,
            "topic": request.topic,
            "approved_guidance": request.guidance_text,
            "approved_facts": {
                "product_id": request.product_id,
                "product_name": request.product_name,
                "monthly_fee": request.product_fee,
                "currency": request.currency,
                "benefits": request.product_benefits,
            },
        }
        return system, json.dumps(facts, ensure_ascii=False)

    def _converse(self, system: str, user_message: str) -> str:
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"temperature": 0, "maxTokens": self.max_tokens},
        )
        try:
            return response["output"]["message"]["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("Bedrock returned an invalid text response") from exc

    async def explain(self, request: ExplanationRequest) -> ExplanationResult:
        system, user_message = self._prompt(request)
        try:
            text = await asyncio.to_thread(self._converse, system, user_message)
        except LLMUnavailable:
            raise
        except Exception as exc:  # pragma: no cover - requires external service
            raise LLMUnavailable(str(exc)) from exc
        return ExplanationResult(
            text=text,
            model_name="amazon-bedrock",
            model_version=self.model_id,
            structured_facts={
                "product_id": request.product_id,
                "product_name": request.product_name,
                "monthly_fee": request.product_fee,
                "currency": request.currency,
                "benefits": list(request.product_benefits),
                "propensity_score": request.propensity_score,
            },
        )
