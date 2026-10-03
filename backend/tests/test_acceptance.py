"""Acceptance tests from the physical-layer brief (Brief 2), section "Acceptance tests".

Built around the tick-12 fixture from the brief's own bug report (solar 15.3, wind 89.9,
base demand 71.2, industrial demand 32.6, transmission constraint 94.7, battery_1 at 89%
SoC, battery_2 offline, storm alert) — since those numbers were computed by hand in the
brief, reproducing them exactly is a good independent check of the physics module.
"""
from __future__ import annotations

from unittest.mock import patch

from app.agents import pipeline
from app.agents.evaluator import evaluate
from app.agents.scenario_agent import generate_scenario, normalize_scenario
from app.data import physics
from app.data.balancer import balance
from app.models.schemas import Battery, BatteryAction, Decision, Difficulty, EnvironmentState, Objective


def _tick12_scenario(objective=None, transmission_headroom_mw=94.7) -> EnvironmentState:
    return EnvironmentState(
        tick=12,
        seed=12,
        difficulty=Difficulty.D3_MULTI_FAILURE_CASCADE,
        objective=objective,
        solar_output_mw=15.3,
        solar_forecast_mw=15.0,
        wind_output_mw=89.9,
        wind_forecast_mw=90.0,
        solar_farms=[],
        wind_farms=[],
        base_demand_mw=71.2,
        base_demand_forecast_mw=71.0,
        total_demand_mw=103.8,
        total_demand_forecast_mw=103.6,
        grid_frequency_hz=50.0,
        transmission_constraint_mw=94.7,
        transmission_headroom_mw=transmission_headroom_mw,
        batteries=[
            Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=89.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
            Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=50.0, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=False),
        ],
        previous_floor_pct=45.0,
        electricity_price_per_mwh=100.0,
        carbon_price_per_ton=30.0,
        demand_response_incentive_per_mwh=20.0,
        weather_forecast="storm",
        storm_alert=True,
        maintenance_scheduled=False,
        industrial_demand_mw=32.6,
        events=["battery_2_offline", "storm_alert"],
        expected_behavior="fixture",
        expected_floor_min_pct=45.0,
        expected_floor_max_pct=60.0,
        expected_ladder_step="fixture",
        expected_emergency=False,
    )


def _decision(**overrides) -> Decision:
    base = dict(
        tick=12,
        objective_used="cost_efficiency",
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="hold",
        market_amount_mw=0.0,
        curtail_solar_mw=0.0,
        curtail_wind_mw=0.0,
        demand_response_triggered=False,
        proposed_floor_pct=45.0,
        applied_floor_pct=45.0,
        floor_justification="fixture",
        reasoning="fixture",
    )
    base.update(overrides)
    return Decision(**base)


def test_1_original_decision_unserved_42_3():
    scenario = _tick12_scenario()
    decision = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="sell", market_amount_mw=7.9,
        curtail_wind_mw=25.8,
    )
    unserved = physics.unserved_mw(scenario, decision)
    assert round(unserved, 1) == 42.3

    result = evaluate(scenario, decision)
    rule3 = next(r for r in result.rules if r.rule_id == "rule_3")
    rule4 = next(r for r in result.rules if r.rule_id == "rule_4")
    assert not rule3.passed
    assert not rule4.passed  # selling while unserved — rules 3 and 4 agree


def test_2_balanced_decision_passes():
    scenario = _tick12_scenario(objective=Objective.MAX_RENEWABLE_UTILISATION)
    decision = _decision(
        objective_used="max_renewable_utilisation",
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=1.4), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="hold", market_amount_mw=0.0,
        curtail_wind_mw=0.0,
    )
    result = evaluate(scenario, decision)
    for rule_id in ("rule_3", "rule_4", "rule_6", "rule_7"):
        r = next(x for x in result.rules if x.rule_id == rule_id)
        assert r.passed, f"{rule_id}: {r.detail}"
    rule9 = next(r for r in result.rules if r.rule_id == "rule_9")
    assert rule9.passed, rule9.detail


def test_3_curtailment_25_8_fails_rule6_and_flags_rule9():
    scenario = _tick12_scenario(objective=Objective.MAX_RENEWABLE_UTILISATION)
    decision = _decision(
        objective_used="max_renewable_utilisation",
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="sell", market_amount_mw=7.9,
        curtail_wind_mw=25.8,
    )
    min_required = physics.min_required_curtailment_mw(scenario)
    assert min_required < 1.0
    result = evaluate(scenario, decision)
    rule6 = next(r for r in result.rules if r.rule_id == "rule_6")
    rule9 = next(r for r in result.rules if r.rule_id == "rule_9")
    assert not rule6.passed
    assert not rule9.passed


def test_4_balancer_repairs_original_proposal():
    scenario = _tick12_scenario()
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="sell", market_amount_mw=7.9,
        curtail_wind_mw=25.8,
    )
    applied, repairs = balance(scenario, proposal)
    assert len(repairs) > 0
    assert abs(physics.power_balance_residual(scenario, applied)) < 0.2
    result = evaluate(scenario, applied, repairs)
    rule10 = next(r for r in result.rules if r.rule_id == "rule_10")
    assert not rule10.passed  # repair magnitude exceeded tolerance


def test_5_over_discharge_capped_and_flagged():
    scenario = _tick12_scenario()
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        proposed_floor_pct=45.0, applied_floor_pct=45.0,
    )
    # battery_1 at 46% SoC, floor 45%: only 1 point of headroom = 0.4MWh = 1.6MW this tick —
    # well under the proposed 10MW, so the balancer must cap it.
    near_floor_battery = scenario.batteries[0].model_copy(update={"state_of_charge_pct": 46.0})
    scenario = scenario.model_copy(update={"batteries": [near_floor_battery, scenario.batteries[1]]})
    applied, repairs = balance(scenario, proposal)
    b1_action = next(a for a in applied.battery_actions if a.battery_id == "battery_1")
    resulting_soc = physics.resulting_soc_pct(near_floor_battery, b1_action.amount_mw)
    assert b1_action.amount_mw < 10.0  # the proposed amount was actually capped
    assert resulting_soc >= 45.0 - 0.1  # capped at (or above) the applied floor
    assert any("battery_1" in r.field for r in repairs)


def test_6_offline_battery_forced_to_zero():
    scenario = _tick12_scenario()
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="discharge", amount_mw=5.0)],
    )
    applied, repairs = balance(scenario, proposal)
    b2_action = next(a for a in applied.battery_actions if a.battery_id == "battery_2")
    assert b2_action.amount_mw == 0.0
    assert any("battery_2" in r.field for r in repairs)


def test_7_computed_emergency():
    # tick-12 as given: generation (105.2MW) alone already exceeds total demand (103.8MW),
    # so it can never be an emergency regardless of transmission headroom — confirms the
    # calm case.
    calm_scenario = _tick12_scenario(transmission_headroom_mw=94.7)
    assert physics.is_emergency(calm_scenario, 45.0) is False

    # A genuine shortfall case: generation alone falls well short of demand, and with
    # transmission headroom and battery both constrained, even the full ladder can't close it.
    shortfall_scenario = _tick12_scenario(transmission_headroom_mw=2.0).model_copy(update={"wind_output_mw": 10.0})
    assert physics.is_emergency(shortfall_scenario, 45.0) is True

    # Same shortfall, but with transmission headroom open — the ladder (import) covers it.
    shortfall_but_importable = shortfall_scenario.model_copy(update={"transmission_headroom_mw": 94.7})
    assert physics.is_emergency(shortfall_but_importable, 45.0) is False


def test_8_rules_3_and_4_never_disagree():
    scenario = _tick12_scenario()
    for curtail, sell in [(0.0, 0.0), (25.8, 7.9), (0.0, 7.9), (10.0, 20.0)]:
        decision = _decision(market_action="sell" if sell else "hold", market_amount_mw=sell, curtail_wind_mw=curtail)
        result = evaluate(scenario, decision)
        rule3 = next(r for r in result.rules if r.rule_id == "rule_3")
        rule4 = next(r for r in result.rules if r.rule_id == "rule_4")
        unserved = physics.unserved_mw(scenario, decision)
        assert rule3.passed == (unserved <= 0.1)
        if not rule3.passed and sell > 0:
            assert not rule4.passed


def test_9_seed_reproducibility():
    a = generate_scenario(Difficulty.D2_PRICE_SPIKE, Objective.MIN_CARBON, seed=777)
    b = generate_scenario(Difficulty.D2_PRICE_SPIKE, Objective.MIN_CARBON, seed=777)
    a_data = a.model_dump(exclude={"tick"})
    b_data = b.model_dump(exclude={"tick"})
    assert a_data == b_data
    assert a.seed == b.seed == 777


def test_10_full_matrix_generates_without_error():
    for difficulty in Difficulty:
        for objective in list(Objective) + [None]:
            s = generate_scenario(difficulty, objective, seed=1)
            assert s.total_demand_mw == round(s.base_demand_mw + s.industrial_demand_mw, 1)


def test_11_same_pipeline_for_every_mode():
    scenario = _tick12_scenario()
    stub_proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=1.4), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
    )
    with patch.object(pipeline, "decide", return_value=stub_proposal):
        result_a = pipeline.run_decision_pipeline(scenario)
        result_b = pipeline.run_decision_pipeline(scenario)
    assert result_a.applied == result_b.applied
    assert result_a.evaluation.status == result_b.evaluation.status
    # Confirm it's literally the same balance()/evaluate() functions, not a parallel copy:
    applied_direct, repairs_direct = balance(scenario, stub_proposal)
    eval_direct = evaluate(scenario, applied_direct, repairs_direct)
    assert result_a.applied == applied_direct
    assert result_a.evaluation.status == eval_direct.status


def test_12_manual_consistency():
    scenario = _tick12_scenario()
    edited = scenario.model_copy(update={"industrial_demand_mw": 50.0})
    normalized, corrections = normalize_scenario(edited)
    assert normalized.total_demand_mw == round(edited.base_demand_mw + 50.0, 1)
    assert any("total_demand_mw" in c for c in corrections)

    inconsistent = scenario.model_copy(update={
        "events": ["battery_2_offline"],
        "batteries": [scenario.batteries[0], scenario.batteries[1].model_copy(update={"available": True})],
    })
    normalized2, corrections2 = normalize_scenario(inconsistent)
    battery_2 = next(b for b in normalized2.batteries if b.id == "battery_2")
    assert battery_2.available is False
    assert any("battery_2" in c for c in corrections2)
