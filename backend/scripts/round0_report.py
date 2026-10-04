#!/usr/bin/env python
"""Round 0 tier report: every one of the 72 scenarios in the denominator (no judged_count /
agent-only exclusion), exactly as instructed -- the stored BatchRunSummary's own headline
fields exclude safe_mode rows, so this recomputes from the raw results list instead.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
data = json.load(open(ROOT / "evidence" / "round0_benchmark.json"))
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


def raw_rules(r):
    return next(s for s in r["stages"] if s["name"] == "raw")["evaluation"]["rules"]


def mode(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["decision"]["mode"]


# ---- 1. Overall first-attempt pass (raw stage, all 72) ------------------------------------
first_attempt_pass = sum(1 for r in results if raw_status(r) == "pass")

# ---- 2. stable + surplus + shortfall subset, first-attempt pass ---------------------------
subset = [r for r in results if r["scenario"]["difficulty"] in STABLE_SURPLUS_SHORTFALL]
subset_pass = sum(1 for r in subset if raw_status(r) == "pass")

# ---- 3. Non-fail rate (applied stage, all 72): pass or flagged, not fail ------------------
non_fail = sum(1 for r in results if applied_status(r) != "fail")

# ---- 4. Per-objective applied-stage passes, all 18 rows, and over active rule_9 rows -------
by_objective_18 = {}
by_objective_rule9_active = {}
for r in results:
    obj = r["scenario"]["objective"] or "none"
    by_objective_18.setdefault(obj, []).append(r)
    rule9 = next((x for x in applied_rules(r) if x["rule_id"] == "rule_9"), None)
    if rule9 is not None and rule9.get("applicable", True):
        by_objective_rule9_active.setdefault(obj, []).append(r)

per_objective_18 = {obj: sum(1 for r in rows if applied_status(r) == "pass") for obj, rows in by_objective_18.items()}
per_objective_rule9 = {obj: (sum(1 for r in rows if applied_status(r) == "pass"), len(rows)) for obj, rows in by_objective_rule9_active.items()}

# ---- 5. Avoidable-unserved: applied-stage rule_3 failures / 72 -----------------------------
avoidable_unserved = sum(1 for r in results if any(x["rule_id"] == "rule_3" and not x["passed"] and x["applicable"] for x in applied_rules(r)))

# ---- 6. Safe mode demonstrated -------------------------------------------------------------
safe_mode_rows = [r for r in results if mode(r) == "safe_mode"]

# ---- 7. Zero verdict inconsistencies (empty repair log -> raw/applied verdict must agree) --
inconsistencies = [
    (r["scenario"]["tick"], r["scenario"]["seed"], raw_status(r), applied_status(r))
    for r in results if not r["repairs"] and raw_status(r) != applied_status(r)
]

# ---- 8. Every non-pass classified: list every applied-stage non-pass with its failing rules
non_pass_rows = []
for r in results:
    st = applied_status(r)
    if st != "pass":
        failing = [x["rule_id"] for x in applied_rules(r) if not x["passed"] and x["applicable"]]
        non_pass_rows.append({
            "tick": r["scenario"]["tick"], "seed": r["scenario"]["seed"],
            "profile": r["scenario"]["difficulty"], "objective": r["scenario"]["objective"] or "none",
            "status": st, "mode": mode(r), "failing_rules": failing,
        })

print("=== Round 0: 72-scenario denominator ===")
print(f"1. Overall first-attempt pass: {first_attempt_pass}/72 = {round(100*first_attempt_pass/72,1)}%")
print(f"2. stable+surplus+shortfall first-attempt pass: {subset_pass}/{len(subset)} = {round(100*subset_pass/len(subset),1)}%")
print(f"3. Non-fail rate (applied): {non_fail}/72 = {round(100*non_fail/72,1)}%")
print("4. Per-objective applied PASS counts, all 18 rows:")
for obj, n in per_objective_18.items():
    print(f"   {obj:28s} {n}/18")
print("   Per-objective applied PASS counts, active rule_9 rows only:")
for obj, (n, total) in per_objective_rule9.items():
    print(f"   {obj:28s} {n}/{total}")
print(f"5. Avoidable-unserved (applied rule_3 fail): {avoidable_unserved}/72 = {round(100*avoidable_unserved/72,1)}%")
print(f"6. Safe mode demonstrated: {len(safe_mode_rows)} row(s) -- {[ (r['scenario']['tick'], r['scenario']['seed']) for r in safe_mode_rows]}")
print(f"7. Verdict inconsistencies: {len(inconsistencies)} -- {inconsistencies}")
print(f"8. Non-pass rows ({len(non_pass_rows)}):")
for row in non_pass_rows:
    print(f"   {row}")

out = {
    "first_attempt_pass": {"count": first_attempt_pass, "of": 72},
    "stable_surplus_shortfall_pass": {"count": subset_pass, "of": len(subset)},
    "non_fail_rate": {"count": non_fail, "of": 72},
    "per_objective_18": per_objective_18,
    "per_objective_rule9_active": per_objective_rule9,
    "avoidable_unserved": {"count": avoidable_unserved, "of": 72},
    "safe_mode_rows": [(r["scenario"]["tick"], r["scenario"]["seed"]) for r in safe_mode_rows],
    "verdict_inconsistencies": inconsistencies,
    "non_pass_rows": non_pass_rows,
}
(ROOT / "evidence" / "round0_tier_report.json").write_text(json.dumps(out, indent=2))
print(f"\nwrote {ROOT / 'evidence' / 'round0_tier_report.json'}")
