"""Named tuning constants for the priority model and reserve-floor logic.

Every number here is a starting value from the design brief, not a measured fact —
revisit after the Learning Guide research (see NEXT_STEPS.md) and tune in testing.
Kept separate from app/core/config.py, which holds only environment/secrets config.
"""
from __future__ import annotations

# Layer 1 golden rules
RESERVE_MARGIN_PCT = 5.0  # critical load must be coverable with this much supply margin to spare
FREQ_BAND_HZ = (49.5, 50.5)  # grid frequency considered stable inside this band — verify before demo

# Layer 2 objective cascade
OBJECTIVE_TOLERANCE_PCT = 5.0  # how close to the top-priority optimum counts as "tied" before the next priority applies

# Battery reserve floor
FLOOR_MIN = 20.0
FLOOR_MAX = 60.0
FLOOR_STEP_DOWN = 10.0  # max points the applied floor may fall in one tick; it may rise by any amount

FLOOR_BANDS = {
    "stable": (20.0, 30.0),
    "some_volatility": (30.0, 45.0),
    "heavy_volatility": (45.0, 60.0),
}

# Patch 3, Step 3 — the dispatcher's OWN volatility signal, computed from scenario state
# (storm_alert, an offline battery, a price spike), not mapped from the profile name the way
# scenario_agent._VOLATILITY_CLASS is. A flat $/MWh threshold rather than the existing
# _daily_high_threshold proxy (rules.py), which is structurally untriggerable for any
# difficulty but price_spike (see NEXT_STEPS.md) — the dispatcher needs a signal that
# actually fires from state alone, independent of which profile generated the scenario.
DISPATCHER_PRICE_SPIKE_THRESHOLD_USD = 100.0

DEFAULT_PREVIOUS_FLOOR_PCT = 25.0  # used when a scenario doesn't carry a prior tick's applied floor

# Patch 3 addendum: percentage-point tolerance for "did this discharge reach the floor,
# not go below it." A discharge rounded to 1 decimal MW cannot always land exactly on the
# floor given a battery's capacity (e.g. 6.6MW on a 40MWh battery resolves to 24.975%, not
# precisely 25.0%) -- without this, rule_2b spuriously flagged a discharge that correctly
# stopped AT the floor. Sized to the rounding noise from the smallest representable MW step
# (0.1MW) against the smaller battery's capacity (25MWh): 0.1*TICK_HOURS/25*100 = 0.1pp.
FLOOR_SOC_TOLERANCE_PCT = 0.1

# Physics module (Brief 2) — the single CONFIG location for every physical-layer number.
TICK_HOURS = 0.25  # 15-minute tick: MWh of usable battery capacity -> max deliverable MW this tick
BALANCE_TOLERANCE_MW = 0.1  # power-balance residual allowed before it's treated as a real imbalance
CURTAIL_TOLERANCE_MW = 0.5  # curtailment allowed above the minimum required before rule_6 fails
REPAIR_TOLERANCE_MW = 0.5  # total balancer repair magnitude allowed before rule_10 flags it

# Transmission: net flow across the grid interconnection (sale minus purchase, in either
# direction) is bounded by transmission_headroom_mw, which is normally the full line rating
# and is driven down by the transmission_at_capacity event — see physics.py docstring.
TRANSMISSION_LINE_RATING_MW = 180.0
TRANSMISSION_HEADROOM_CONSTRAINED_MW = 2.0  # near-zero headroom left when the line is "at capacity"

# Brief 2 Patch 2, Step 2 — buy/sell price spread around electricity_price_per_mwh. 0 must
# reproduce the old single-price behaviour exactly (buy == sell == electricity_price).
PRICE_SPREAD_PCT = 5.0

# Patch 3, Step 1 — the cap on retries for an infrastructure failure (503/429/timeout/
# network) before a scenario is reported unresolved rather than retried forever.
GEMINI_RETRY_ATTEMPTS = 5
GEMINI_RETRY_MAX_WAIT_S = 20.0

# Patch 3, Step 4 — safe mode.
PARSE_RETRY_ATTEMPTS = 2  # whole fresh model calls retried on a parse/schema failure specifically (infra retries are separate, see GEMINI_RETRY_ATTEMPTS)
SAFE_MODE_FALLBACK_TIMEOUT_S = 15.0  # the live attempt + fallback to the dispatcher must complete within this, so the UI never hangs
# The NORMAL live-call retry policy (GEMINI_RETRY_ATTEMPTS=5, max wait 20s) can take ~50s
# worst case -- far more than SAFE_MODE_FALLBACK_TIMEOUT_S allows. Safe mode's own live
# attempt uses this tighter policy instead so the 15s budget is actually honorable.
SAFE_MODE_RETRY_ATTEMPTS = 2
SAFE_MODE_RETRY_MAX_WAIT_S = 5.0

# Patch 3 addendum — pinned explicitly rather than left as an unset, undocumented default.
# This is NOT a tuning change: 1.0 is Google's own documented default for the Gemini 3
# family (which gemini-3.5-flash-lite belongs to), and their docs strongly recommend
# against lowering it — "may lead to unexpected behavior, such as looping or degraded
# performance, particularly in complex... reasoning tasks." Pinned here only so the value
# is visible and intentional in CONFIG, not because a different value was tried or wanted.
# https://ai.google.dev/gemini-api/docs/gemini-3
GEMINI_TEMPERATURE = 1.0

# Brief 2 Patch — calibrated scenario generation ------------------------------------------

# total_demand_mw is sampled within this band first; base/industrial are then split from it.
DEMAND_BAND_MW = (90.0, 150.0)
INDUSTRIAL_SHARE_RANGE = (0.25, 0.35)  # industrial_demand_mw as a share of total_demand_mw

# Target generation/total_demand ratio per profile — rejection-sampled until the ratio lands
# in range (or MAX_RESAMPLE_ATTEMPTS is hit, which should never happen in practice).
PROFILE_RATIO_RANGES = {
    "stable_day": (1.05, 1.25),
    "cloudy_afternoon": (0.80, 1.00),
    "price_spike": (0.95, 1.15),
    "multi_failure_cascade": (0.70, 0.95),
    "surplus_day": (1.30, 1.60),
    "shortfall_day": (0.65, 0.90),
}
MAX_RESAMPLE_ATTEMPTS = 200

REASONING_CHAR_CAP = 900  # submit_decision's reasoning field max length (JSON Schema maxLength)

# Raw-rule-failure categories for the batch scoreboard (Step 6). rule_3 is special-cased in
# code: "arithmetic" when the raw proposal over-allocated (repairs touched charge/sale/
# curtailment), "outcome" when the shortfall was there regardless of allocation.
RULE_CATEGORY_MAP = {
    "rule_10": "arithmetic",
    "rule_1": "strategy", "rule_2b": "strategy", "rule_4": "strategy", "rule_5": "strategy",
    "rule_6": "strategy", "rule_8b": "strategy", "rule_8c": "strategy", "rule_8d": "strategy",
    "rule_8e": "strategy", "rule_9": "strategy",
    "rule_2a": "outcome", "rule_3b": "outcome", "rule_7": "outcome",
    # rule_3 deliberately omitted — categorized dynamically, see routes.py
}

# Benchmark seed sets (Step 7). The held-out set is guarded by this flag so it's never
# consumed casually while tuning — only flip it on when actually reporting results.
BENCHMARK_ALLOW_HELD_OUT = False
