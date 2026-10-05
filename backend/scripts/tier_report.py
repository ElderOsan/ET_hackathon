#!/usr/bin/env python
"""Generalized tier report: agent-only headline, safe-mode shown separately, per Patch 3
Step 4. Usage: python scripts/tier_report.py <benchmark_json_path>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1])
data = json.load(open(path))
tiers = json.load(open(ROOT / "evidence" / "exit_tiers.json"))
results = data["results"]
assert len(results) == 72

STABLE_SURPLUS_SHORTFALL = {"stable_day", "surplus_day", "shortfall_day"}


def raw_status(r):
    return next(s for s in r["stages"] if s["name"] == "raw")["evaluation"]["status"]


def applied_status(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["evaluation"]["status"]


def applied_rules(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["evaluation"]["rules"]


def mode(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["decision"]["mode"]


agent_rows = [r for r in results if mode(r) == "agent"]
safe_rows = [r for r in results if mode(r) == "safe_mode"]
unresolved_rows = [r for r in results if mode(r) not in ("agent", "safe_mode")]
n = len(agent_rows)

first_attempt_pass = sum(1 for r in agent_rows if raw_status(r) == "pass")
subset = [r for r in agent_rows if r["scenario"]["difficulty"] in STABLE_SURPLUS_SHORTFALL]
subset_pass = sum(1 for r in subset if raw_status(r) == "pass")
non_fail = sum(1 for r in agent_rows if applied_status(r) != "fail")
avoidable_unserved = sum(1 for r in agent_rows if any(x["rule_id"] == "rule_3" and not x["passed"] and x["applicable"] for x in applied_rules(r)))

by_obj_18 = {}
by_obj_rule9 = {}
for r in agent_rows:
    obj = r["scenario"]["objective"] or "none"
    by_obj_18.setdefault(obj, []).append(r)
    rule9 = next((x for x in applied_rules(r) if x["rule_id"] == "rule_9"), None)
    if rule9 is not None and rule9.get("applicable", True):
        by_obj_rule9.setdefault(obj, []).append(r)
per_obj_18 = {o: sum(1 for r in rows if applied_status(r) == "pass") for o, rows in by_obj_18.items()}
per_obj_rule9 = {o: (sum(1 for r in rows if applied_status(r) == "pass"), len(rows)) for o, rows in by_obj_rule9.items()}

inconsistencies = [
    (r["scenario"]["tick"], r["scenario"]["seed"], raw_status(r), applied_status(r))
    for r in agent_rows if not r["repairs"] and raw_status(r) != applied_status(r)
]

non_pass_rows = []
for r in results:  # includes safe-mode and unresolved rows too, for completeness
    st = applied_status(r)
    if st != "pass":
        failing = [x["rule_id"] for x in applied_rules(r) if not x["passed"] and x["applicable"]]
        non_pass_rows.append({
            "tick": r["scenario"]["tick"], "seed": r["scenario"]["seed"],
            "profile": r["scenario"]["difficulty"], "objective": r["scenario"]["objective"] or "none",
            "status": st, "mode": mode(r), "failing_rules": failing,
        })

safe_mode_pass = sum(1 for r in safe_rows if applied_status(r) == "pass")

print(f"=== Tier report: {path.name} (agent-only headline, n={n}; safe_mode n={len(safe_rows)}; unresolved n={len(unresolved_rows)}) ===")
print(f"1. Overall first-attempt pass (agent-only): {first_attempt_pass}/{n} = {round(100*first_attempt_pass/n,1) if n else 'n/a'}%")
print(f"2. stable+surplus+shortfall first-attempt pass (agent-only): {subset_pass}/{len(subset)} = {round(100*subset_pass/len(subset),1) if subset else 'n/a'}%")
print(f"3. Non-fail rate (applied, agent-only): {non_fail}/{n} = {round(100*non_fail/n,1) if n else 'n/a'}%")
print("4. Per-objective applied PASS counts (agent-only), all rows:")
for obj, cnt in per_obj_18.items():
    print(f"   {obj:28s} {cnt}/{len(by_obj_18[obj])}")
print("   Per-objective applied PASS counts (agent-only), active rule_9 rows only:")
for obj, (cnt, total) in per_obj_rule9.items():
    print(f"   {obj:28s} {cnt}/{total}")
print(f"5. Avoidable-unserved (agent-only): {avoidable_unserved}/{n} = {round(100*avoidable_unserved/n,1) if n else 'n/a'}%")
print(f"6a. Safe mode: {len(safe_rows)} row(s), pass {safe_mode_pass}/{len(safe_rows)}" if safe_rows else "6a. Safe mode: 0 rows this run")
print(f"6e. Verdict inconsistencies (agent-only, empty-repair rows): {len(inconsistencies)} -- {inconsistencies}")
print(f"6d. Non-pass rows (all modes, {len(non_pass_rows)}):")
for row in non_pass_rows:
    print(f"   {row}")

out = {
    "source": str(path), "agent_n": n, "safe_mode_n": len(safe_rows), "unresolved_n": len(unresolved_rows),
    "first_attempt_pass": {"count": first_attempt_pass, "of": n},
    "stable_surplus_shortfall_pass": {"count": subset_pass, "of": len(subset)},
    "non_fail_rate": {"count": non_fail, "of": n},
    "per_objective_18": per_obj_18,
    "per_objective_rule9_active": per_obj_rule9,
    "avoidable_unserved": {"count": avoidable_unserved, "of": n},
    "safe_mode": {"count": len(safe_rows), "passed": safe_mode_pass},
    "verdict_inconsistencies": inconsistencies,
    "non_pass_rows": non_pass_rows,
}
out_path = ROOT / "evidence" / f"{path.stem.replace('_benchmark','')}_tier_report.json"
out_path.write_text(json.dumps(out, indent=2))
print(f"\nwrote {out_path}")
