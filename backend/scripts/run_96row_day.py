#!/usr/bin/env python
"""Runs the 96-row example day (file_input.EXAMPLE_96ROW_DAY_ROWS) live, recorded, so it ships
in the repo able to replay with no key. Paced at ~4s between calls against the measured
15 req/min free-tier limit (D.3 -- round1's 72-call run hit a 429 with zero pacing, which is
what this exists to prevent happening to a 96-call run).

Writes under TWO run_ids from the SAME 96 live calls (never doubles the call count):
  - file_input.run_id_for(...) -- the CONTENT-HASH run_id, computed the same way
    /file-input/preview computes it. This is the one Door 1 and any real "upload the 96-row
    file, preview it, run in Replay mode" flow actually reads at replay time.
  - "example_96row_day" -- the fixed legacy name this script has always written, kept for
    anyone who already has it bookmarked. Not read by any live code path as of this writing
    (checked: no route, no frontend code references this literal string at runtime).
A recorded call's file content depends only on (scenario_hash, prompt_version, model,
temperature, sample_index) -- never on run_id -- so copying the already-written file from one
run's calls/ directory to the other costs nothing further.

Usage: python scripts/run_96row_day.py
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import run_decision_pipeline
from app.data import file_input, recording
from app.data.recording import RecordingRecorder, SafeModeRecorder

PACE_SECONDS = 4.0  # ~15 req/min free-tier limit (measured, round1/D.2) -> 60/15 = 4s
LEGACY_RUN_ID = "example_96row_day"

rows = file_input.EXAMPLE_96ROW_DAY_ROWS
results = file_input.validate_rows(rows)
assert all(r.status == "ok" for r in results), [(r.row_index, r.errors) for r in results if r.status != "ok"]

content_run_id = file_input.run_id_for(results)
print(f"content-hash run_id: {content_run_id}")
print(f"legacy run_id:       {LEGACY_RUN_ID}")
print(f"pacing: {PACE_SECONDS}s between calls")

content_calls_dir = recording.RECORDINGS_ROOT / content_run_id / "calls"
legacy_calls_dir = recording.RECORDINGS_ROOT / LEGACY_RUN_ID / "calls"
legacy_calls_dir.mkdir(parents=True, exist_ok=True)

t0 = time.time()
pass_count = 0
for r in results:
    recorder = SafeModeRecorder(inner=RecordingRecorder(run_id=content_run_id, sample_index=r.row_index))
    run_result = run_decision_pipeline(r.scenario, recorder=recorder)
    applied = next(s for s in run_result.stages if s.name == "applied")
    if applied.evaluation.status.value == "pass":
        pass_count += 1
    print(f"row={r.row_index} tick={r.tick} mode={applied.decision.mode} status={applied.evaluation.status.value}")

    # Mirror whatever call file this row just wrote (if any -- a safe-mode fallback writes
    # none) into the legacy directory too, at zero extra calls.
    from app.agents.orchestrator_agent import build_request
    request = build_request(r.scenario)
    from app.data.recording import cache_key
    from app.agents.orchestrator_agent import MODEL, GEMINI_TEMPERATURE
    key = cache_key(request["scenario_hash"], request["prompt_version"], MODEL, GEMINI_TEMPERATURE, r.row_index)
    src = content_calls_dir / f"{key}.json"
    if src.exists():
        shutil.copy2(src, legacy_calls_dir / f"{key}.json")

    time.sleep(PACE_SECONDS)

recording.write_run_meta(content_run_id, model="gemini-3.5-flash-lite", seed=None, seed_set="file_input_96row", created_at=time.time(), scenario_count=len(results))
recording.write_manifest(content_run_id)
recording.write_run_meta(LEGACY_RUN_ID, model="gemini-3.5-flash-lite", seed=None, seed_set="file_input_96row", created_at=time.time(), scenario_count=len(results))
recording.write_manifest(LEGACY_RUN_ID)

print(f"\n{pass_count}/{len(results)} pass, elapsed={time.time()-t0:.1f}s")
print(f"wrote recordings/{content_run_id}/ and recordings/{LEGACY_RUN_ID}/")
