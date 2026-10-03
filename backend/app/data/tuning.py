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

DEFAULT_PREVIOUS_FLOOR_PCT = 25.0  # used when a scenario doesn't carry a prior tick's applied floor

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
