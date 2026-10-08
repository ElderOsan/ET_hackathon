#!/usr/bin/env python
"""Builds the day report from the stored evidence/day_report_example_agent_results.json
(written by day_report_run.py) and exports JSON + CSV. No model calls -- the baseline
comparison uses the deterministic dispatcher directly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.day_report import build_day_report, report_to_csv, report_to_json
from app.models.schemas import EnvironmentState, ScenarioRunResult

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "day_report_example"
ROOT = Path(__file__).resolve().parents[2]
raw = json.loads((ROOT / "evidence" / f"{RUN_ID}_agent_results.json").read_text())
results = [ScenarioRunResult(**r) for r in raw]
scenarios = [r.scenario for r in results]

report = build_day_report(scenarios, results)

(ROOT / "evidence" / f"{RUN_ID}.json").write_text(report_to_json(report))
(ROOT / "evidence" / f"{RUN_ID}.csv").write_text(report_to_csv(report))

print(f"rows: {report['row_count']}")
print(f"verdict counts (first attempt, raw, headline): {report['verdict_summary']['counts_first_attempt_raw']} ({report['verdict_summary']['first_attempt_pass_rate_pct']}% pass)")
print(f"verdict counts (applied, after repair): {report['verdict_summary']['counts_applied_after_repair']} ({report['verdict_summary']['applied_pass_rate_pct']}% pass)")
print(f"rule fire counts: {report['verdict_summary']['rule_fire_counts']}")
print(f"cumulative agent: {report['cumulative']['agent']}")
print(f"cumulative same_objective_baseline: {report['cumulative']['same_objective_baseline']}")
print(f"cumulative fixed_cost_baseline: {report['cumulative']['fixed_cost_baseline']}")
print(f"mean renewable utilisation: {report['cumulative']['mean_renewable_utilisation_pct']}%")
print("comparison (agent vs same-objective dispatcher vs fixed-cost dispatcher):")
for k, v in report["comparison"].items():
    print(
        f"  {k}: agent={v['agent']} same_objective={v['same_objective_baseline']} fixed_cost={v['fixed_cost_baseline']}"
        f" | agent-vs-same_objective diff={v['diff_agent_vs_same_objective']} pct={v['pct_agent_vs_same_objective']}"
        f" | same_objective-vs-fixed_cost diff={v['diff_same_objective_vs_fixed_cost']} pct={v['pct_same_objective_vs_fixed_cost']}"
    )
print(f"\nwrote evidence/{RUN_ID}.json and evidence/{RUN_ID}.csv")
