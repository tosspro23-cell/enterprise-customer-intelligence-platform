from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class GuidanceResult:
    guidance_id: str
    title: str
    text: str
    source: str
    version: str
    purpose: str
    snapshot_id: str
    as_of: datetime
    expires_at: datetime


class LocalGuidanceIndex:
    def __init__(self, path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parents[3] / "data" / "guidance" / "fee-retention.json"
        self.path = Path(path or default_path)
        self._records = json.loads(self.path.read_text(encoding="utf-8"))
        self.fail = False

    def search(self, topic: str, *, purpose: str, now: datetime | None = None) -> GuidanceResult | None:
        if self.fail:
            return None
        now = now or datetime.now(timezone.utc)
        topic = topic.lower()
        record = next(
            (item for item in self._records if item["purpose"] == purpose and item["topic"] in topic),
            None,
        )
        if record is None:
            return None
        return GuidanceResult(
            guidance_id=record["guidance_id"],
            title=record["title"],
            text=record["text"],
            source=record["source"],
            version=record["version"],
            purpose=record["purpose"],
            snapshot_id=f"guidance-{record['guidance_id']}-{record['version']}",
            as_of=now,
            expires_at=now + timedelta(seconds=60),
        )
