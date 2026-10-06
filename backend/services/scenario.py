from __future__ import annotations

import json
from pathlib import Path


SCENARIO_DIR = Path(__file__).resolve().parents[2] / "data" / "scenarios"
DEFAULT_SCENARIO_ID = "c001-fee-resolution"


def load_demo_scenario(scenario_id: str = DEFAULT_SCENARIO_ID) -> dict:
    path = SCENARIO_DIR / f"{scenario_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for candidate in SCENARIO_DIR.glob("*.json"):
        scenario = json.loads(candidate.read_text(encoding="utf-8"))
        if scenario.get("scenario_id") == scenario_id:
            return scenario
    raise ValueError(f"unknown demo scenario: {scenario_id}")


def load_demo_scenarios() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCENARIO_DIR.glob("*.json"))
    ]
