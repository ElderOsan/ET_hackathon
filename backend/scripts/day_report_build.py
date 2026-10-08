#!/usr/bin/env python
"""Builds the day report from the stored evidence/<run_id>_agent_results.json (written by
day_report_run.py) and exports JSON + CSV. No model calls -- the baseline comparison uses the
deterministic dispatcher directly.

Each stored row's RAW proposal is re-scored under today's balancer/rules/physics code via
pipeline.reevaluate_stored before the report is built -- the stored file's own `evaluation`
field is frozen at recording time and must never be read directly here, or a rule/balancer
change made after the recording would silently not show up in this report. build_day_report()
itself is a pure aggregator and does NOT do this re-scoring (see day_report.py's own tests) --
build_report_for_run() below is the one place that must, and
backend/tests/test_day_report_build.py tests it directly, at the layer the staleness bug
actually lived in, not just build_day_report()'s own (true, but narrower) pure-function
contract.

Usage: python scripts/day_report_build.py [run_id]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import reevaluate_stored
from app.data.day_report import build_day_report, report_to_csv, report_to_json
from app.models.schemas import ScenarioRunResult

ROOT = Path(__file__).resolve().parents[2]


def build_report_for_run(run_id: str, evidence_dir: Path | None = None) -> dict:
    """Loads evidence_dir/<run_id>_agent_results.json, re-scores every row's RAW proposal
    under CURRENT code (never trusts the frozen `evaluation` on disk), builds the day report,
    writes <run_id>.json/.csv into the same directory, and returns the report dict.
    evidence_dir defaults to the repo's real evidence/ directory; tests pass a tmp_path so
    nothing touches it."""
    evidence_dir = evidence_dir or (ROOT / "evidence")
    raw = json.loads((evidence_dir / f"{run_id}_agent_results.json").read_text())
    stored = [ScenarioRunResult(**r) for r in raw]
    raw_proposals = [next(s.decision for s in r.stages if s.name == "raw") for r in stored]
    results = [reevaluate_stored(r.scenario, proposal) for r, proposal in zip(stored, raw_proposals)]
    scenarios = [r.scenario for r in results]

    report = build_day_report(scenarios, results)

    (evidence_dir / f"{run_id}.json").write_text(report_to_json(report))
    (evidence_dir / f"{run_id}.csv").write_text(report_to_csv(report))
    return report


def _print_summary(report: dict, run_id: str) -> None:
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
    print(f"\nwrote evidence/{run_id}.json and evidence/{run_id}.csv")


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else "day_report_example"
    report = build_report_for_run(run_id)
    _print_summary(report, run_id)


if __name__ == "__main__":
    main()
