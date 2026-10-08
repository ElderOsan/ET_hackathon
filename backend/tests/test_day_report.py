"""Tests for day_report.py (C.1) -- zero coverage before this file existed, and it's the
screen two of the three first-run doors land on. No model calls anywhere here.
"""
from __future__ import annotations

from app.agents.pipeline import reevaluate_stored
from app.data import file_input
from app.data.day_report import build_day_report, report_to_csv
from app.data.tuning import DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
from app.models.schemas import (
    BatteryAction,
    Decision,
    DecisionStage,
    Difficulty,
    EvalResult,
    EvalStatus,
    Objective,
    RuleResult,
    ScenarioRunResult,
)
from tests.test_acceptance import _decision, _tick88_scenario


def _surplus_decision_charge(scenario, amount_mw=16.0):
    return _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=amount_mw), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="hold", market_amount_mw=0.0,
    )


def test_per_tick_row_reflects_the_given_decision():
    scenario = _tick88_scenario(tick=5, seed=505, total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # surplus 11.7MW
    proposal = _surplus_decision_charge(scenario, amount_mw=10.0)
    result = reevaluate_stored(scenario, proposal)

    report = build_day_report([scenario], [result])
    assert report["row_count"] == 1
    row = report["per_tick"][0]
    assert row["tick"] == 5
    assert row["seed"] == 505
    assert row["decision"]["battery_actions"][0] == {"battery_id": "battery_1", "action": "charge", "amount_mw": 10.0}
    assert row["applied_floor_pct"] == proposal.applied_floor_pct
    assert "ledger" in row and "verdict" in row and "resulting_soc_pct" in row


def test_cumulative_totals_are_the_sum_of_the_per_tick_ledgers():
    s1 = _tick88_scenario(tick=1, seed=1, total_demand_mw=90.0, total_demand_forecast_mw=90.0)
    s2 = _tick88_scenario(tick=2, seed=2, total_demand_mw=95.0, total_demand_forecast_mw=95.0)
    r1 = reevaluate_stored(s1, _surplus_decision_charge(s1, 8.0))
    r2 = reevaluate_stored(s2, _surplus_decision_charge(s2, 6.0))

    report = build_day_report([s1, s2], [r1, r2])
    expected_cost = round(report["per_tick"][0]["ledger"]["cost"] + report["per_tick"][1]["ledger"]["cost"], 2)
    expected_emissions = round(report["per_tick"][0]["ledger"]["emissions_tonnes"] + report["per_tick"][1]["ledger"]["emissions_tonnes"], 2)
    assert report["cumulative"]["agent"]["cost"] == expected_cost
    assert report["cumulative"]["agent"]["emissions_tonnes"] == expected_emissions


def test_both_baselines_diverge_exactly_where_the_dispatcher_does():
    # D4_SURPLUS_DAY-shaped surplus with full sellable headroom: max_profit sells before
    # charging (dispatcher.py's own branch), every other objective charges first -- a real,
    # known divergence (this session's ladder-reword probe), not a hand-picked edge case.
    scenario = _tick88_scenario(
        tick=9, seed=909, difficulty=Difficulty.D4_SURPLUS_DAY, objective=Objective.MAX_PROFIT,
        total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=180.0,
    )
    proposal = _surplus_decision_charge(scenario, amount_mw=10.0)  # the agent's own (bad, by max_profit's own ladder) choice is irrelevant to this test
    result = reevaluate_stored(scenario, proposal)

    report = build_day_report([scenario], [result])
    same_obj = report["cumulative"]["same_objective_baseline"]
    fixed_cost = report["cumulative"]["fixed_cost_baseline"]
    # same_objective_baseline runs under max_profit (sells); fixed_cost_baseline always runs
    # under cost_efficiency (charges first) -- they must differ on sold/bought MWh here.
    assert same_obj["sold_mwh"] != fixed_cost["sold_mwh"] or same_obj["bought_mwh"] != fixed_cost["bought_mwh"]


def test_raw_applied_counter_split_and_headline_uses_raw():
    # A decision whose RAW proposal violates a rule the balancer then repairs away: raw ==
    # fail/flagged, applied == pass. The two counters must disagree, and the headline
    # (first_attempt_pass_rate_pct) must reflect the RAW count, not the applied one.
    scenario = _tick88_scenario(tick=3, seed=303, total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=5.0)  # surplus 11.7MW
    # Propose charging 0.15MW beyond the renewable surplus (> GRID_CHARGE_CAP_TOLERANCE_MW of
    # 0.1 -- rule_11 flags the raw proposal) plus a matching 0.15MW purchase so load stays
    # fully served either way (isolates rule_11 from rule_3). The balancer caps the charge by
    # 0.15MW and then drops the now-unneeded 0.15MW purchase (Phase A.5) -- 0.3MW of total
    # repair, under REPAIR_TOLERANCE_MW (0.5), so the applied decision stays clean.
    # Split across both batteries so neither battery's OWN charge-rate limit binds (battery_1's
    # 10.0MW rate cap alone would trigger a much bigger, unrelated repair) -- only the shared
    # surplus budget is exceeded, by exactly 0.15MW.
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=10.0), BatteryAction(battery_id="battery_2", action="charge", amount_mw=1.85)],
        market_action="buy", market_amount_mw=0.15,
    )
    result = reevaluate_stored(scenario, proposal)
    raw_status = next(s for s in result.stages if s.name == "raw").evaluation.status
    applied_status = next(s for s in result.stages if s.name == "applied").evaluation.status
    assert raw_status != EvalStatus.PASS
    assert applied_status == EvalStatus.PASS  # sanity: the fixture actually exercises the raw/applied split

    report = build_day_report([scenario], [result])
    vs = report["verdict_summary"]
    assert vs["counts_first_attempt_raw"]["pass"] == 0
    assert vs["counts_applied_after_repair"]["pass"] == 1
    assert vs["first_attempt_pass_rate_pct"] == 0.0  # headline is the raw count
    assert vs["applied_pass_rate_pct"] == 100.0


def test_regression_report_must_be_built_from_a_rescored_result_not_a_frozen_one():
    # The exact bug class from this morning: day_report_build.py originally read each stored
    # row's `evaluation` field as-is (frozen at recording time) instead of re-scoring the raw
    # proposal via pipeline.reevaluate_stored -- so a prompt/rule fix that changed a verdict
    # never showed up in a regenerated report, while the report looked freshly built.
    #
    # Uses the real rule_8c bug this session found and fixed: a FILE_INPUT scenario with a
    # raised floor at a high price used to be flagged (the generator-tag-gated threshold
    # never recognized FILE_INPUT's price); current code correctly passes it.
    row = dict(file_input.EXAMPLE_DAY_ROWS[7])  # the price-spike row, price 165 >= threshold
    scenario = file_input.row_to_scenario(row, 7)
    assert scenario.electricity_price_per_mwh >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    shortfall = scenario.total_demand_mw - (scenario.solar_output_mw + scenario.wind_output_mw)  # 32.0MW here
    proposal = _decision(
        tick=scenario.tick, proposed_floor_pct=37.5, applied_floor_pct=37.5,
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="buy", market_amount_mw=round(shortfall, 1),  # fully served via import -- isolates the floor/rule_8c behavior from rule_3
    )

    # 1) A STALE stored result: the same scenario + raw proposal, but with a hand-forced
    #    "frozen" applied evaluation claiming rule_8c failed -- simulating exactly what was on
    #    disk before the fix (status FLAGGED, rule_8c not passed).
    stale_rule_8c = RuleResult(rule_id="rule_8c", description="stale", severity="flagged", passed=False, applicable=True, detail="stale, pre-fix")
    stale_eval = EvalResult(tick=scenario.tick, status=EvalStatus.FLAGGED, rules=[stale_rule_8c], notes="stale")
    stale_result = ScenarioRunResult(
        scenario=scenario,
        stages=[DecisionStage(name="raw", decision=proposal, evaluation=stale_eval), DecisionStage(name="applied", decision=proposal, evaluation=stale_eval)],
        repairs=[], repaired=False,
    )

    # 2) The CORRECT pipeline: re-score the same raw proposal under current rules.
    rescored_result = reevaluate_stored(scenario, proposal)

    stale_report = build_day_report([scenario], [stale_result])
    rescored_report = build_day_report([scenario], [rescored_result])

    # build_day_report is a pure aggregator -- feeding it a stale frozen evaluation produces a
    # stale report (this is the bug, reproduced on purpose to prove the test can catch it)...
    assert stale_report["per_tick"][0]["verdict"]["applied"] == "flagged"
    assert "rule_8c" in stale_report["per_tick"][0]["verdict"]["failing_rules"]
    # ...while the correct pipeline (reevaluate_stored first, as day_report_build.py and the
    # /file-input/day-report route both now do) reflects CURRENT rules winning: rule_8c passes.
    assert rescored_report["per_tick"][0]["verdict"]["applied"] == "pass"
    assert rescored_report["per_tick"][0]["verdict"]["failing_rules"] == []
    assert rescored_report["verdict_summary"]["counts_first_attempt_raw"]["pass"] == 1

    # The two reports must disagree -- if they didn't, this test wouldn't be testing anything.
    assert stale_report["verdict_summary"]["counts_first_attempt_raw"] != rescored_report["verdict_summary"]["counts_first_attempt_raw"]


def test_report_to_csv_contains_the_same_row_count():
    scenario = _tick88_scenario(tick=1, seed=1, total_demand_mw=90.0, total_demand_forecast_mw=90.0)
    result = reevaluate_stored(scenario, _surplus_decision_charge(scenario, 5.0))
    report = build_day_report([scenario], [result])
    csv_text = report_to_csv(report)
    # header + 1 data row
    assert len(csv_text.strip().splitlines()) == 2
