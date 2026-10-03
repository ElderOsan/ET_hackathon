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
