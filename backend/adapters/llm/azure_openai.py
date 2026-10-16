from __future__ import annotations

import json
import os
from urllib import request as urlrequest

from .base import ExplanationAdapter, ExplanationRequest, ExplanationResult, LLMUnavailable


class AzureOpenAIExplanationAdapter(ExplanationAdapter):
    """Optional adapter; the model receives bounded facts and returns only explanation text."""

    def __init__(self, endpoint: str | None = None, api_key: str | None = None, deployment: str | None = None, api_version: str | None = None) -> None:
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY", "")
        self.deployment = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

    async def explain(self, request: ExplanationRequest) -> ExplanationResult:
        if not self.endpoint or not self.api_key or not self.deployment:
            raise LLMUnavailable("Azure OpenAI adapter is not configured")
        prompt = {
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
            "rule": "Do not invent product, price, eligibility, or score facts. Return a short handling suggestion.",
        }
        body = json.dumps({
            "messages": [
                {"role": "system", "content": "You produce bounded customer-service guidance."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
            "temperature": 0,
        }).encode()
        url = f"{self.endpoint.rstrip('/')}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
        req = urlrequest.Request(url, data=body, headers={"api-key": self.api_key, "Content-Type": "application/json"})
        try:
            with urlrequest.urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode())
        except Exception as exc:  # pragma: no cover - requires external service
            raise LLMUnavailable(str(exc)) from exc
        text = payload["choices"][0]["message"]["content"]
        return ExplanationResult(
            text=text,
            model_name="azure-openai",
            model_version=self.deployment,
            structured_facts={
                "product_id": request.product_id,
                "product_name": request.product_name,
                "monthly_fee": request.product_fee,
                "currency": request.currency,
                "benefits": list(request.product_benefits),
                "propensity_score": request.propensity_score,
            },
        )
