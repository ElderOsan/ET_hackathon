#!/usr/bin/env python
"""Patch 3 addendum: `reevaluate` -- re-score stored raw proposals under the CURRENT rules,
balancer and physics code, with NO model calls. This is how a rule change is tested against
old results: load a JSONL of previously-recorded ScenarioRunResults (one per line, the same
shape evidence/patch2_runs.jsonl is in), take each row's RAW proposal, and re-run it through
today's code via pipeline.reevaluate_stored. The scenario and the raw proposal are facts from
the past; only the verdicts are recomputed.

Usage:
    python scripts/reevaluate.py evidence/patch2_runs.jsonl --out evidence/patch2_reeval.json
    python scripts/reevaluate.py evidence/patch2_runs.jsonl --before brief2_patch2_benchmark.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import reevaluate_stored
from app.api.routes import _summarize
from app.models.schemas import Decision, EnvironmentState, Objective, ScenarioRunResult


def load_jsonl(path: Path) -> list[ScenarioRunResult]:
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            results.append(ScenarioRunResult(**json.loads(line)))
    return results


def reevaluate_all(stored: list[ScenarioRunResult]) -> list[ScenarioRunResult]:
    out = []
    for r in stored:
        raw_stage = next(s for s in r.stages if s.name == "raw")
        scenario: EnvironmentState = r.scenario
        proposal: Decision = raw_stage.decision
        out.append(reevaluate_stored(scenario, proposal))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsonl", help="Path to a JSONL file of stored ScenarioRunResults (raw proposals reused, no model calls).")
    parser.add_argument("--out", default=None, help="Write the full re-evaluated BatchRunSummary here (JSON).")
    parser.add_argument("--before", default=None, help="An existing BatchRunSummary JSON to diff against (verdict-change counts only).")
    args = parser.parse_args()

    stored = load_jsonl(Path(args.jsonl))
    print(f"loaded {len(stored)} stored rows from {args.jsonl} (no model calls)")

    reevaluated = reevaluate_all(stored)
    # base_seed is informational only here -- the actual scenarios came from the stored
    # rows, not from re-generating a matrix, so there's no single seed that reproduces this.
    summary = _summarize(reevaluated, base_seed=0, seed_set_name="reevaluated", objectives=list(Objective))

    judged = summary.judged_count
    print(f"total={summary.total} infeasible={summary.infeasible_count} judged={judged} margin_infeasible={summary.margin_infeasible_count}")
    print(f"na_counts_by_rule={summary.na_counts_by_rule}")
    print(f"first_attempt_pass_rate={summary.first_attempt_pass_rate_pct}% ({summary.first_attempt_passed}/{judged})")
    print(f"applied_pass_rate={summary.applied_pass_rate_pct}% ({summary.applied_passed}/{judged}) failed={summary.applied_failed} flagged={summary.applied_flagged}")
    print(f"repair_rate={summary.repair_rate_pct}%")

    if args.before:
        before_data = json.load(open(args.before))
        before_by_seed = {r["scenario"]["seed"]: r for r in before_data["results"]}
        changed = []
        for r in reevaluated:
            prev = before_by_seed.get(r.scenario.seed)
            if not prev:
                continue
            prev_applied_status = next(s for s in prev["stages"] if s["name"] == "applied")["evaluation"]["status"]
            new_applied = next(s for s in r.stages if s.name == "applied")
            if new_applied.evaluation.status.value != prev_applied_status:
                changed.append((r.scenario.tick, r.scenario.seed, prev_applied_status, new_applied.evaluation.status.value))
        print(f"\nverdict changes vs {args.before}: {len(changed)}")
        for tick, seed, old, new in changed:
            print(f"  tick={tick} seed={seed}: {old} -> {new}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary.model_dump(mode="json"), f, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
