"""The fixed fleet (Brief 2 Patch, Step 2). A utility operates one portfolio — farm IDs,
farm capacities, and battery specs are identical in every scenario; only output, forecast,
demand, prices, battery state of charge, and events vary per scenario.

Chosen totals: ~110 MW solar (5 farms), ~60 MW wind (3 farms), matching the "suggested
totals" in the brief and close to what the old random generator produced at its higher end.
Batteries unchanged from Brief 1: 40 MWh / 10 MW and 25 MWh / 6 MW.
"""
from __future__ import annotations

SOLAR_FARM_CAPACITIES_MW = {
    "solar_1": 28.0,
    "solar_2": 24.0,
    "solar_3": 22.0,
    "solar_4": 20.0,
    "solar_5": 16.0,
}  # sums to 110.0

WIND_FARM_CAPACITIES_MW = {
    "wind_1": 24.0,
    "wind_2": 20.0,
    "wind_3": 16.0,
}  # sums to 60.0

TOTAL_SOLAR_CAPACITY_MW = sum(SOLAR_FARM_CAPACITIES_MW.values())
TOTAL_WIND_CAPACITY_MW = sum(WIND_FARM_CAPACITIES_MW.values())

BATTERY_SPECS = [
    dict(id="battery_1", capacity_mwh=40.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0),
    dict(id="battery_2", capacity_mwh=25.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0),
]
