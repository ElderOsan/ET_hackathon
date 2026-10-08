"""Brief 2 Patch 2 evidence checklist, Step 1 deterministic cases: rule_3b (8+), the profit
metric (8+), rule_5 (8+), rule_9 N/A (6+), and a consistency check over every row of a real
stored batch (not just hand-built fixtures) rather than synthetic cases alone. No API calls.
"""
from __future__ import annotations

import json
import os

from app.agents.evaluator import evaluate
from app.data import file_input, physics, rules
from app.data.tuning import DISPATCHER_PRICE_SPIKE_THRESHOLD_USD, PRICE_SPREAD_PCT
from app.models.schemas import Battery, BatteryAction, Difficulty, Objective
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
    assert p["revenue"] == 0.0 and p["cost"] == round(10.0 * physics.TICK_HOURS * scenario.buy_price_per_mwh, 1) and p["net_profit"] == -p["cost"]


def test_profit_02_sell_only():
    scenario = _tick88_scenario()
    p = physics.decision_profit(scenario, _decision(market_action="sell", market_amount_mw=10.0))
    assert p["cost"] == 0.0 and p["revenue"] == round(10.0 * physics.TICK_HOURS * scenario.sell_price_per_mwh, 1) and p["net_profit"] == p["revenue"]


def test_profit_03_hold_is_both_zero():
    scenario = _tick88_scenario()
    p = physics.decision_profit(scenario, _decision())
    assert p == {"sale_mw": 0.0, "purchase_mw": 0.0, "revenue": 0.0, "cost": 0.0, "stored_energy_mwh": 0.0, "stored_energy_value": 0.0, "net_profit": 0.0}


def test_profit_04_spread_zero_buy_equals_sell_equals_electricity_price():
    from unittest.mock import patch as mockpatch
    with mockpatch.object(physics, "PRICE_SPREAD_PCT", 0.0):
        assert physics.buy_price_per_mwh(42.0) == 42.0
        assert physics.sell_price_per_mwh(42.0) == 42.0


def test_profit_05_large_purchase_scales_linearly():
    # amount_mw=4.0 (not 1.0): TICK_HOURS=0.25 makes 1.0MW*TICK_HOURS*price land on an exact
    # x.75 rounding boundary for this scenario's buy_price, which breaks a x100 linearity
    # check through independent rounding, not through any real nonlinearity -- 4.0 keeps
    # TICK_HOURS*amount an integer so neither side needs that boundary rounding.
    scenario = _tick88_scenario()
    small = physics.decision_profit(scenario, _decision(market_action="buy", market_amount_mw=4.0))
    large = physics.decision_profit(scenario, _decision(market_action="buy", market_amount_mw=400.0))
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
    assert p["net_profit"] == -round(1.8 * physics.TICK_HOURS * scenario.buy_price_per_mwh, 1)


def test_profit_09_charge_vs_sale_of_same_mw_differ_only_by_efficiency():
    # Round 0 diagnostic, fixed 2026-10-05: before the TICK_HOURS fix, charging valued MWh
    # (amount_mw * TICK_HOURS * efficiency) while selling valued raw MW with no TICK_HOURS --
    # a ~4x mismatch unrelated to efficiency. On one convention, the only remaining gap
    # between storing X MW and selling X MW of the same tick is the round-trip charging
    # efficiency: storing is worth exactly `efficiency` times what an immediate sale is worth.
    scenario = _tick88_scenario()
    battery = next(b for b in scenario.batteries if b.id == "battery_1")
    efficiency = battery.charging_efficiency_pct / 100.0

    sold = physics.decision_profit(scenario, _decision(market_action="sell", market_amount_mw=10.0))
    charged = physics.decision_profit(
        scenario,
        _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)]),
    )
    assert charged["stored_energy_value"] == round(sold["revenue"] * efficiency, 1)


# ---- rule_5: 8 cases --------------------------------------------------------------------


def _rule5(scenario, decision):
    return next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_5")


def _r5_scenario(objective, total_demand_mw=90.0, transmission_headroom_mw=5.0):
    # generation 101.7; at demand=90, surplus=11.7MW. transmission_headroom_mw caps sellable.
    # price is explicit and >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD (the state-based
    # threshold _daily_high_threshold now uses) -- the fixture's own tick88 default (60.0) no
    # longer counts as "at peak" since the fix replaced the old difficulty-gated relative
    # threshold (price*0.95, reachable at any price once tagged D2_PRICE_SPIKE) with an
    # absolute one.
    return _tick88_scenario(
        difficulty=Difficulty.D2_PRICE_SPIKE, objective=objective, total_demand_mw=total_demand_mw, total_demand_forecast_mw=total_demand_mw,
        transmission_headroom_mw=transmission_headroom_mw, electricity_price_per_mwh=150.0, buy_price_per_mwh=153.0, sell_price_per_mwh=147.0,
    )


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


def test_reference_dispatch_uses_applied_floor_not_expected_floor():
    # Patch 3 addendum: reference_dispatch must score against decision.applied_floor_pct,
    # not scenario.expected_floor_min_pct -- a higher applied floor gives the reference LESS
    # battery headroom credit, matching what the balancer actually allowed the decision.
    from app.data.balancer import reference_dispatch
    scenario = _tick88_scenario()  # expected_floor_min_pct=20.0, shortfall 37.3MW
    ref_at_low_floor = reference_dispatch(scenario, 20.0)
    ref_at_high_floor = reference_dispatch(scenario, 75.0)  # binds SoC, not just rate (see test_3b_07)
    assert ref_at_high_floor["min_grid_import_mw"] > ref_at_low_floor["min_grid_import_mw"]
    assert ref_at_high_floor["floor_used_for_reference_pct"] == 75.0
    # The informational (not scored) expected-floor comparison is always present and
    # independent of which floor was actually used to score.
    assert "reference_cost_at_expected_floor_pct" in ref_at_high_floor
    assert ref_at_high_floor["reference_cost_at_expected_floor_pct"] == ref_at_low_floor["reference_cost_at_expected_floor_pct"]


def test_rule2b_passes_when_discharge_lands_exactly_on_floor():
    # Patch 3 addendum, reproducing tick 63's exact numbers: battery_1 at 29.1% SoC,
    # discharging 6.6MW (rounded to 1 decimal) lands at 24.975% -- 0.025pp below a 25.0%
    # floor from rounding alone. Must pass, not be flagged.
    scenario = _tick88_scenario(
        batteries=[
            Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=29.1, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
            Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=67.5, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=True),
        ],
    )
    decision = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=6.6), BatteryAction(battery_id="battery_2", action="discharge", amount_mw=6.0)],
        market_action="buy", market_amount_mw=29.2,
        proposed_floor_pct=25.0, applied_floor_pct=25.0,
    )
    rule2b = next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_2b")
    assert rule2b.passed, rule2b.detail


def test_rule2b_still_flags_a_real_violation_beyond_tolerance():
    # The tolerance must not swallow a genuine violation -- 2MW further below the floor
    # (well beyond the 0.1pp rounding tolerance) must still be flagged.
    scenario = _tick88_scenario(
        batteries=[
            Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=20.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
            Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=67.5, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=True),
        ],
    )
    decision = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=8.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        proposed_floor_pct=25.0, applied_floor_pct=25.0,
    )
    rule2b = next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_2b")
    assert not rule2b.passed


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
    ref = reference_dispatch(scenario.model_copy(update={"objective": Objective.MAX_PROFIT}), scenario.previous_floor_pct)
    assert ref["max_sellable_mw"] == 5.0  # same value as the shared function


def test_consistency_over_real_72_row_benchmark():
    """Brief 2 Patch 2 Step 1 evidence requirement: check the invariant (empty repair log ->
    identical raw/applied verdict) over every row of an actual stored batch, not just
    hand-built cases. Uses the committed Step 6 three-pass dev benchmark."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "evidence", "brief2_patch2_benchmark.json")
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


# ---- rule_11 / balancer no-grid-charging cap (Addendum C, point 6) --------------------


def _rule11(scenario, decision):
    return next(r for r in evaluate(scenario, decision).rules if r.rule_id == "rule_11")


def test_rule11_01_charge_within_surplus_passes():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # surplus 11.7MW
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=5.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = _rule11(scenario, decision)
    assert r.passed, r.detail


def test_rule11_02_charge_beyond_surplus_flagged():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # surplus 11.7MW
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=15.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = _rule11(scenario, decision)
    assert not r.passed
    assert r.value_actual == 15.0 and r.value_reference == 11.7


def test_rule11_03_no_surplus_any_charge_flagged():
    scenario = _tick88_scenario()  # default: generation 101.7 < demand 139.0, no surplus
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=1.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = _rule11(scenario, decision)
    assert not r.passed


def test_rule11_04_hold_passes_regardless_of_surplus():
    scenario = _tick88_scenario()  # no surplus
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = _rule11(scenario, decision)
    assert r.passed


def test_balancer_caps_charge_to_renewable_surplus():
    # Addendum C, point 6: the balancer repairs a proposal that charges beyond the surplus,
    # same enforcement rule_11 flags on the raw proposal. demand=95 -> surplus 6.7MW, below
    # battery_1's own 10.0MW rate cap, so the surplus is the binding constraint here.
    from app.data.balancer import balance
    scenario = _tick88_scenario(total_demand_mw=95.0, total_demand_forecast_mw=95.0)
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    applied, repairs = balance(scenario, decision)
    charge_action = next(a for a in applied.battery_actions if a.battery_id == "battery_1")
    assert charge_action.amount_mw == 6.7
    assert any("renewable surplus" in r.reason for r in repairs)


def test_balancer_does_not_cap_charge_within_surplus():
    from app.data.balancer import balance
    scenario = _tick88_scenario(total_demand_mw=95.0, total_demand_forecast_mw=95.0)  # surplus 6.7MW
    decision = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=5.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    applied, repairs = balance(scenario, decision)
    charge_action = next(a for a in applied.battery_actions if a.battery_id == "battery_1")
    assert charge_action.amount_mw == 5.0
    assert not any("renewable surplus" in r.reason for r in repairs)


# ---- orchestrator_facts: min_required_curtailment_mw / surplus_after_max_charge_mw -----


def test_facts_transmission_headroom_never_negative_across_generated_scenarios():
    # The min_required_curtailment_mw / surplus_after_max_charge_mw equivalence (physics.py)
    # depends on transmission_headroom_mw >= 0 -- subtracting a non-negative number can't
    # move the result to the other side of the floor-at-0; a negative one could. Checked
    # across every generated profile, not just the fixture.
    from app.agents.scenario_agent import generate_scenario
    from app.models.schemas import GENERATED_DIFFICULTIES
    for difficulty in GENERATED_DIFFICULTIES:
        for seed in range(10):
            scenario = generate_scenario(difficulty, None, seed=9000 + seed)
            assert scenario.transmission_headroom_mw >= 0.0, f"{difficulty.value} seed={seed}: negative transmission_headroom_mw"


def test_facts_surplus_after_max_charge_matches_min_required_curtailment_intermediate():
    # surplus_after_max_charge_mw must be the exact intermediate term
    # min_required_curtailment_mw subtracts transmission_headroom_mw from -- not a second,
    # independently-computed value that could drift.
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=5.0)  # surplus 11.7MW
    surplus_after_charge = physics.surplus_after_max_charge_mw(scenario)
    min_curtail = physics.min_required_curtailment_mw(scenario)
    assert min_curtail == round(max(0.0, surplus_after_charge - scenario.transmission_headroom_mw), 1)
    # concretely: 11.7MW surplus - 16MW battery charge cap -> 0 (batteries absorb it all)
    assert surplus_after_charge == 0.0
    assert min_curtail == 0.0


def test_facts_min_required_curtailment_and_surplus_after_charge_in_orchestrator_facts():
    scenario = _tick88_scenario(total_demand_mw=50.0, total_demand_forecast_mw=50.0, transmission_headroom_mw=5.0)  # generation 101.7, surplus 51.7MW, forces real curtailment
    facts = physics.orchestrator_facts(scenario, scenario.previous_floor_pct)
    assert facts["surplus_after_max_charge_mw"] == round(physics.surplus_after_max_charge_mw(scenario), 1)
    assert facts["min_required_curtailment_mw"] == round(physics.min_required_curtailment_mw(scenario), 1)
    assert facts["min_required_curtailment_mw"] > 0.0  # a real case where curtailment is unavoidable


# ---- Prompt freeze guards (evidence/prompt_freeze.json, commit 6cd573a) -------------------
# Pinned the moment the prompt was frozen for submission (Gate 0.4 -> Option C: the rule_3
# capability gap is documented, not fixed -- no further SYSTEM_PROMPT/facts/schema changes
# are planned before the final run). These three constants exist so an ACCIDENTAL edit to
# any of them fails pytest in seconds instead of being discovered tomorrow when 96 rows miss
# their replay cache. If a change here is DELIBERATE, update the constant below AND
# re-record every recording under recordings/ that depends on it -- do not just loosen the
# assertion to make it pass again.

# prompt_version() hashes SYSTEM_PROMPT + the submit_decision tool schema as one blob --
# covers both, but says nothing about scenario fields or facts VALUES (see the two guards
# below, which cover what this one can't).
_FROZEN_PROMPT_VERSION = "114f4a55af8ba01b"

# orchestrator_facts()'s exact key set at freeze time. A KEY-SET check only -- it catches a
# fact being added/removed/renamed, not a change to the arithmetic behind an existing key
# (that's what the scenario_hash guards below are for, since scenario_hash hashes the
# facts' VALUES, not just their names).
_FROZEN_FACTS_KEYS = frozenset({
    "forecast_net_position_mw", "forecast_position", "forecast_total_generation_mw",
    "max_import_mw", "min_required_curtailment_mw", "net_position_mw", "per_battery",
    "position", "sellable_surplus_mw", "surplus_after_max_charge_mw",
    "total_charge_headroom_mw", "total_discharge_available_mw", "total_generation_mw",
})

# scenario_hash() hashes objective + non-hidden scenario fields + orchestrator_facts()
# output -- these two pinned hashes are the only guard that would catch a change to the
# MATH inside a physics function feeding a fact that's already in the key set above (e.g.
# a miscalculation introduced while touching unrelated dead code in the same module). One
# surplus scenario, one shortfall scenario, both fixed seeds.
_FROZEN_SCENARIO_HASH_SURPLUS = "409ee63ffcea6f1d"   # D4_SURPLUS_DAY, seed=1_000_001
_FROZEN_SCENARIO_HASH_SHORTFALL = "2043926da5d14061"  # D5_SHORTFALL_DAY, seed=1_000_002


def test_freeze_prompt_version_unchanged():
    from app.agents import orchestrator_agent
    actual = orchestrator_agent.prompt_version()
    assert actual == _FROZEN_PROMPT_VERSION, (
        f"SYSTEM_PROMPT or the tool schema changed after the freeze "
        f"(expected prompt_version {_FROZEN_PROMPT_VERSION!r}, got {actual!r}). "
        f"Every recording is now invalid. If this change was deliberate, update the "
        f"constant and re-record; if not, revert it."
    )


def test_freeze_orchestrator_facts_key_set_unchanged():
    from app.agents.scenario_agent import generate_scenario
    from app.models.schemas import Difficulty
    scenario = generate_scenario(Difficulty.D4_SURPLUS_DAY, None, seed=1_000_001)
    actual_keys = frozenset(physics.orchestrator_facts(scenario, scenario.previous_floor_pct).keys())
    assert actual_keys == _FROZEN_FACTS_KEYS, (
        f"orchestrator_facts() changed its key set after the freeze "
        f"(expected {sorted(_FROZEN_FACTS_KEYS)}, got {sorted(actual_keys)}). "
        f"Every recording is now invalid. If this change was deliberate, update the "
        f"constant and re-record; if not, revert it."
    )


def test_freeze_scenario_hash_unchanged():
    from app.agents import orchestrator_agent
    from app.agents.scenario_agent import generate_scenario
    from app.models.schemas import Difficulty
    surplus = generate_scenario(Difficulty.D4_SURPLUS_DAY, None, seed=1_000_001)
    shortfall = generate_scenario(Difficulty.D5_SHORTFALL_DAY, None, seed=1_000_002)
    actual_surplus = orchestrator_agent.scenario_hash(surplus)
    actual_shortfall = orchestrator_agent.scenario_hash(shortfall)
    assert actual_surplus == _FROZEN_SCENARIO_HASH_SURPLUS, (
        f"scenario_hash() changed for the pinned surplus reference scenario after the "
        f"freeze (expected {_FROZEN_SCENARIO_HASH_SURPLUS!r}, got {actual_surplus!r}) -- "
        f"the math behind a value in orchestrator_facts() moved, even though the key set "
        f"didn't. Every recording is now invalid. If this change was deliberate, update "
        f"the constant and re-record; if not, revert it."
    )
    assert actual_shortfall == _FROZEN_SCENARIO_HASH_SHORTFALL, (
        f"scenario_hash() changed for the pinned shortfall reference scenario after the "
        f"freeze (expected {_FROZEN_SCENARIO_HASH_SHORTFALL!r}, got {actual_shortfall!r}) -- "
        f"the math behind a value in orchestrator_facts() moved, even though the key set "
        f"didn't. Every recording is now invalid. If this change was deliberate, update "
        f"the constant and re-record; if not, revert it."
    )


# ---- _daily_high_threshold / rule_8c / rule_5 -- state-based, not generator-tag-based -----
# Regression guards for the bug confirmed this session: _daily_high_threshold() used to gate
# on scenario.difficulty.value == "price_spike", a generator tag Difficulty.FILE_INPUT rows
# never carry, making the price-peak check permanently unreachable for them regardless of
# actual price. No test existed for this bug class before now.


def test_volatility_signal_present_for_file_input_at_high_price():
    # EXAMPLE_DAY_ROWS[7] is the 12-row example's price-spike row (price 165, >= the 100
    # threshold) -- the exact row that used to be flagged by rule_8c incorrectly.
    row = dict(file_input.EXAMPLE_DAY_ROWS[7])
    scenario = file_input.row_to_scenario(row, 7)
    assert scenario.difficulty == Difficulty.FILE_INPUT
    assert scenario.electricity_price_per_mwh >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    assert rules._volatility_signal_present(scenario) is True


def test_volatility_signal_absent_for_file_input_at_calm_price():
    # EXAMPLE_DAY_ROWS[0]: no storm, no battery outage, price well under threshold -- isolates
    # the price check from the other four signals (storm/outage/demand_surge/transmission).
    row = dict(file_input.EXAMPLE_DAY_ROWS[0])
    scenario = file_input.row_to_scenario(row, 0)
    assert scenario.electricity_price_per_mwh < DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    assert rules._volatility_signal_present(scenario) is False


def test_rule_8c_does_not_fire_on_raised_floor_at_high_price():
    row = dict(file_input.EXAMPLE_DAY_ROWS[7])
    scenario = file_input.row_to_scenario(row, 7)
    decision = _decision(tick=scenario.tick, proposed_floor_pct=37.5, applied_floor_pct=37.5)
    result = rules.rule_8c_floor_raised_without_signal(scenario, decision)
    assert result.passed is True


def test_rule_5_fires_on_avoidable_charging_at_high_price_file_input():
    # The newly-reachable path: a FILE_INPUT scenario with a genuine surplus (so charging is
    # possible at all), a high price, a non-exempt objective, no emergency, and a charge that
    # exceeds the unsellable surplus -- asserted directly, not left to chance.
    scenario = _tick88_scenario(
        difficulty=Difficulty.FILE_INPUT, objective=Objective.COST_EFFICIENCY,
        total_demand_mw=50.0, total_demand_forecast_mw=50.0,  # generation 101.7 -> 51.7MW surplus
        transmission_headroom_mw=180.0,  # fully sellable -> unsellable_surplus_mw == 0, so any charge is avoidable
        electricity_price_per_mwh=150.0, buy_price_per_mwh=153.0, sell_price_per_mwh=147.0,
    )
    assert scenario.electricity_price_per_mwh >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    decision = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
    )
    result = rules.rule_5_no_charge_at_price_peak(scenario, decision)
    assert result.applicable is True
    assert result.passed is False
