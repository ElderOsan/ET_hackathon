#!/usr/bin/env python
"""Probe: one fixed surplus state with genuine export headroom, all 4 objectives, 3 live
samples each (12 calls) -- directly tests whether the ladder reword made max_profit sell
before charging. Fresh run, new run_id, nothing existing re-recorded.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import run_decision_pipeline
from app.agents.scenario_agent import generate_scenario
from app.data import physics
from app.data.recording import RecordingRecorder
from app.models.schemas import Difficulty, Objective

RUN_ID = "probe_ladder_reword"
OBJECTIVES = [Objective.COST_EFFICIENCY, Objective.MIN_CARBON, Objective.MAX_RENEWABLE_UTILISATION, Objective.MAX_PROFIT]
N_SAMPLES = 3

base_scenario = generate_scenario(Difficulty.D4_SURPLUS_DAY, None, seed=777001)
gen = physics.total_generation_mw(base_scenario)
surplus = physics.renewable_surplus_mw(base_scenario)
print(f"probe state: tick={base_scenario.tick} seed={base_scenario.seed} generation={gen:.1f}MW demand={base_scenario.total_demand_mw:.1f}MW surplus={surplus:.1f}MW transmission_headroom={base_scenario.transmission_headroom_mw:.1f}MW sellable_surplus={physics.sellable_surplus_mw(base_scenario):.1f}MW")
print()

for objective in OBJECTIVES:
    scenario = base_scenario.model_copy(update={"objective": objective})
    for sample in range(N_SAMPLES):
        recorder = RecordingRecorder(run_id=RUN_ID, sample_index=sample)
        result = run_decision_pipeline(scenario, recorder=recorder)
        applied = next(s for s in result.stages if s.name == "applied")
        decision = applied.decision
        charge = round(sum(a.amount_mw for a in decision.battery_actions if a.action == "charge"), 1)
        sell = decision.market_amount_mw if decision.market_action == "sell" else 0.0
        print(f"obj={objective.value:28s} sample={sample} mode={decision.mode:10s} sell={sell:6.1f} charge={charge:6.1f} status={applied.evaluation.status.value}")
