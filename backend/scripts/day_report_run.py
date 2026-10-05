#!/usr/bin/env python
"""Runs the 12-row example day through the file-input path (live, recorded) so the day
report has real stored results to build from. Usage: python scripts/day_report_run.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import run_decision_pipeline
from app.data import file_input
from app.data.recording import RecordingRecorder, SafeModeRecorder

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "day_report_example"

rows = file_input.EXAMPLE_DAY_ROWS
results = file_input.validate_rows(rows)
assert all(r.status == "ok" for r in results), [r.errors for r in results if r.status != "ok"]

run_results = []
for r in results:
    recorder = SafeModeRecorder(inner=RecordingRecorder(run_id=RUN_ID, sample_index=r.row_index))
    run_result = run_decision_pipeline(r.scenario, recorder=recorder)
    run_results.append(run_result)
    applied = next(s for s in run_result.stages if s.name == "applied")
    print(f"row={r.row_index} tick={r.tick} mode={applied.decision.mode} status={applied.evaluation.status.value}")

out_path = Path(__file__).resolve().parents[2] / "evidence" / f"{RUN_ID}_agent_results.json"
out_path.write_text(json.dumps([r.model_dump(mode="json") for r in run_results], indent=2))
print(f"wrote {out_path}")
