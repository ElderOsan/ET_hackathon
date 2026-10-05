#!/usr/bin/env python
"""Replays the round0 recording (0 new model calls) and confirms every one of the 72
decisions matches the originally recorded run exactly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import _run_matrix
from app.data.benchmark_seeds import DEV_SEED_SET
from app.models.schemas import Objective

ROOT = Path(__file__).resolve().parents[2]
run_id = sys.argv[1] if len(sys.argv) > 1 else "round0"
original = json.load(open(ROOT / "evidence" / f"{run_id}_benchmark.json"))["results"]

replayed = _run_matrix(
    DEV_SEED_SET["base_seed"], 3, list(Objective),
    seed_set_name="dev_round0", mode="replay", run_id=run_id,
)

mismatches = []
for i, (orig, rep) in enumerate(zip(original, replayed.results)):
    rep_dict = rep.model_dump(mode="json")
    if orig["scenario"] != rep_dict["scenario"]:
        mismatches.append((i, "scenario differs"))
        continue
    for stage_name in ("raw", "applied"):
        o_stage = next(s for s in orig["stages"] if s["name"] == stage_name)
        r_stage = next(s for s in rep_dict["stages"] if s["name"] == stage_name)
        if o_stage["decision"] != r_stage["decision"] or o_stage["evaluation"]["status"] != r_stage["evaluation"]["status"]:
            mismatches.append((i, f"{stage_name} decision/status differs"))

bad_indices = {i for i, _ in mismatches}
print(f"{len(original) - len(bad_indices)}/{len(original)} match on replay (0 new model calls)")
if mismatches:
    for m in mismatches:
        print(" MISMATCH:", m)
else:
    print("replay matches 72/72")
