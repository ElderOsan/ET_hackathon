"""Acceptance tests from the Brief 2 Patch (calibration, balancer unwind-order fix, raw+applied
scoreboard). Built around the tick-88 fixture from the patch's own bug report: generation
101.7MW (solar 40 + wind 61.7), total demand 139.0MW, original proposal charged 16MW
(battery_1 10 + battery_2 6) and sold 17.3MW. These numbers were computed by hand in the
brief, so reproducing them exactly is a good independent check.
"""
from __future__ import annotations

from unittest.mock import patch

from app.agents import pipeline
from app.agents.evaluator import evaluate
from app.agents.orchestrator_agent import SUBMIT_DECISION_SCHEMA
from app.agents.scenario_agent import generate_scenario, normalize_scenario
from app.data import fleet, physics
from app.data.balancer import balance
from app.data.tuning import PROFILE_RATIO_RANGES
from app.models.schemas import Battery, BatteryAction, Decision, Difficulty, EnvironmentState, Objective


def _tick88_scenario(**overrides) -> EnvironmentState:
    base = dict(
        tick=88,
        seed=88,
        difficulty=Difficulty.D1_STABLE_DAY,
        objective=None,
        solar_output_mw=40.0,
        solar_forecast_mw=40.0,
        wind_output_mw=61.7,
        wind_forecast_mw=61.7,
        solar_farms=[],
        wind_farms=[],
        base_demand_mw=100.0,
        base_demand_forecast_mw=100.0,
        total_demand_mw=139.0,
        total_demand_forecast_mw=139.0,
        grid_frequency_hz=50.0,
        transmission_constraint_mw=180.0,
        transmission_headroom_mw=180.0,
        batteries=[
            Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
            Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=True),
        ],
        previous_floor_pct=25.0,
        electricity_price_per_mwh=60.0,
        buy_price_per_mwh=63.0,
        sell_price_per_mwh=57.0,
        carbon_price_per_ton=30.0,
        demand_response_incentive_per_mwh=20.0,
        weather_forecast="clear",
        storm_alert=False,
        maintenance_scheduled=False,
        industrial_demand_mw=39.0,
        events=[],
        expected_behavior="fixture",
        expected_floor_min_pct=20.0,
        expected_floor_max_pct=30.0,
        expected_ladder_step="fixture",
        expected_emergency=False,
    )
    base.update(overrides)
    return EnvironmentState(**base)


def _decision(**overrides) -> Decision:
    base = dict(
        tick=88,
        objective_used="cost_efficiency",
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="hold",
        market_amount_mw=0.0,
        curtail_solar_mw=0.0,
        curtail_wind_mw=0.0,
        demand_response_triggered=False,
        proposed_floor_pct=25.0,
        applied_floor_pct=25.0,
        floor_justification="fixture",
        reasoning="fixture",
    )
    base.update(overrides)
    return Decision(**base)


def _original_tick88_proposal() -> Decision:
    return _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="charge", amount_mw=6.0)],
        market_action="sell", market_amount_mw=17.3,
    )


def test_1_display_single_result_element_and_na():
    scenario = _tick88_scenario()
    decision = _decision()  # fully served (101.7 generation vs... actually unserved here, see test below)
    result = evaluate(scenario, decision)
    rule3b = next(r for r in result.rules if r.rule_id == "rule_3b")
    # load is unserved for this hold-everything decision -> rule_3b must be N/A, not a disguised pass
    assert rule3b.applicable is False


def test_2_fixed_fleet_identical_across_scenarios():
    s1 = generate_scenario(Difficulty.D1_STABLE_DAY, Objective.COST_EFFICIENCY, seed=1)
    s2 = generate_scenario(Difficulty.D3_MULTI_FAILURE_CASCADE, Objective.MAX_PROFIT, seed=2)
    for s in (s1, s2):
        solar_ids = {f.id: f.capacity_mw for f in s.solar_farms}
        wind_ids = {f.id: f.capacity_mw for f in s.wind_farms}
        assert solar_ids == fleet.SOLAR_FARM_CAPACITIES_MW
        assert wind_ids == fleet.WIND_FARM_CAPACITIES_MW
        battery_specs = {b.id: (b.capacity_mwh, b.max_charge_rate_mw, b.max_discharge_rate_mw) for b in s.batteries}
        expected = {spec["id"]: (spec["capacity_mwh"], spec["max_charge_rate_mw"], spec["max_discharge_rate_mw"]) for spec in fleet.BATTERY_SPECS}
        assert battery_specs == expected


def test_4_profile_ratios_in_range():
    for difficulty in Difficulty:
        lo, hi = PROFILE_RATIO_RANGES[difficulty.value]
        for seed in range(30):
            s = generate_scenario(difficulty, None, seed=1000 * (list(Difficulty).index(difficulty) + 1) + seed)
            ratio = (s.solar_output_mw + s.wind_output_mw) / s.total_demand_mw
            assert lo - 0.01 <= ratio <= hi + 0.01, f"{difficulty.value} seed={seed}: ratio {ratio}"
            assert physics.min_achievable_unserved_mw(s) == 0.0
    # stable_day always a surplus, shortfall_day always below 1.0 (explicit brief requirement)
    for seed in range(10):
        s_stable = generate_scenario(Difficulty.D1_STABLE_DAY, None, seed=seed)
        assert (s_stable.solar_output_mw + s_stable.wind_output_mw) / s_stable.total_demand_mw > 1.0
        s_short = generate_scenario(Difficulty.D5_SHORTFALL_DAY, None, seed=seed)
        assert (s_short.solar_output_mw + s_short.wind_output_mw) / s_short.total_demand_mw < 1.0


def test_5_orchestrator_facts_derived_from_state_only():
    scenario = _tick88_scenario()
    facts = physics.orchestrator_facts(scenario, scenario.previous_floor_pct)
    assert facts["total_generation_mw"] == round(scenario.solar_output_mw + scenario.wind_output_mw, 1)
    assert facts["net_position_mw"] == round(facts["total_generation_mw"] - scenario.total_demand_mw, 1)
    assert facts["position"] == "shortfall"
    forbidden_keys = {"expected_behavior", "expected_emergency", "expected_floor_min_pct", "expected_floor_max_pct", "status", "rules", "passed"}
    assert forbidden_keys.isdisjoint(facts.keys())
    for b in facts["per_battery"]:
        assert set(b.keys()) == {"battery_id", "discharge_available_mw", "charge_headroom_mw"}


def test_6_reasoning_first_in_schema():
    assert list(SUBMIT_DECISION_SCHEMA["properties"].keys())[0] == "reasoning"
    assert SUBMIT_DECISION_SCHEMA["required"][0] == "reasoning"


def test_7_charging_unwound_tick88_fixture():
    scenario = _tick88_scenario()
    proposal = _original_tick88_proposal()
    applied, repairs = balance(scenario, proposal)

    assert applied.market_action == "hold"
    assert all(a.action == "hold" or a.amount_mw == 0 for a in applied.battery_actions)
    unserved = physics.unserved_mw(scenario, applied)
    assert round(unserved, 1) == 37.3

    repaired_fields = {r.field for r in repairs}
    assert any("sell" in f for f in repaired_fields)
    assert any("battery_1" in f for f in repaired_fields) or any("battery_2" in f for f in repaired_fields)


def test_8_balancer_never_adds_discharge_or_purchase():
    scenario = _tick88_scenario()
    proposal = _decision()  # proposes nothing at all — pure shortfall
    applied, repairs = balance(scenario, proposal)
    assert all(a.action != "discharge" for a in applied.battery_actions)
    assert applied.market_action != "buy"
    # the shortfall is left standing, not invented away
    assert round(physics.unserved_mw(scenario, applied), 1) == round(scenario.total_demand_mw - (scenario.solar_output_mw + scenario.wind_output_mw), 1)


def test_9_rule3_avoidable_shows_both_numbers():
    scenario = _tick88_scenario()
    proposal = _original_tick88_proposal()
    applied, repairs = balance(scenario, proposal)
    achievable = physics.min_achievable_unserved_mw(scenario)
    assert achievable == 0.0  # generation + 16MW emergency discharge + headroom covers demand
    result = evaluate(scenario, applied, repairs)
    rule3 = next(r for r in result.rules if r.rule_id == "rule_3")
    assert not rule3.passed
    assert rule3.value_actual == round(physics.unserved_mw(scenario, applied), 1)
    assert rule3.value_reference == 0.0


def test_10_rule3_infeasible_scenario_not_failed():
    # Crank demand far beyond anything the fleet + batteries + headroom could ever cover.
    scenario = _tick88_scenario(total_demand_mw=5000.0, total_demand_forecast_mw=5000.0, transmission_headroom_mw=1.0)
    achievable = physics.min_achievable_unserved_mw(scenario)
    assert achievable > 0
    # A decision that uses every lever maximally (full emergency discharge + full import) —
    # the best ANYONE could do — must match the achievable minimum exactly, not exceed it.
    decision = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="discharge", amount_mw=6.0)],
        market_action="buy", market_amount_mw=1.0,
    )
    result = evaluate(scenario, decision)
    rule3 = next(r for r in result.rules if r.rule_id == "rule_3")
    # unserved == achievable (within tolerance) -> not the decision's fault -> passes
    assert rule3.passed, rule3.detail


def test_11_scoreboard_fields_present():
    scenario = _tick88_scenario()
    stub_proposal = _original_tick88_proposal()
    with patch.object(pipeline, "decide", return_value=stub_proposal):
        result = pipeline.run_decision_pipeline(scenario)
    assert {s.name for s in result.stages} == {"raw", "applied"}
    raw = next(s for s in result.stages if s.name == "raw")
    applied = next(s for s in result.stages if s.name == "applied")
    assert not any(r.rule_id == "rule_10" for r in raw.evaluation.rules)
    assert any(r.rule_id == "rule_10" for r in applied.evaluation.rules)


def test_12_raw_fails_3_and_4_applied_fails_3_only():
    scenario = _tick88_scenario()
    stub_proposal = _original_tick88_proposal()
    with patch.object(pipeline, "decide", return_value=stub_proposal):
        result = pipeline.run_decision_pipeline(scenario)
    raw = next(s for s in result.stages if s.name == "raw")
    applied = next(s for s in result.stages if s.name == "applied")

    raw_rule3 = next(r for r in raw.evaluation.rules if r.rule_id == "rule_3")
    raw_rule4 = next(r for r in raw.evaluation.rules if r.rule_id == "rule_4")
    assert not raw_rule3.passed
    assert not raw_rule4.passed  # sold 17.3MW while demand was unmet

    applied_rule3 = next(r for r in applied.evaluation.rules if r.rule_id == "rule_3")
    applied_rule4 = next(r for r in applied.evaluation.rules if r.rule_id == "rule_4")
    assert not applied_rule3.passed  # shortfall remains (37.3MW) — a model mistake, not infeasible
    assert applied_rule4.passed  # balancer already stripped the sale


def test_13_seed_sets_reproducible():
    from app.data.benchmark_seeds import DEV_SEED_SET, HELD_OUT_SEED_SET
    assert DEV_SEED_SET["name"] == "dev"
    assert HELD_OUT_SEED_SET["name"] == "held_out"
    a = generate_scenario(Difficulty.D2_PRICE_SPIKE, Objective.MIN_CARBON, seed=DEV_SEED_SET["base_seed"])
    b = generate_scenario(Difficulty.D2_PRICE_SPIKE, Objective.MIN_CARBON, seed=DEV_SEED_SET["base_seed"])
    assert a.model_dump(exclude={"tick"}) == b.model_dump(exclude={"tick"})


def test_14_manual_consistency_recomputes_ladder_from_position():
    scenario = _tick88_scenario()  # shortfall scenario tagged with placeholder ladder text
    normalized, corrections = normalize_scenario(scenario)
    assert "shortfall" in normalized.expected_ladder_step.lower() or "import" in normalized.expected_ladder_step.lower()
    assert any("expected_ladder_step" in c for c in corrections)


def test_16_rule3b_tick1_tick60_margin_infeasible_not_flagged():
    # Brief 2 Patch 2, acceptance test 1: ticks 1 (seed 472264643) and 60 (seed 1039876167)
    # reproduce; rule_3b reports margin infeasible with best possible 0.2MW / 1.6MW, and
    # does not flag a decision that reaches that achievable max.
    s1 = generate_scenario(Difficulty.D3_MULTI_FAILURE_CASCADE, None, seed=472264643)
    s60 = generate_scenario(Difficulty.D3_MULTI_FAILURE_CASCADE, Objective.MAX_PROFIT, seed=1039876167)
    for scenario, expected_best in [(s1, 0.2), (s60, 1.6)]:
        achievable = physics.max_achievable_headroom_mw(scenario, scenario.previous_floor_pct)
        assert round(achievable, 1) == expected_best, f"seed {scenario.seed}: achievable={achievable}"
        # A decision that maxes every lever (full discharge above floor + full import) should
        # reach that achievable max and not be flagged by rule_3b.
        battery_actions = [
            BatteryAction(battery_id=b.id, action="discharge", amount_mw=physics.max_discharge_mw(b, scenario.previous_floor_pct, emergency=False))
            for b in scenario.batteries
        ]
        shortfall = max(0.0, scenario.total_demand_mw - physics.total_generation_mw(scenario) - sum(a.amount_mw for a in battery_actions))
        decision = _decision(
            battery_actions=battery_actions,
            market_action="buy" if shortfall > 0 else "hold",
            market_amount_mw=round(min(shortfall, scenario.transmission_headroom_mw), 1),
            proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
        )
        result = evaluate(scenario, decision)
        rule3b = next(r for r in result.rules if r.rule_id == "rule_3b")
        assert rule3b.passed, rule3b.detail
        assert "margin infeasible" in rule3b.detail.lower()


def test_17_rule3b_flags_when_achievable_exceeds_requirement_but_decision_falls_short():
    # Brief 2 Patch 2, acceptance test 2: achievable margin exceeds the requirement, but the
    # decision leaves less than that — still flagged.
    scenario = _tick88_scenario(total_demand_mw=100.0, total_demand_forecast_mw=100.0)
    # generation 101.7 already exceeds demand 100 -> no shortfall to cover; achievable headroom
    # is the full lever capacity (16MW batteries + 180MW transmission = 196MW), comfortably
    # above the 5% requirement (5.0MW), so target == required == 5.0MW, not the achievable max.
    # A decision that uses almost all of both levers (leaving only ~0.15MW unused) still falls
    # short of that 5.0MW target and must be flagged.
    decision = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="discharge", amount_mw=9.9), BatteryAction(battery_id="battery_2", action="discharge", amount_mw=6.0)],
        market_action="buy", market_amount_mw=179.95,
    )
    result = evaluate(scenario, decision)
    rule3b = next(r for r in result.rules if r.rule_id == "rule_3b")
    assert not rule3b.passed, rule3b.detail
    assert "margin infeasible" not in rule3b.detail.lower()


def test_18_profit_nets_purchase_cost_not_zero():
    # Brief 2 Patch 2, acceptance test 3: a decision that buys 1.8MW shows a negative
    # profit equal to the purchase cost, with components shown — never $0.
    scenario = _tick88_scenario(objective=Objective.MAX_PROFIT)
    decision = _decision(market_action="buy", market_amount_mw=1.8)
    profit = physics.decision_profit(scenario, decision)
    assert profit["cost"] == round(1.8 * scenario.buy_price_per_mwh, 1)
    assert profit["revenue"] == 0.0
    assert profit["net_profit"] == -profit["cost"]
    assert profit["net_profit"] != 0.0

    result = evaluate(scenario, decision)
    rule9 = next(r for r in result.rules if r.rule_id == "rule_9")
    assert f"${profit['cost']:.0f}" in rule9.detail
    assert "buy 1.8MW" in rule9.detail


def test_19_rule9_na_gives_verdict_from_other_rules_and_stays_in_denominator():
    # Patch 3, Step 1 (replaces the Patch 2 wording): N/A applies to a rule's result, never
    # to the whole scenario. A scenario with an N/A rule_9 still gets a verdict from its
    # other rules, and is never excluded from the batch's pass-rate denominator.
    balanced = _tick88_scenario(
        objective=Objective.MAX_PROFIT,
        wind_output_mw=99.0, wind_forecast_mw=99.0,  # generation == demand (139.0): no shortfall, no surplus
        transmission_headroom_mw=0.0,  # nothing sellable even if there were a surplus
    )
    decision = _decision()  # hold everything -- passes every other rule here
    result = evaluate(balanced, decision)
    rule9 = next(r for r in result.rules if r.rule_id == "rule_9")
    assert rule9.applicable is False
    assert rule9.passed is True
    assert "N/A" in rule9.detail and "decision" in rule9.detail.lower()
    assert result.status.value == "pass"  # verdict comes from the other (all-passing) rules

    from app.api.routes import _summarize
    from app.models.schemas import DecisionStage, ScenarioRunResult
    na_result = ScenarioRunResult(
        scenario=balanced,
        stages=[DecisionStage(name="raw", decision=decision, evaluation=result), DecisionStage(name="applied", decision=decision, evaluation=evaluate(balanced, decision, repairs=[]))],
        repairs=[], repaired=False,
    )
    normal_scenario = _tick88_scenario(objective=Objective.MAX_PROFIT)
    failing_decision = _decision()  # holds everything -> unserved -> fails rule_3, rule_9 judged normally
    normal_eval_raw = evaluate(normal_scenario, failing_decision, include_repair_rule=False)
    normal_eval_applied = evaluate(normal_scenario, failing_decision, repairs=[])
    normal_result = ScenarioRunResult(
        scenario=normal_scenario,
        stages=[DecisionStage(name="raw", decision=failing_decision, evaluation=normal_eval_raw), DecisionStage(name="applied", decision=failing_decision, evaluation=normal_eval_applied)],
        repairs=[], repaired=False,
    )
    summary = _summarize([na_result, normal_result], base_seed=1, seed_set_name=None, objectives=[Objective.MAX_PROFIT])
    assert summary.total == 2
    assert summary.judged_count == 2  # neither scenario is infeasible -- both stay in the denominator
    assert summary.na_counts_by_rule.get("rule_9") == 1  # reported per-rule, not subtracted from anything
    # na_result's raw stage is a clean PASS (counted); normal's raw stage fails rule_3 -> 1/2.
    assert summary.first_attempt_pass_rate_pct == 50.0
    assert summary.applied_passed + summary.applied_failed + summary.applied_flagged == 2


def test_20_buy_sell_prices_present_and_zero_spread_reproduces_old_behaviour():
    # Brief 2 Patch 2, acceptance test 5: buy/sell prices appear on the scenario (and so in
    # the prompt input and manual form, which both consume the scenario as-is) and in the
    # physics module; a spread of 0 reproduces the old single-price behaviour.
    s = generate_scenario(Difficulty.D1_STABLE_DAY, Objective.MAX_PROFIT, seed=5)
    assert s.buy_price_per_mwh == physics.buy_price_per_mwh(s.electricity_price_per_mwh)
    assert s.sell_price_per_mwh == physics.sell_price_per_mwh(s.electricity_price_per_mwh)
    assert s.buy_price_per_mwh > s.electricity_price_per_mwh > s.sell_price_per_mwh

    with patch.object(physics, "PRICE_SPREAD_PCT", 0.0):
        assert physics.buy_price_per_mwh(100.0) == 100.0
        assert physics.sell_price_per_mwh(100.0) == 100.0


def test_21_rule5_avoidable_charge_only_and_na_for_carbon_and_renewable():
    # Brief 2 Patch 2, acceptance test 6: rule_5 doesn't flag charging that absorbs
    # unsellable surplus, flags only the sellable part otherwise, and is N/A for
    # min_carbon / max_renewable_utilisation.
    base = dict(difficulty=Difficulty.D2_PRICE_SPIKE, total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=5.0)
    # generation 101.7 - demand 90 = surplus 11.7MW; sellable 5.0MW (headroom); unsellable 6.7MW.

    scenario = _tick88_scenario(**base, objective=Objective.COST_EFFICIENCY)
    fully_unavoidable = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=6.7), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)])
    r = evaluate(scenario, fully_unavoidable)
    rule5 = next(x for x in r.rules if x.rule_id == "rule_5")
    assert rule5.passed, rule5.detail

    partly_avoidable = _decision(battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=6.7), BatteryAction(battery_id="battery_2", action="charge", amount_mw=3.3)])
    r2 = evaluate(scenario, partly_avoidable)
    rule5b = next(x for x in r2.rules if x.rule_id == "rule_5")
    assert not rule5b.passed, rule5b.detail
    assert rule5b.value_actual == 3.3

    for objective in (Objective.MIN_CARBON, Objective.MAX_RENEWABLE_UTILISATION):
        na_scenario = _tick88_scenario(**base, objective=objective)
        r3 = evaluate(na_scenario, partly_avoidable)
        rule5c = next(x for x in r3.rules if x.rule_id == "rule_5")
        assert rule5c.applicable is False
        assert rule5c.passed is True


def test_22_repaired_flag_true_even_below_repair_tolerance():
    # Brief 2 Patch 2, acceptance test 8 / the row-49 root cause: a purchase-cap repair of
    # 0.2MW (well under REPAIR_TOLERANCE_MW=0.5) is enough to flip rule_3 from pass (raw,
    # uncapped purchase 10.2MW covers demand) to fail (applied, capped to the 10.0MW
    # transmission headroom, leaving 0.15MW unserved against BALANCE_TOLERANCE_MW=0.1) --
    # while the OLD `repaired` flag (gated on REPAIR_TOLERANCE_MW) would have shown
    # "Repaired: no" for this very row. ScenarioRunResult.repaired must be True whenever the
    # repair log is non-empty, regardless of magnitude.
    scenario = _tick88_scenario(
        wind_output_mw=50.0,  # generation 40 + 50 = 90.0
        total_demand_mw=100.15, total_demand_forecast_mw=100.15,
        transmission_headroom_mw=10.0,
    )
    proposal = _decision(market_action="buy", market_amount_mw=10.2)  # slightly over-buys
    with patch.object(pipeline, "decide", return_value=proposal):
        result = pipeline.run_decision_pipeline(scenario)

    total_repair = sum(abs(r.delta_mw) for r in result.repairs)
    assert 0 < total_repair < 0.5  # genuinely below REPAIR_TOLERANCE_MW
    assert result.repaired is True  # must reflect "a repair happened", not "a big one did"

    raw = next(s for s in result.stages if s.name == "raw")
    applied = next(s for s in result.stages if s.name == "applied")
    raw_rule3 = next(r for r in raw.evaluation.rules if r.rule_id == "rule_3")
    applied_rule3 = next(r for r in applied.evaluation.rules if r.rule_id == "rule_3")
    assert raw_rule3.passed, raw_rule3.detail  # uncapped 10.2MW purchase fully covers 100.15MW demand
    assert not applied_rule3.passed, applied_rule3.detail  # capped to 10.0MW leaves 0.15MW short


def test_23_empty_repair_log_implies_identical_raw_and_applied_verdict():
    # Brief 2 Patch 2, acceptance test 7 (regression): for every row with an empty repair
    # log, raw and applied verdicts are identical.
    import app.agents.pipeline as pipeline_module

    cases = []
    # An exactly-balanced scenario (generation == demand) with a pure hold decision: no
    # lever is used, nothing is short or surplus, so the balancer makes zero changes.
    balanced = _tick88_scenario(wind_output_mw=99.0, wind_forecast_mw=99.0)  # generation 139.0 == demand 139.0
    cases.append((balanced, _decision()))
    # A shortfall scenario where the proposal already uses exactly the achievable levers --
    # feasible as submitted, so the balancer has nothing to repair.
    for difficulty in (Difficulty.D1_STABLE_DAY, Difficulty.D3_MULTI_FAILURE_CASCADE, Difficulty.D5_SHORTFALL_DAY):
        for seed in range(5):
            s = generate_scenario(difficulty, None, seed=2_000_000 + seed)
            battery_actions = [BatteryAction(battery_id=b.id, action="discharge", amount_mw=physics.max_discharge_mw(b, s.previous_floor_pct, emergency=False)) for b in s.batteries]
            shortfall = max(0.0, s.total_demand_mw - physics.total_generation_mw(s) - sum(a.amount_mw for a in battery_actions))
            decision = _decision(
                tick=s.tick, battery_actions=battery_actions,
                market_action="buy" if shortfall > 0 else "hold", market_amount_mw=round(min(shortfall, s.transmission_headroom_mw), 1),
                proposed_floor_pct=s.previous_floor_pct, applied_floor_pct=s.previous_floor_pct,
            )
            cases.append((s, decision))

    checked_empty_repair_case = False
    for s, decision in cases:
        with patch.object(pipeline_module, "decide", return_value=decision):
            result = pipeline_module.run_decision_pipeline(s)
        raw = next(st for st in result.stages if st.name == "raw")
        applied = next(st for st in result.stages if st.name == "applied")
        if not result.repairs:
            checked_empty_repair_case = True
            assert raw.evaluation.status == applied.evaluation.status, f"seed={s.seed}: raw={raw.evaluation.status} applied={applied.evaluation.status} with no repairs"
    assert checked_empty_repair_case, "no empty-repair case was actually exercised by this test"


def test_15_regression_rules_3_and_4_never_disagree_on_unmet():
    scenario = _tick88_scenario()
    for curtail, sell, charge in [(0.0, 0.0, 0.0), (0.0, 17.3, 16.0), (0.0, 0.0, 16.0)]:
        battery_actions = [BatteryAction(battery_id="battery_1", action="charge", amount_mw=charge * (10 / 16) if charge else 0.0), BatteryAction(battery_id="battery_2", action="charge", amount_mw=charge * (6 / 16) if charge else 0.0)]
        decision = _decision(battery_actions=battery_actions, market_action="sell" if sell else "hold", market_amount_mw=sell, curtail_wind_mw=curtail)
        result = evaluate(scenario, decision)
        rule3 = next(r for r in result.rules if r.rule_id == "rule_3")
        rule4 = next(r for r in result.rules if r.rule_id == "rule_4")
        if not rule3.passed and sell > 0:
            assert not rule4.passed
        if rule4 and not rule4.passed:
            assert not rule3.passed
