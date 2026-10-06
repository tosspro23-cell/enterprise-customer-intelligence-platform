from __future__ import annotations

from backend.services.scenario import load_demo_scenario, load_demo_scenarios


def test_demo_scenario_is_data_driven_and_complete():
    scenario = load_demo_scenario()
    actions = [step["action"] for step in scenario["steps"]]
    assert actions[:4] == ["start", "transcript", "transcript", "commercial"]
    assert "resolve" in actions
    assert actions[-2:] == ["post-call", "post-call"]
    assert scenario["customer"]["customer_id"] == "C001"


def test_demo_catalog_contains_three_business_call_scripts():
    scenarios = load_demo_scenarios()
    assert len(scenarios) == 3
    assert {scenario["scenario_id"] for scenario in scenarios} == {
        "c001-fee-resolution",
        "c002-billing-recovery",
        "c001-savings-followup",
    }
    assert all(scenario["steps"][0]["action"] == "start" for scenario in scenarios)
