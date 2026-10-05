#!/usr/bin/env python
"""Audit item H: cross-objective probe. One fixed surplus state and one fixed shortfall
state, each run under all 4 objectives x 3 live samples = 24 calls. Probe evidence only --
NOT benchmark evidence, does not count as one of the three fresh runs.

The same underlying EnvironmentState (byte-identical generation/demand/batteries/prices) is
reused across all 4 objectives for a given state -- only `objective` differs -- so any
difference in the decision is attributable to the objective, not to a different scenario.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import run_decision_pipeline
from app.agents.scenario_agent import generate_scenario
from app.data import physics
from app.data.recording import RecordingRecorder
from app.models.schemas import Difficulty, Objective

RUN_ID = "audit_h_cross_objective"
OBJECTIVES = [Objective.COST_EFFICIENCY, Objective.MIN_CARBON, Objective.MAX_RENEWABLE_UTILISATION, Objective.MAX_PROFIT]
N_SAMPLES = 3

STATES = {
    "surplus": generate_scenario(Difficulty.D4_SURPLUS_DAY, None, seed=777001),
    "shortfall": generate_scenario(Difficulty.D5_SHORTFALL_DAY, None, seed=777002),
}


def battery_summary(decision):
    charge = round(sum(a.amount_mw for a in decision.battery_actions if a.action == "charge"), 1)
    discharge = round(sum(a.amount_mw for a in decision.battery_actions if a.action == "discharge"), 1)
    return charge, discharge


def main():
    rows = []
    for state_name, base_scenario in STATES.items():
        gen = physics.total_generation_mw(base_scenario)
        print(f"\n=== state={state_name} tick={base_scenario.tick} seed={base_scenario.seed} generation={gen:.1f}MW demand={base_scenario.total_demand_mw:.1f}MW ===")
        for objective in OBJECTIVES:
            scenario = base_scenario.model_copy(update={"objective": objective})
            for sample in range(N_SAMPLES):
                recorder = RecordingRecorder(run_id=RUN_ID, sample_index=sample)
                result = run_decision_pipeline(scenario, recorder=recorder)
                applied = next(s for s in result.stages if s.name == "applied")
                decision = applied.decision
                charge, discharge = battery_summary(decision)
                sell = decision.market_amount_mw if decision.market_action == "sell" else 0.0
                buy = decision.market_amount_mw if decision.market_action == "buy" else 0.0
                curtail = round(decision.curtail_solar_mw + decision.curtail_wind_mw, 1)
                profit = physics.decision_profit(scenario, decision)
                emissions = physics.emissions_tonnes(scenario, decision)
                utilisation = physics.renewable_utilisation_pct(scenario, decision)
                row = {
                    "state": state_name, "objective": objective.value, "sample": sample, "mode": decision.mode,
                    "sell_mw": sell, "buy_mw": buy, "charge_mw": charge, "discharge_mw": discharge, "curtail_mw": curtail,
                    "net_profit": profit["net_profit"], "emissions_t": emissions, "utilisation_pct": utilisation,
                }
                rows.append(row)
                print(f"  obj={objective.value:28s} sample={sample} mode={decision.mode:10s} sell={sell:6.1f} buy={buy:6.1f} charge={charge:6.1f} discharge={discharge:6.1f} curtail={curtail:5.1f} | profit=${profit['net_profit']:8.1f} emissions={emissions:.3f}t utilisation={utilisation:.1f}%")

    import json
    out_path = Path(__file__).resolve().parents[2] / "evidence" / "audit_h_cross_objective_probe.json"
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
