"""Regression test at the layer the staleness bug actually lived in: day_report_build.py's
build_report_for_run(), not day_report.build_day_report() itself.

day_report.py's own test (test_day_report.py) proves build_day_report() is a pure function of
whatever ScenarioRunResults it's given -- a true, useful property, but NOT the bug. The bug
was that the script read each stored row's frozen `evaluation` field directly instead of
calling pipeline.reevaluate_stored on the raw proposal first. If that call is ever removed
from build_report_for_run() again, this test -- unlike build_day_report()'s own pure-function
test -- must fail.
"""
from __future__ import annotations

import json

from app.data import file_input
from app.data.tuning import DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
from app.models.schemas import BatteryAction, DecisionStage, EvalResult, EvalStatus, RuleResult, ScenarioRunResult
from scripts.day_report_build import build_report_for_run
from tests.test_acceptance import _decision


def test_build_report_for_run_rescores_under_current_rules_not_the_frozen_evaluation(tmp_path):
    # The real rule_8c bug this session found and fixed: a FILE_INPUT scenario with a raised
    # floor at a high price used to be flagged (the generator-tag-gated threshold never
    # recognized FILE_INPUT's price); current code correctly passes it.
    row = dict(file_input.EXAMPLE_DAY_ROWS[7])  # the price-spike row, price 165
    scenario = file_input.row_to_scenario(row, 7)
    assert scenario.electricity_price_per_mwh >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    shortfall = scenario.total_demand_mw - (scenario.solar_output_mw + scenario.wind_output_mw)
    proposal = _decision(
        tick=scenario.tick, proposed_floor_pct=37.5, applied_floor_pct=37.5,
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="buy", market_amount_mw=round(shortfall, 1),
    )

    # Hand-build the ON-DISK shape with a deliberately STALE applied evaluation (rule_8c
    # failed) -- exactly what a pre-fix recording's evidence/<run_id>_agent_results.json
    # would contain. build_report_for_run must never read this evaluation.
    stale_rule_8c = RuleResult(rule_id="rule_8c", description="stale", severity="flagged", passed=False, applicable=True, detail="stale, pre-fix")
    stale_eval = EvalResult(tick=scenario.tick, status=EvalStatus.FLAGGED, rules=[stale_rule_8c], notes="stale")
    stored_result = ScenarioRunResult(
        scenario=scenario,
        stages=[DecisionStage(name="raw", decision=proposal, evaluation=stale_eval), DecisionStage(name="applied", decision=proposal, evaluation=stale_eval)],
        repairs=[], repaired=False,
    )

    run_id = "test_regression_run"
    (tmp_path / f"{run_id}_agent_results.json").write_text(json.dumps([stored_result.model_dump(mode="json")]))

    report = build_report_for_run(run_id, evidence_dir=tmp_path)

    # If this read the frozen evaluation (the bug), it would say "flagged" with rule_8c
    # failing. It must instead reflect current code: pass, no failing rules.
    assert report["per_tick"][0]["verdict"]["applied"] == "pass"
    assert report["per_tick"][0]["verdict"]["failing_rules"] == []
    assert report["verdict_summary"]["counts_first_attempt_raw"]["pass"] == 1
    assert report["verdict_summary"]["counts_first_attempt_raw"]["flagged"] == 0

    # And it must have actually written the files (the other half of what this function does).
    written_json = json.loads((tmp_path / f"{run_id}.json").read_text())
    assert written_json["per_tick"][0]["verdict"]["applied"] == "pass"
    assert (tmp_path / f"{run_id}.csv").exists()
