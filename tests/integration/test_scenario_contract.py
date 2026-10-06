from __future__ import annotations

from backend.services.scenario import load_demo_scenario


def test_demo_scenario_is_data_driven_and_complete():
    scenario = load_demo_scenario()
    actions = [step["action"] for step in scenario["steps"]]
    assert actions[:4] == ["start", "transcript", "transcript", "commercial"]
    assert "resolve" in actions
    assert actions[-2:] == ["post-call", "post-call"]
    assert scenario["customer"]["customer_id"] == "C001"
