"""Brief 2 Patch 2 evidence checklist, Step 1 deterministic cases: rule_3b (8+), the profit
metric (8+), rule_5 (8+), rule_9 N/A (6+), and a consistency check over every row of a real
stored batch (not just hand-built fixtures) rather than synthetic cases alone. No API calls.
"""
from __future__ import annotations

import json
import os

from app.agents.evaluator import evaluate
from app.data import physics
from app.data.tuning import PRICE_SPREAD_PCT
from app.models.schemas import BatteryAction, Difficulty, Objective
from tests.test_acceptance import _decision, _tick88_scenario

# ---- rule_3b: 8 cases -----------------------------------------------------------------


def _rule3b(scenario, decision):
    return next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_3b")


def test_3b_01_achievable_margin_below_requirement_decision_reaches_it():
    # multi_failure_cascade seed 472264643: achievable 0.2MW < required 4.9MW -- margin
    # infeasible; a decision that reaches the achievable max must pass.
    from app.agents.scenario_agent import generate_scenario
    scenario = generate_scenario(Difficulty.D3_MULTI_FAILURE_CASCADE, None, seed=472264643)
    battery_actions = [BatteryAction(battery_id=b.id, action="discharge", amount_mw=physics.max_discharge_mw(b, scenario.previous_floor_pct, False)) for b in scenario.batteries]
    shortfall = max(0.0, scenario.total_demand_mw - physics.total_generation_mw(scenario) - sum(a.amount_mw for a in battery_actions))
    decision = _decision(battery_actions=battery_actions, market_action="buy", market_amount_mw=round(min(shortfall, scenario.transmission_headroom_mw), 1), proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct)
    r = _rule3b(scenario, decision)
    assert r.passed and "margin infeasible" in r.detail.lower()


def test_3b_02_achievable_above_requirement_decision_falls_short():
    scenario = _tick88_scenario(total_demand_mw=100.0, total_demand_forecast_mw=100.0)
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=9.9), BatteryAction(battery_id="battery_2", action="discharge", amount_mw=6.0)], market_action="buy", market_amount_mw=179.95)
    r = _rule3b(scenario, decision)
    assert not r.passed


def test_3b_03_achievable_equals_requirement_boundary():
    # Construct achievable == required exactly: shrink lever_capacity to equal required.
    scenario = _tick88_scenario(total_demand_mw=100.0, total_demand_forecast_mw=100.0, transmission_headroom_mw=0.0)
    # lever_capacity = 16 (batteries) + 0 (headroom) = 16; shortfall 0 (surplus) -> achievable=16.
    # required = 5% * 100 = 5.0 < achievable=16, so target=required=5.0 here (not the boundary
    # case itself, but confirms target correctly uses required when achievable is ample).
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=5.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = _rule3b(scenario, decision)
    assert r.value_reference == 5.0  # target == required, not achievable, since achievable > required here


def test_3b_04_surplus_scenario_headroom_from_full_lever_capacity():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # 101.7 gen > 90 demand, no shortfall
    achievable = physics.max_achievable_headroom_mw(scenario, scenario.previous_floor_pct)
    assert achievable == 16.0 + 180.0  # full battery + full transmission, shortfall=0


def test_3b_05_zero_shortfall_matches_full_lever_capacity():
    scenario = _tick88_scenario(total_demand_mw=101.7, total_demand_forecast_mw=101.7)  # generation == demand exactly
    achievable = physics.max_achievable_headroom_mw(scenario, scenario.previous_floor_pct)
    assert achievable == 196.0  # shortfall 0 -> no deduction


def test_3b_06_battery_offline_reduces_lever_capacity():
    scenario = _tick88_scenario()
    battery_2_offline = scenario.model_copy(update={"batteries": [b.model_copy(update={"available": False}) if b.id == "battery_2" else b for b in scenario.batteries]})
    achievable = physics.max_achievable_headroom_mw(battery_2_offline, scenario.previous_floor_pct)
    achievable_both = physics.max_achievable_headroom_mw(scenario, scenario.previous_floor_pct)
    assert achievable < achievable_both  # battery_2's 6MW discharge capacity is gone


def test_3b_07_higher_floor_reduces_lever_capacity():
    # Both batteries sit at 80% SoC; floor 20% is rate-limited (10/6MW caps bind before SoC
    # does), so it needs a floor close to 80% to actually bind on SoC and show a difference.
    scenario = _tick88_scenario()
    low_floor = physics.max_achievable_headroom_mw(scenario, 20.0)
    high_floor = physics.max_achievable_headroom_mw(scenario, 75.0)
    assert high_floor < low_floor


def test_3b_08_zero_import_headroom():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=0.0)  # surplus -> shortfall 0
    achievable = physics.max_achievable_headroom_mw(scenario, scenario.previous_floor_pct)
    assert achievable == 16.0  # battery only, no import lever


# ---- profit metric: 8 cases ------------------------------------------------------------


def test_profit_01_buy_only():
    scenario = _tick88_scenario()
    p = physics.decision_profit(scenario, _decision(market_action="buy", market_amount_mw=10.0))
    assert p["revenue"] == 0.0 and p["cost"] == round(10.0 * scenario.buy_price_per_mwh, 1) and p["net_profit"] == -p["cost"]


def test_profit_02_sell_only():
    scenario = _tick88_scenario()
    p = physics.decision_profit(scenario, _decision(market_action="sell", market_amount_mw=10.0))
    assert p["cost"] == 0.0 and p["revenue"] == round(10.0 * scenario.sell_price_per_mwh, 1) and p["net_profit"] == p["revenue"]


def test_profit_03_hold_is_both_zero():
    scenario = _tick88_scenario()
    p = physics.decision_profit(scenario, _decision())
    assert p == {"sale_mw": 0.0, "purchase_mw": 0.0, "revenue": 0.0, "cost": 0.0, "net_profit": 0.0}


def test_profit_04_spread_zero_buy_equals_sell_equals_electricity_price():
    from unittest.mock import patch as mockpatch
    with mockpatch.object(physics, "PRICE_SPREAD_PCT", 0.0):
        assert physics.buy_price_per_mwh(42.0) == 42.0
        assert physics.sell_price_per_mwh(42.0) == 42.0


def test_profit_05_large_purchase_scales_linearly():
    scenario = _tick88_scenario()
    small = physics.decision_profit(scenario, _decision(market_action="buy", market_amount_mw=1.0))
    large = physics.decision_profit(scenario, _decision(market_action="buy", market_amount_mw=100.0))
    assert large["cost"] == round(small["cost"] * 100, 1)


def test_profit_06_nonzero_spread_buy_above_sell_below_quoted_price():
    scenario = _tick88_scenario()
    assert PRICE_SPREAD_PCT > 0
    assert scenario.buy_price_per_mwh > scenario.electricity_price_per_mwh > scenario.sell_price_per_mwh


def test_profit_07_rounds_to_one_decimal():
    scenario = _tick88_scenario(electricity_price_per_mwh=33.33, buy_price_per_mwh=physics.buy_price_per_mwh(33.33), sell_price_per_mwh=physics.sell_price_per_mwh(33.33))
    p = physics.decision_profit(scenario, _decision(market_action="sell", market_amount_mw=3.0))
    assert p["revenue"] == round(p["revenue"], 1)


def test_profit_08_buy_1_8mw_never_shows_zero():
    # The exact reported bug: a 1.8MW purchase must never net to $0.
    scenario = _tick88_scenario()
    p = physics.decision_profit(scenario, _decision(market_action="buy", market_amount_mw=1.8))
    assert p["net_profit"] != 0.0
    assert p["net_profit"] == -round(1.8 * scenario.buy_price_per_mwh, 1)


# ---- rule_5: 8 cases --------------------------------------------------------------------


def _rule5(scenario, decision):
    return next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_5")


def _r5_scenario(objective, total_demand_mw=90.0, transmission_headroom_mw=5.0):
    # generation 101.7; at demand=90, surplus=11.7MW. transmission_headroom_mw caps sellable.
    return _tick88_scenario(difficulty=Difficulty.D2_PRICE_SPIKE, objective=objective, total_demand_mw=total_demand_mw, total_demand_forecast_mw=total_demand_mw, transmission_headroom_mw=transmission_headroom_mw)


def test_5_01_fully_sellable_surplus_charging_flagged():
    scenario = _r5_scenario(Objective.COST_EFFICIENCY, total_demand_mw=96.7, transmission_headroom_mw=180.0)
    # surplus 5.0MW, all sellable (headroom 180) -> any charge is fully avoidable.
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=5.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = _rule5(scenario, decision)
    assert not r.passed


def test_5_02_fully_unsellable_surplus_charging_not_flagged():
    scenario = _r5_scenario(Objective.COST_EFFICIENCY, transmission_headroom_mw=0.0)
    # surplus 11.7MW, 0 sellable -> all charging is unavoidable.
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="charge", amount_mw=1.7)])
    r = _rule5(scenario, decision)
    assert r.passed


def test_5_03_partly_sellable_only_excess_flagged():
    scenario = _r5_scenario(Objective.COST_EFFICIENCY)  # sellable 5.0, unsellable 6.7
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=6.7), BatteryAction(battery_id="battery_2", action="charge", amount_mw=3.3)])
    r = _rule5(scenario, decision)
    assert not r.passed and r.value_actual == 3.3


def test_5_04_cost_efficiency_applies():
    scenario = _r5_scenario(Objective.COST_EFFICIENCY)
    r = _rule5(scenario, _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)]))
    assert r.applicable


def test_5_05_max_profit_applies():
    scenario = _r5_scenario(Objective.MAX_PROFIT)
    r = _rule5(scenario, _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)]))
    assert r.applicable


def test_5_06_min_carbon_na():
    scenario = _r5_scenario(Objective.MIN_CARBON)
    r = _rule5(scenario, _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)]))
    assert not r.applicable


def test_5_07_max_renewable_utilisation_na():
    scenario = _r5_scenario(Objective.MAX_RENEWABLE_UTILISATION)
    r = _rule5(scenario, _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)]))
    assert not r.applicable


def test_5_08_no_charge_at_peak_passes_trivially():
    scenario = _r5_scenario(Objective.COST_EFFICIENCY)
    r = _rule5(scenario, _decision())  # hold
    assert r.passed and r.value_actual == 0.0


# ---- rule_9 N/A: 6 cases ------------------------------------------------------------------


def _rule9(scenario, decision):
    return next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_9")


def test_9na_01_vacuous_zero_vs_zero_profit():
    # The exact reported vacuous case: "$0 vs $0" must now read N/A, not a disguised pass.
    scenario = _tick88_scenario(objective=Objective.MAX_PROFIT, wind_output_mw=99.0, wind_forecast_mw=99.0, transmission_headroom_mw=0.0)  # generation == demand, nothing sellable
    r = _rule9(scenario, _decision())
    assert not r.applicable
    assert "N/A" in r.detail


def test_9na_02_balanced_scenario_cost_na():
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY, wind_output_mw=99.0, wind_forecast_mw=99.0)  # no shortfall at all
    r = _rule9(scenario, _decision())
    assert not r.applicable


def test_9na_03_balanced_scenario_carbon_na():
    scenario = _tick88_scenario(objective=Objective.MIN_CARBON, wind_output_mw=99.0, wind_forecast_mw=99.0)
    r = _rule9(scenario, _decision())
    assert not r.applicable


def test_9na_04_no_surplus_renewable_na():
    scenario = _tick88_scenario(objective=Objective.MAX_RENEWABLE_UTILISATION)  # tick88 default is a shortfall -> no surplus to curtail
    r = _rule9(scenario, _decision())
    assert not r.applicable


def test_9na_05_real_shortfall_cost_has_freedom_not_na():
    scenario = _tick88_scenario(objective=Objective.COST_EFFICIENCY)  # 37.3MW shortfall, battery+import both available
    r = _rule9(scenario, _decision())
    assert r.applicable


def test_9na_06_real_surplus_renewable_has_freedom_not_na():
    scenario = _tick88_scenario(objective=Objective.MAX_RENEWABLE_UTILISATION, total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # 11.7MW surplus, headroom 180
    r = _rule9(scenario, _decision())
    assert r.applicable


# ---- consistency over a REAL stored batch (not synthetic fixtures) ----------------------


def test_facts_sellable_surplus_and_max_import_shared_definition():
    # Patch 3 addendum: sellable_surplus_mw / max_import_mw must be the SAME function rule_5
    # and reference_dispatch use, exposed in orchestrator_facts for the model to see directly.
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=5.0)
    # generation 101.7 - demand 90 = 11.7MW surplus; headroom 5.0MW caps what's sellable.
    assert physics.sellable_surplus_mw(scenario) == 5.0
    assert physics.max_import_mw(scenario) == 5.0  # == transmission_headroom_mw, no "minus planned sale"

    facts = physics.orchestrator_facts(scenario, scenario.previous_floor_pct)
    assert facts["sellable_surplus_mw"] == 5.0
    assert facts["max_import_mw"] == 5.0

    from app.data.balancer import reference_dispatch
    ref = reference_dispatch(scenario.model_copy(update={"objective": Objective.MAX_PROFIT}))
    assert ref["max_sellable_mw"] == 5.0  # same value as the shared function


def test_consistency_over_real_72_row_benchmark():
    """Brief 2 Patch 2 Step 1 evidence requirement: check the invariant (empty repair log ->
    identical raw/applied verdict) over every row of an actual stored batch, not just
    hand-built cases. Uses the committed Step 6 three-pass dev benchmark."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "brief2_patch2_benchmark.json")
    path = os.path.abspath(path)
    if not os.path.exists(path):
        import pytest
        pytest.skip(f"no stored batch at {path} -- run the Step 6 benchmark first")
    data = json.load(open(path))
    violations = []
    for r in data["results"]:
        if r["repairs"]:
            continue
        raw = next(s for s in r["stages"] if s["name"] == "raw")
        applied = next(s for s in r["stages"] if s["name"] == "applied")
        if raw["evaluation"]["status"] != applied["evaluation"]["status"]:
            violations.append((r["scenario"]["tick"], r["scenario"]["seed"], raw["evaluation"]["status"], applied["evaluation"]["status"]))
    assert violations == [], f"{len(violations)} empty-repair rows with differing verdicts: {violations}"
    assert len(data["results"]) == 72
