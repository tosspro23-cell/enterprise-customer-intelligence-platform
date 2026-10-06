from __future__ import annotations

from collections import Counter

from backend.domain.models import TranscriptSegment


KNOWN_THEMES = {
    "fees": ("fee", "fees", "monthly charge", "charged"),
    "savings": ("save", "saving", "savings"),
    "service": ("help", "support", "service", "agent"),
}


def detect_themes(segments: tuple[TranscriptSegment, ...]) -> tuple[str, ...]:
    text = " ".join(s.text.lower() for s in segments)
    found = [theme for theme, terms in KNOWN_THEMES.items() if any(term in text for term in terms)]
    return tuple(sorted(found))


def theme_counts(segments: tuple[TranscriptSegment, ...]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for segment in segments:
        text = segment.text.lower()
        for theme, terms in KNOWN_THEMES.items():
            if any(term in text for term in terms):
                counts[theme] += 1
    return dict(counts)
