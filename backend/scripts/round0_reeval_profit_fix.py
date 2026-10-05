#!/usr/bin/env python
"""Re-scores the stored Round 0 raw proposals under the fixed profit formula (no model
calls -- pipeline.reevaluate_stored). Reports every verdict change against the original
evidence/round0_benchmark.json. These are PROJECTIONS against stored data, not a fresh
benchmark -- no new scenario or model call is made.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import reevaluate_stored
from app.models.schemas import Decision, EnvironmentState

ROOT = Path(__file__).resolve().parents[2]
data = json.load(open(ROOT / "evidence" / "round0_benchmark.json"))
results = data["results"]


def status_of(result_stages, name):
    return next(s for s in result_stages if s["name"] == name)["evaluation"]["status"]


def rules_of(result_stages, name):
    return next(s for s in result_stages if s["name"] == name)["evaluation"]["rules"]


changes = []
for r in results:
    scenario = EnvironmentState(**r["scenario"])
    raw_decision = Decision(**next(s for s in r["stages"] if s["name"] == "raw")["decision"])
    old_raw_status = status_of(r["stages"], "raw")
    old_applied_status = status_of(r["stages"], "applied")

    new_result = reevaluate_stored(scenario, raw_decision)
    new_raw = next(s for s in new_result.stages if s.name == "raw")
    new_applied = next(s for s in new_result.stages if s.name == "applied")

    row_changed = False
    detail = {"tick": r["scenario"]["tick"], "seed": r["scenario"]["seed"], "profile": r["scenario"]["difficulty"], "objective": r["scenario"]["objective"] or "none"}

    if new_raw.evaluation.status.value != old_raw_status:
        detail["raw_status"] = f"{old_raw_status} -> {new_raw.evaluation.status.value}"
        row_changed = True
    if new_applied.evaluation.status.value != old_applied_status:
        detail["applied_status"] = f"{old_applied_status} -> {new_applied.evaluation.status.value}"
        row_changed = True

    old_applied_rules = {x["rule_id"]: x["passed"] for x in rules_of(r["stages"], "applied")}
    new_applied_rules = {x.rule_id: x.passed for x in new_applied.evaluation.rules}
    rule_changes = {rid: (old_applied_rules.get(rid), new_applied_rules.get(rid)) for rid in new_applied_rules if old_applied_rules.get(rid) != new_applied_rules.get(rid)}
    if rule_changes:
        detail["rule_changes"] = rule_changes
        row_changed = True

    if row_changed:
        changes.append(detail)

print(f"=== Projection only: re-scored {len(results)} stored Round 0 raw proposals under the fixed profit formula ===")
print(f"{len(changes)} row(s) with a verdict or per-rule change:")
for c in changes:
    print(" ", c)

out = {"note": "PROJECTION against stored Round 0 data under the fixed profit formula -- not a fresh benchmark, not new evidence.", "total_rows": len(results), "changed_rows": len(changes), "changes": changes}
(ROOT / "evidence" / "round0_profit_fix_reeval.json").write_text(json.dumps(out, indent=2))
print(f"\nwrote {ROOT / 'evidence' / 'round0_profit_fix_reeval.json'}")
