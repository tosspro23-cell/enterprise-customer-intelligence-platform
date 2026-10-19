from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class InMemoryRateLimiter:
    """Bounded single-process fixed-window limiter for defense in depth.

    This limiter intentionally does not claim distributed correctness. A
    shared edge or gateway limiter is required before horizontal scaling.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float = 60.0,
        max_keys: int = 10_000,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._windows: dict[str, deque[float]] = {}
        self._last_seen: dict[str, float] = {}
        self._lock = RLock()

    def allow(self, key: str) -> RateLimitDecision:
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            if key not in self._windows and len(self._windows) >= self.max_keys:
                oldest = min(self._last_seen, key=self._last_seen.get)
                self._windows.pop(oldest, None)
                self._last_seen.pop(oldest, None)
            window = self._windows.setdefault(key, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            self._last_seen[key] = now
            if len(window) >= self.max_requests:
                retry_after = max(1, int(window[0] + self.window_seconds - now + 0.999))
                return RateLimitDecision(False, retry_after)
            window.append(now)
            return RateLimitDecision(True)
