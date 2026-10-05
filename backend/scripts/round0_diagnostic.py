#!/usr/bin/env python
"""Round 0 diagnostic (no model calls): items 1-4 and 6 of the user's diagnostic request,
computed entirely from the stored evidence/round0_benchmark.json and a fresh (but
model-call-free) reference_dispatch/dispatch call per scenario.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import physics
from app.data.balancer import reference_dispatch
from app.data.dispatcher import dispatch
from app.models.schemas import Decision, EnvironmentState, Objective

ROOT = Path(__file__).resolve().parents[2]
data = json.load(open(ROOT / "evidence" / "round0_benchmark.json"))
results = data["results"]

TARGET_TICKS = {10, 11, 12, 27, 28, 31, 34, 35, 36, 58, 59, 60}  # rule_9 max_profit (9) + rule_5 (4); 28/31 are rule_8b only, kept out below
RULE9_TICKS = {10, 11, 12, 34, 35, 36, 58, 59, 60}
RULE5_TICKS = {27, 34, 35, 36}


def battery_summary(actions):
    charge = round(sum(a["amount_mw"] for a in actions if a["action"] == "charge"), 1)
    discharge = round(sum(a["amount_mw"] for a in actions if a["action"] == "discharge"), 1)
    return charge, discharge


def row_by_tick(tick):
    return next(r for r in results if r["scenario"]["tick"] == tick)


print("=== Item 1: actual vs reference MW (sale/charge/discharge), sellable surplus ===")
for tick in sorted(RULE9_TICKS | RULE5_TICKS):
    r = row_by_tick(tick)
    scenario = EnvironmentState(**r["scenario"])
    applied = next(s for s in r["stages"] if s["name"] == "applied")
    decision_dict = applied["decision"]
    applied_floor = decision_dict["applied_floor_pct"]
    ref = reference_dispatch(scenario, applied_floor)

    model_charge, model_discharge = battery_summary(decision_dict["battery_actions"])
    model_sale = decision_dict["market_amount_mw"] if decision_dict["market_action"] == "sell" else 0.0
    model_buy = decision_dict["market_amount_mw"] if decision_dict["market_action"] == "buy" else 0.0

    from app.data.dispatcher import dispatch_at_floor
    best = dispatch_at_floor(scenario, scenario.objective, applied_floor)
    ref_charge, ref_discharge = battery_summary([a.model_dump() for a in best.battery_actions])
    ref_sale = best.market_amount_mw if best.market_action == "sell" else 0.0
    ref_buy = best.market_amount_mw if best.market_action == "buy" else 0.0

    sellable = ref["renewable_surplus_mw"]
    max_sellable = ref["max_sellable_mw"]

    if model_sale > 0 and model_charge > 0:
        behavior = "sold part, charged part"
    elif model_sale > 0:
        behavior = "sold (no charge)"
    elif model_charge > 0:
        behavior = "charged, sold nothing"
    else:
        behavior = "held (no sale, no charge)"

    print(f"tick={tick:3d} {scenario.difficulty.value:22s} obj={scenario.objective.value if scenario.objective else 'none':26s} "
          f"MODEL: sell={model_sale:6.1f} buy={model_buy:6.1f} charge={model_charge:6.1f} discharge={model_discharge:6.1f} [{behavior}] | "
          f"REF: sell={ref_sale:6.1f} buy={ref_buy:6.1f} charge={ref_charge:6.1f} discharge={ref_discharge:6.1f} | "
          f"renewable_surplus={sellable:6.1f} max_sellable={max_sellable:6.1f}")

print("\n=== Item 2: full profit breakdown, model vs reference ===")
for tick in sorted(RULE9_TICKS | RULE5_TICKS):
    r = row_by_tick(tick)
    scenario = EnvironmentState(**r["scenario"])
    applied = next(s for s in r["stages"] if s["name"] == "applied")
    decision_dict = applied["decision"]
    decision = Decision(**decision_dict)
    applied_floor = decision_dict["applied_floor_pct"]

    from app.data.dispatcher import dispatch_at_floor
    best = dispatch_at_floor(scenario, scenario.objective, applied_floor)

    model_profit = physics.decision_profit(scenario, decision)
    ref_profit = physics.decision_profit(scenario, best)

    print(f"tick={tick:3d} {scenario.difficulty.value:22s} obj={scenario.objective.value if scenario.objective else 'none'}")
    print(f"   MODEL: revenue={model_profit['revenue']:8.1f} cost={model_profit['cost']:8.1f} stored_energy_mwh={model_profit['stored_energy_mwh']:6.2f} stored_value={model_profit['stored_energy_value']:8.1f} net_profit={model_profit['net_profit']:8.1f}")
    print(f"   REF:   revenue={ref_profit['revenue']:8.1f} cost={ref_profit['cost']:8.1f} stored_energy_mwh={ref_profit['stored_energy_mwh']:6.2f} stored_value={ref_profit['stored_energy_value']:8.1f} net_profit={ref_profit['net_profit']:8.1f}")

print("\n=== Item 3: does the reference ever discharge to sell under max_profit? ===")
discharge_and_sell_rows = []
discharge_rows_maxprofit = []
for r in results:
    scenario = EnvironmentState(**r["scenario"])
    if scenario.objective != Objective.MAX_PROFIT:
        continue
    applied = next(s for s in r["stages"] if s["name"] == "applied")
    applied_floor = applied["decision"]["applied_floor_pct"]
    from app.data.dispatcher import dispatch_at_floor
    best = dispatch_at_floor(scenario, scenario.objective, applied_floor)
    charge, discharge = battery_summary([a.model_dump() for a in best.battery_actions])
    sells = best.market_action == "sell" and best.market_amount_mw > 0
    if discharge > 0:
        discharge_rows_maxprofit.append((scenario.tick, discharge, sells))
    if discharge > 0 and sells:
        discharge_and_sell_rows.append((scenario.tick, discharge, best.market_amount_mw))

print(f"max_profit rows where reference discharges at all: {len(discharge_rows_maxprofit)} -- {discharge_rows_maxprofit}")
print(f"max_profit rows where reference discharges AND sells in the same tick: {len(discharge_and_sell_rows)} -- {discharge_and_sell_rows}")
print("Valuation when it DOES discharge: physics.net_stored_energy_change_mwh subtracts discharged MWh (no efficiency factor)")
print("from the net total, and physics.decision_profit values that net MWh at sell_price_per_mwh -- so a discharge is a debit")
print("against stored_energy_value using the SAME per-MWh price a charge is credited at. This is the same shared function for")
print("both model and reference decisions -- there is only one implementation, so there is no separate 'reference-side' rule.")

print("\n=== Item 4: agent-only / safe-mode-only pass rates per tier line ===")
STABLE_SURPLUS_SHORTFALL = {"stable_day", "surplus_day", "shortfall_day"}


def mode_of(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["decision"]["mode"]


def raw_status(r):
    return next(s for s in r["stages"] if s["name"] == "raw")["evaluation"]["status"]


def applied_status(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["evaluation"]["status"]


def applied_rules(r):
    return next(s for s in r["stages"] if s["name"] == "applied")["evaluation"]["rules"]


agent_rows = [r for r in results if mode_of(r) == "agent"]
safe_rows = [r for r in results if mode_of(r) == "safe_mode"]
print(f"agent rows: {len(agent_rows)}, safe_mode rows: {len(safe_rows)} (of 72 total)")

for label, rows in (("AGENT", agent_rows), ("SAFE_MODE", safe_rows)):
    n = len(rows)
    if n == 0:
        print(f"{label}: 0 rows -- n/a")
        continue
    fap = sum(1 for r in rows if raw_status(r) == "pass")
    subset = [r for r in rows if r["scenario"]["difficulty"] in STABLE_SURPLUS_SHORTFALL]
    subset_pass = sum(1 for r in subset if raw_status(r) == "pass")
    non_fail = sum(1 for r in rows if applied_status(r) != "fail")
    avoid_unserved = sum(1 for r in rows if any(x["rule_id"] == "rule_3" and not x["passed"] and x["applicable"] for x in applied_rules(r)))
    print(f"{label} (n={n}):")
    print(f"  first-attempt pass: {fap}/{n} = {round(100*fap/n,1) if n else 0}%")
    print(f"  stable+surplus+shortfall first-attempt pass: {subset_pass}/{len(subset)} = {round(100*subset_pass/len(subset),1) if subset else 'n/a (0 rows)'}%")
    print(f"  non-fail rate (applied): {non_fail}/{n} = {round(100*non_fail/n,1)}%")
    print(f"  avoidable-unserved: {avoid_unserved}/{n} = {round(100*avoid_unserved/n,1)}%")
    by_obj = {}
    for r in rows:
        obj = r["scenario"]["objective"] or "none"
        by_obj.setdefault(obj, [0, 0])
        by_obj[obj][1] += 1
        if applied_status(r) == "pass":
            by_obj[obj][0] += 1
    print(f"  per-objective applied passes: {by_obj}")

print("\n=== Item 6: dispatcher-as-oracle (200 scenarios) from Step 6 evidence ===")
step6 = json.load(open(ROOT / "evidence" / "step6_evidence.json"))
oracle = step6["oracle_and_baselines"]["oracle (dispatcher)"]
print(f"oracle pass rate: {oracle['passed']}/{oracle['total']} = {oracle['pct']}%")
print("The 33 shortfall_day rule_8b/8c floor-band mismatches found in the earlier debug run DID count as non-passes")
print("(rule_8b/8c are both severity='flagged', and EvalStatus.FLAGGED is not EvalStatus.PASS -- the oracle pass rate")
print("counts only status=='pass' rows, so a flagged-but-not-failed row is correctly excluded from the numerator).")
