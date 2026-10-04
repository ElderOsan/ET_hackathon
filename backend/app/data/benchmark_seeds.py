"""Benchmark seed sets (Brief 2 Patch, Step 7). Fixed so runs are directly comparable —
each run of the same seed set uses the exact same 24 scenarios (6 profiles x 4 objectives).

Dev set: iterate against this freely. Held-out set: never touched while tuning, gated by
tuning.BENCHMARK_ALLOW_HELD_OUT so it can't be consumed casually — only flip that flag on
when actually reporting results.
"""
from __future__ import annotations

DEV_SEED_SET = {
    "name": "dev",
    "base_seed": 20261004,
}

HELD_OUT_SEED_SET = {
    "name": "held_out",
    "base_seed": 20261104,
}

# T1 smoke (Patch 3 evidence checklist): one scenario per profile plus two hard cascades,
# fixed seeds, run whenever the prompt, input schema or model path changes -- never the full
# benchmark. 8 scenarios, ~8 calls. See scripts/smoke.py.
SMOKE_SEED_SET = {
    "name": "smoke",
    "base_seed": 90000001,
}
