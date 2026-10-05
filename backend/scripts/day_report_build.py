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
print(f"verdict counts: {report['verdict_summary']['counts']}")
print(f"rule fire counts: {report['verdict_summary']['rule_fire_counts']}")
print(f"cumulative agent: {report['cumulative']['agent']}")
print(f"cumulative baseline: {report['cumulative']['baseline']}")
print(f"mean renewable utilisation: {report['cumulative']['mean_renewable_utilisation_pct']}%")
print("comparison (agent vs baseline):")
for k, v in report["comparison_agent_vs_baseline"].items():
    print(f"  {k}: agent={v['agent']} baseline={v['baseline']} diff={v['diff']} pct={v['pct']}")
print(f"\nwrote evidence/{RUN_ID}.json and evidence/{RUN_ID}.csv")
