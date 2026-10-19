from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from backend.adapters.llm.base import ExplanationRequest
from backend.adapters.llm.bedrock import BedrockExplanationAdapter
from backend.services.explanation_validator import ExplanationValidator


DEFAULT_MODELS = {
    "amazon-nova-micro": "us.amazon.nova-micro-v1:0",
    "anthropic-claude-haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "meta-llama-3-3": "us.meta.llama3-3-70b-instruct-v1:0",
}


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    request: ExplanationRequest
    expected_outcome: str
    required_terms: tuple[str, ...]


def benchmark_cases() -> tuple[BenchmarkCase, ...]:
    return (
        BenchmarkCase(
            name="complaint_suppression",
            request=ExplanationRequest(
                outcome="SUPPRESS",
                customer_name="Sarah Chen",
                topic="fees",
                product_id=None,
                product_name=None,
                product_fee=None,
                currency=None,
                product_benefits=(),
                guidance_text=(
                    "Acknowledge the fee concern, clarify the impact, and resolve "
                    "the issue before discussing another product."
                ),
                guidance_id="GUIDE-FEE-001",
                propensity_score=None,
                complaint_status="OPEN",
            ),
            expected_outcome="SUPPRESS",
            required_terms=("fee", "concern", "issue"),
        ),
        BenchmarkCase(
            name="approved_recommendation",
            request=ExplanationRequest(
                outcome="RECOMMEND",
                customer_name="Alex Morgan",
                topic="savings",
                product_id="SAVINGS_PLUS",
                product_name="Savings Plus",
                product_fee=4.99,
                currency="EUR",
                product_benefits=("fee alerts", "automatic savings rules"),
                guidance_text=(
                    "Explain the approved savings option, confirm interest, and "
                    "disclose the approved fee before any action."
                ),
                guidance_id="GUIDE-SAVINGS-001",
                propensity_score=0.91,
                complaint_status="RESOLVED",
            ),
            expected_outcome="RECOMMEND",
            required_terms=("savings", "fee"),
        ),
        BenchmarkCase(
            name="provider_unavailable",
            request=ExplanationRequest(
                outcome="UNAVAILABLE",
                customer_name="Jordan Lee",
                topic="savings",
                product_id=None,
                product_name=None,
                product_fee=None,
                currency=None,
                product_benefits=(),
                guidance_text=(
                    "The recommendation service is temporarily unavailable; "
                    "continue with the customer's request and do not present an offer."
                ),
                guidance_id="GUIDE-SAVINGS-001",
                propensity_score=None,
                complaint_status="RESOLVED",
            ),
            expected_outcome="UNAVAILABLE",
            required_terms=("unavailable", "request"),
        ),
    )


def _validator_result(case: BenchmarkCase, result) -> tuple[bool, str | None]:
    validation = ExplanationValidator().validate(
        result,
        outcome=case.expected_outcome,
        product_id=case.request.product_id,
        expected_fee=case.request.product_fee,
        expected_currency=case.request.currency,
        evidence_refs=[case.request.guidance_id] if case.request.guidance_id else [],
        required_guidance_id=(
            case.request.guidance_id
            if case.expected_outcome in {"RECOMMEND", "SUPPRESS"}
            else None
        ),
    )
    return validation.valid, validation.reason


def _rubric_pass(case: BenchmarkCase, text: str) -> bool:
    normalized = text.casefold()
    return len(text.strip()) >= 20 and all(
        term.casefold() in normalized for term in case.required_terms
    )


def _client(profile: str | None, region: str):
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client(
        "bedrock-runtime",
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )


async def _run_one(
    semaphore: asyncio.Semaphore,
    adapter: BedrockExplanationAdapter,
    case: BenchmarkCase,
    repetition: int,
) -> dict[str, Any]:
    async with semaphore:
        started = time.perf_counter()
        try:
            result = await adapter.explain(case.request)
            validation_passed, validation_reason = _validator_result(case, result)
            text = result.text.strip()
            return {
                "case": case.name,
                "repetition": repetition,
                "status": "success",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "validation_passed": validation_passed,
                "validation_reason": validation_reason,
                "rubric_passed": _rubric_pass(case, text),
                "output_chars": len(text),
                "model_version": result.model_version,
            }
        except Exception as exc:
            return {
                "case": case.name,
                "repetition": repetition,
                "status": "error",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "validation_passed": False,
                "validation_reason": type(exc).__name__,
                "rubric_passed": False,
                "output_chars": 0,
                "error": str(exc)[:300],
            }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, round((len(values) - 1) * percentile))
    return round(values[index], 2)


def _summary(model_name: str, model_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [item for item in results if item["status"] == "success"]
    latencies = [item["latency_ms"] for item in successes]
    validation_count = sum(item["validation_passed"] for item in successes)
    rubric_count = sum(item["rubric_passed"] for item in successes)
    total = len(results)
    return {
        "name": model_name,
        "model_id": model_id,
        "requests": total,
        "successes": len(successes),
        "errors": total - len(successes),
        "success_rate": round(len(successes) / total, 4) if total else 0,
        "validation_pass_rate": round(validation_count / total, 4) if total else 0,
        "rubric_pass_rate": round(rubric_count / total, 4) if total else 0,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 2) if latencies else None,
        },
    }


def _score(summary: dict[str, Any], fastest_p95: float | None) -> float:
    if fastest_p95 is None or summary["latency_ms"]["p95"] is None:
        latency_score = 0
    else:
        latency_score = min(1.0, fastest_p95 / summary["latency_ms"]["p95"])
    return round(
        summary["validation_pass_rate"] * 0.60
        + summary["rubric_pass_rate"] * 0.30
        + latency_score * 0.10,
        4,
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(args.concurrency)
    cases = benchmark_cases()
    summaries: list[dict[str, Any]] = []
    raw_results: dict[str, list[dict[str, Any]]] = {}
    for model_name, model_id in args.models.items():
        adapter = BedrockExplanationAdapter(
            client=_client(args.profile, args.region),
            model_id=model_id,
        )
        tasks = [
            _run_one(semaphore, adapter, case, repetition)
            for repetition in range(1, args.repetitions + 1)
            for case in cases
        ]
        results = await asyncio.gather(*tasks)
        raw_results[model_name] = results
        summaries.append(_summary(model_name, model_id, results))

    valid_summaries = [
        summary
        for summary in summaries
        if summary["success_rate"] == 1 and summary["validation_pass_rate"] == 1
    ]
    fastest_p95 = min(
        (
            summary["latency_ms"]["p95"]
            for summary in valid_summaries
            if summary["latency_ms"]["p95"] is not None
        ),
        default=None,
    )
    for summary in summaries:
        summary["composite_score"] = _score(summary, fastest_p95)
    recommended = max(valid_summaries, key=lambda item: item["composite_score"], default=None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": args.region,
        "profile": args.profile or os.getenv("AWS_PROFILE") or "default",
        "repetitions_per_case": args.repetitions,
        "concurrency": args.concurrency,
        "cases": [case.name for case in cases],
        "selection_rule": {
            "hard_gate": "100% success and 100% explanation validation pass rate",
            "score": "validation 60% + deterministic rubric 30% + relative p95 latency 10%",
        },
        "recommended_default": recommended,
        "summaries": summaries,
        "results": raw_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark bounded Bedrock explanation models.")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--repetitions", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--model",
        action="append",
        metavar="NAME=MODEL_ID",
        help="Override the default candidate; may be repeated.",
    )
    args = parser.parse_args()
    args.models = dict(DEFAULT_MODELS)
    if args.model:
        args.models = {}
        for entry in args.model:
            name, separator, model_id = entry.partition("=")
            if not separator or not name or not model_id:
                parser.error("--model must use NAME=MODEL_ID")
            args.models[name] = model_id
    if len(args.models) < 3:
        parser.error("at least three models are required for comparison")
    if args.repetitions < 1 or args.concurrency < 1:
        parser.error("repetitions and concurrency must be positive")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    report = asyncio.run(run(arguments))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summaries"], indent=2))
    if report["recommended_default"]:
        print("recommended_default:", report["recommended_default"]["model_id"])
