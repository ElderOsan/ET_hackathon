#!/usr/bin/env python
"""Runs the 96-row example day (file_input.EXAMPLE_96ROW_DAY_ROWS) live, recorded, under a
stable run_id so it ships in the repo able to replay with no key. Usage:
python scripts/run_96row_day.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import run_decision_pipeline
from app.data import file_input
from app.data.recording import RecordingRecorder, SafeModeRecorder

RUN_ID = "example_96row_day"

rows = file_input.EXAMPLE_96ROW_DAY_ROWS
results = file_input.validate_rows(rows)
assert all(r.status == "ok" for r in results), [(r.row_index, r.errors) for r in results if r.status != "ok"]

t0 = time.time()
pass_count = 0
for r in results:
    recorder = SafeModeRecorder(inner=RecordingRecorder(run_id=RUN_ID, sample_index=r.row_index))
    run_result = run_decision_pipeline(r.scenario, recorder=recorder)
    applied = next(s for s in run_result.stages if s.name == "applied")
    if applied.evaluation.status.value == "pass":
        pass_count += 1
    print(f"row={r.row_index} tick={r.tick} mode={applied.decision.mode} status={applied.evaluation.status.value}")

print(f"\n{pass_count}/{len(results)} pass, elapsed={time.time()-t0:.1f}s")
