#!/usr/bin/env python
"""D.5 (finished) -- zero-call check of whether the two day-report baselines actually
diverge when the transmission/sell cap is NOT the binding constraint. The 12-row example
day's own ticks all have sellable_surplus_mw < total battery charge capacity there (12.0 <
16.0), so the sell cap binds under either ladder order and the baselines can never differ --
that result (see evidence/day_report_example.json / D.4) answers "not on this day," not the
actual D.5 question: does declaring an objective reach the dispatch at all?

This probe hand-builds (via model_copy on a real generated scenario, not a synthetic one
built field-by-field) a sweep of surplus states where sellable_surplus_mw > total charge
capacity -- using app/agents/scenario_agent.generate_scenario(D4_SURPLUS_DAY, seed=777001),
the same base state probe_ladder_reword.py already used (transmission_headroom_mw=180.0, so
sellable_surplus_mw == surplus for every surplus in this sweep -- the transmission cap is
never what's binding). Battery charge capacity there is fixed at 16.0 MW
(battery_1=10.0 + battery_2=6.0). Surplus is swept via total_demand_mw alone (solar/wind/
batteries/transmission/prices held fixed) from 0 to 60 MW in 2 MW steps -- 31 states,
covering below-both-caps, between-the-caps, and above-both-caps regions.

Both baselines are dispatch() + balance(), the exact same deterministic functions
day_report.build_day_report() calls -- zero model calls, nothing in app.agents.pipeline or
app.data.recording is imported. Separate probe; does not touch the 12-row day or its
recordings.

Usage: python scripts/probe_baseline_divergence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.scenario_agent import generate_scenario
from app.data import physics
from app.data.balancer import balance
from app.data.day_report import _row_ledger_entry
from app.data.dispatcher import dispatch
from app.data.tuning import TICK_HOURS
from app.models.schemas import Difficulty, Objective

ROOT = Path(__file__).resolve().parents[2]

base_scenario = generate_scenario(Difficulty.D4_SURPLUS_DAY, None, seed=777001)
generation = physics.total_generation_mw(base_scenario)
total_charge_cap = sum(physics.max_charge_mw(b) for b in base_scenario.batteries)
print(f"base: generation={generation:.1f}MW transmission_headroom={base_scenario.transmission_headroom_mw:.1f}MW "
      f"total_charge_cap={total_charge_cap:.1f}MW")
print(f"sweeping surplus 0-60MW via total_demand_mw (solar/wind/batteries/transmission/prices fixed)")
print()

SURPLUS_SWEEP = [s / 1.0 for s in range(0, 62, 2)]  # 0, 2, 4, ..., 60

rows = []
print(f"{'surplus':>8} {'sellable':>9} {'>cap?':>6} {'mp_sell':>8} {'mp_charge':>10} {'ce_sell':>8} {'ce_charge':>10} {'diverges':>9}")
for surplus in SURPLUS_SWEEP:
    sc = base_scenario.model_copy(update={"total_demand_mw": round(generation - surplus, 1)})
    sellable = physics.sellable_surplus_mw(sc)

    mp_decision = dispatch(sc, Objective.MAX_PROFIT)
    mp_applied, _ = balance(sc, mp_decision)
    ce_decision = dispatch(sc, Objective.COST_EFFICIENCY)
    ce_applied, _ = balance(sc, ce_decision)

    mp_sell = mp_applied.market_amount_mw if mp_applied.market_action == "sell" else 0.0
    mp_charge = round(sum(a.amount_mw for a in mp_applied.battery_actions if a.action == "charge"), 1)
    ce_sell = ce_applied.market_amount_mw if ce_applied.market_action == "sell" else 0.0
    ce_charge = round(sum(a.amount_mw for a in ce_applied.battery_actions if a.action == "charge"), 1)

    mp_entry = _row_ledger_entry(sc, mp_applied)
    ce_entry = _row_ledger_entry(sc, ce_applied)

    diverges = (
        mp_applied.market_action != ce_applied.market_action
        or abs(mp_applied.market_amount_mw - ce_applied.market_amount_mw) > 1e-6
        or [(a.battery_id, a.action, round(a.amount_mw, 3)) for a in mp_applied.battery_actions]
        != [(a.battery_id, a.action, round(a.amount_mw, 3)) for a in ce_applied.battery_actions]
    )

    rows.append({
        "surplus_mw": surplus, "sellable_surplus_mw": round(sellable, 1),
        "sellable_exceeds_charge_cap": sellable > total_charge_cap,
        "max_profit": {"sell_mw": mp_sell, "charge_mw": mp_charge, **{k: mp_entry[k] for k in ("cost", "profit", "emissions_tonnes", "curtailed_mw", "renewable_utilisation_pct")}},
        "cost_efficiency": {"sell_mw": ce_sell, "charge_mw": ce_charge, **{k: ce_entry[k] for k in ("cost", "profit", "emissions_tonnes", "curtailed_mw", "renewable_utilisation_pct")}},
        "diverges": diverges,
    })
    print(f"{surplus:>8.1f} {sellable:>9.1f} {str(sellable > total_charge_cap):>6} {mp_sell:>8.1f} {mp_charge:>10.1f} "
          f"{ce_sell:>8.1f} {ce_charge:>10.1f} {str(diverges):>9}")

diverging = [r for r in rows if r["diverges"]]
print()
print(f"diverging states: {len(diverging)}/{len(rows)}")

if diverging:
    def _diff(key, sub=None):
        vals = [abs((r["max_profit"][key] if sub is None else r["max_profit"][sub][key]) - (r["cost_efficiency"][key] if sub is None else r["cost_efficiency"][sub][key])) for r in diverging]
        return max(vals), round(sum(vals) / len(vals), 3)

    print()
    print("size of difference on diverging states only (max_profit vs cost_efficiency), max / mean absolute diff:")
    for key, label in (("cost", "cost"), ("profit", "profit"), ("emissions_tonnes", "emissions_tonnes"), ("curtailed_mw", "curtailed_mw"), ("renewable_utilisation_pct", "renewable_utilisation_pct")):
        mx, mean = max(abs(r["max_profit"][key] - r["cost_efficiency"][key]) for r in diverging), round(sum(abs(r["max_profit"][key] - r["cost_efficiency"][key]) for r in diverging) / len(diverging), 3)
        print(f"  {label:>26}: max={mx:.3f} mean={mean:.3f}")

out = {
    "probe": "D.5 baseline divergence (sellable_surplus_mw > total_charge_capacity_mw regime)",
    "base_scenario": {"difficulty": "D4_SURPLUS_DAY", "seed": 777001, "generation_mw": generation,
                        "transmission_headroom_mw": base_scenario.transmission_headroom_mw, "total_charge_cap_mw": total_charge_cap},
    "method": "dispatch() + balance() only -- zero model calls. Surplus swept via total_demand_mw, solar/wind/batteries/transmission/prices held fixed.",
    "sweep": rows,
    "diverging_count": len(diverging),
    "total_count": len(rows),
}
out_path = ROOT / "evidence" / "baseline_divergence_probe.json"
out_path.write_text(json.dumps(out, indent=2))
print(f"\nwrote {out_path}")
