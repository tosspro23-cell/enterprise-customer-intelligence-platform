from __future__ import annotations

import asyncio
from datetime import datetime

from backend.domain.models import SentimentAspect, SentimentState, TranscriptSegment


class TextAspectSentimentAdapter:
    """Small deterministic adapter for local evidence and repeatable race tests."""

    def __init__(self, *, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail

    async def analyze(self, segments: tuple[TranscriptSegment, ...], transcript_version: int) -> SentimentState:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("sentiment adapter failure")
        aspect_evidence: dict[str, list[str]] = {"fees": [], "service": []}
        aspect_scores: dict[str, float] = {"fees": 0.0, "service": 0.0}
        positive_terms = ("good", "helpful", "great", "thank", "satisfied")
        negative_terms = ("bad", "terrible", "unfair", "expensive", "hate", "problem", "complaint")
        for segment in segments:
            text = segment.text.lower()
            if any(term in text for term in ("fee", "fees", "monthly charge", "charged")):
                aspect_evidence["fees"].append(segment.segment_id)
                aspect_scores["fees"] += self._polarity(text, positive_terms, negative_terms)
            if any(term in text for term in ("help", "support", "service", "agent")):
                aspect_evidence["service"].append(segment.segment_id)
                aspect_scores["service"] += self._polarity(text, positive_terms, negative_terms)
        aspects: dict[str, SentimentAspect] = {}
        for name, evidence in aspect_evidence.items():
            if not evidence:
                continue
            score = max(-1.0, min(1.0, aspect_scores[name] / len(evidence)))
            aspects[name] = SentimentAspect(
                aspect=name,
                label=self._label(score),
                score=score,
                evidence_segment_ids=tuple(evidence),
            )
        all_scores = [aspect.score for aspect in aspects.values()]
        overall = sum(all_scores) / len(all_scores) if all_scores else 0.0
        return SentimentState(
            overall_label=self._label(overall),
            overall_score=overall,
            aspects=aspects,
            model_group="deterministic-en-v1",
            as_of_transcript_version=transcript_version,
        )

    @staticmethod
    def _polarity(text: str, positive: tuple[str, ...], negative: tuple[str, ...]) -> float:
        return float(sum(term in text for term in positive) - sum(term in text for term in negative))

    @staticmethod
    def _label(score: float) -> str:
        if score >= 0.25:
            return "POSITIVE"
        if score <= -0.25:
            return "NEGATIVE"
        return "NEUTRAL"
