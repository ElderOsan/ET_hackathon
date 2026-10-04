#!/usr/bin/env python
"""T1 smoke test (Patch 3 evidence checklist): 8 fixed scenarios -- one per profile plus two
hard (multi_failure_cascade) cascades under different objectives -- same seeds every time,
recorded/cached via RecordingRecorder so a repeat run costs nothing. Run this whenever the
prompt, input schema or model path changes; never run the full 72-scenario benchmark for a
check this cheap can catch.

Usage: python scripts/smoke.py [--run-id smoke_<timestamp>]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import run_decision_pipeline
from app.agents.scenario_agent import generate_scenario
from app.data import recording
from app.data.benchmark_seeds import SMOKE_SEED_SET
from app.data.recording import RecordingRecorder
from app.models.schemas import Difficulty, Objective

BASE = SMOKE_SEED_SET["base_seed"]

CASES = [
    (Difficulty.D1_STABLE_DAY, None, BASE + 0),
    (Difficulty.D2_CLOUDY_AFTERNOON, None, BASE + 1),
    (Difficulty.D2_PRICE_SPIKE, None, BASE + 2),
    (Difficulty.D3_MULTI_FAILURE_CASCADE, None, BASE + 3),
    (Difficulty.D4_SURPLUS_DAY, None, BASE + 4),
    (Difficulty.D5_SHORTFALL_DAY, None, BASE + 5),
    (Difficulty.D3_MULTI_FAILURE_CASCADE, Objective.MAX_PROFIT, BASE + 6),   # hard cascade 1
    (Difficulty.D3_MULTI_FAILURE_CASCADE, Objective.MIN_CARBON, BASE + 7),   # hard cascade 2
]


def main():
    run_id = sys.argv[sys.argv.index("--run-id") + 1] if "--run-id" in sys.argv else f"smoke_{int(time.time())}"
    recorder = RecordingRecorder(run_id=run_id)
    print(f"run_id={run_id}")

    rows = []
    for difficulty, objective, seed in CASES:
        scenario = generate_scenario(difficulty, objective, seed=seed)
        result = run_decision_pipeline(scenario, recorder=recorder)
        applied = next(s for s in result.stages if s.name == "applied")
        failed = [x.rule_id for x in applied.evaluation.rules if not x.passed and x.applicable]
        rows.append((difficulty.value, objective.value if objective else "none", seed, applied.evaluation.status.value, applied.decision.mode, failed))
        print(f"{difficulty.value:22s} {objective.value if objective else 'none':25s} seed={seed:10d} -> {applied.evaluation.status.value:8s} mode={applied.decision.mode:16s} failed={failed}")

    recording.write_run_meta(run_id, model="smoke", seed=BASE, seed_set="smoke", created_at=time.time(), scenario_count=len(rows))
    recording.write_manifest(run_id)
    passed = sum(1 for r in rows if r[3] == "pass")
    print(f"\n{passed}/{len(rows)} pass. Recorded under recordings/{run_id}/ -- re-running this script reuses the cache, 0 new calls.")


if __name__ == "__main__":
    main()
