from __future__ import annotations

from datetime import datetime, timedelta, timezone


class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock(Clock):
    def __init__(self, current: datetime | None = None) -> None:
        self.current = current or datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)
