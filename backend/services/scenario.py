from __future__ import annotations

import json
from pathlib import Path


SCENARIO_PATH = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "c001-live.json"


def load_demo_scenario() -> dict:
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
