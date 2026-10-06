from __future__ import annotations

from backend.services.scenario import load_demo_scenario, load_demo_scenarios


def test_demo_scenario_is_data_driven_and_complete():
    scenario = load_demo_scenario()
    actions = [step["action"] for step in scenario["steps"]]
    transcript_steps = [step for step in scenario["steps"] if step["action"] == "transcript"]
    assert actions[0] == "start"
    assert len(transcript_steps) >= 10
    assert all(step["speaker"] in {"CUSTOMER", "AGENT"} for step in transcript_steps)
    assert [step["speaker"] for step in transcript_steps] == [
        "CUSTOMER" if index % 2 == 0 else "AGENT"
        for index in range(len(transcript_steps))
    ]
    assert "commercial" in actions
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
    for scenario in scenarios:
        turns = [step for step in scenario["steps"] if step["action"] == "transcript"]
        assert len(turns) >= 7
        assert [step["speaker"] for step in turns] == [
            "CUSTOMER" if index % 2 == 0 else "AGENT"
            for index in range(len(turns))
        ]
