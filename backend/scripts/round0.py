#!/usr/bin/env python
"""The fresh three-pass benchmark (dev seed 20261004, 6 difficulties x 4 objectives x 3 reps
= 72 scenarios, every scenario in the denominator) run against the pre-registered tiers in
evidence/exit_tiers.json. Live Gemini calls, recorded under recordings/<run_id>/.

Usage: python scripts/round0.py [run_id]  (default: round0)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import _run_matrix
from app.data.benchmark_seeds import DEV_SEED_SET
from app.models.schemas import Objective


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else "round0"
    t0 = time.time()
    summary = _run_matrix(
        DEV_SEED_SET["base_seed"], 3, list(Objective),
        seed_set_name="dev_round0", mode="record", run_id=run_id,
    )
    elapsed = time.time() - t0
    out_path = Path(__file__).resolve().parents[2] / "evidence" / f"{run_id}_benchmark.json"
    out_path.write_text(summary.model_dump_json(indent=2))
    print(f"total={summary.total} judged={summary.judged_count} infeasible={summary.infeasible_count} margin_infeasible={summary.margin_infeasible_count}")
    print(f"first_attempt_pass_rate={summary.first_attempt_pass_rate_pct}% ({summary.first_attempt_passed}/{summary.judged_count})")
    print(f"applied: passed={summary.applied_passed} failed={summary.applied_failed} flagged={summary.applied_flagged}")
    print(f"repaired={summary.repaired_count} ({summary.repair_rate_pct}%)")
    print(f"safe_mode_count={summary.safe_mode_count} unresolved_count={summary.unresolved_count}")
    print(f"elapsed={elapsed:.1f}s")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
