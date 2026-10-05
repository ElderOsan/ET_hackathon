#!/usr/bin/env python
"""Report only, no changes: for the Step 6 oracle's 200 scenarios, every rule_8b (floor-band)
mismatch -- the dispatcher's chosen floor, the scenario's expected band, the dispatcher's own
state-based volatility class/method, and whether that class comes from scenario state or the
profile-name map.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.evaluator import evaluate
from app.agents.scenario_agent import generate_scenario
from app.data.dispatcher import dispatch, state_volatility_class
from app.data.tuning import DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
from app.models.schemas import Difficulty

PROFILES = [Difficulty.D1_STABLE_DAY, Difficulty.D2_CLOUDY_AFTERNOON, Difficulty.D2_PRICE_SPIKE, Difficulty.D3_MULTI_FAILURE_CASCADE, Difficulty.D4_SURPLUS_DAY, Difficulty.D5_SHORTFALL_DAY]
BASELINE_SEED = 500_000
N_ORACLE = 200

mismatches = []
for i in range(N_ORACLE):
    profile = PROFILES[i % len(PROFILES)]
    scenario = generate_scenario(profile, None, seed=BASELINE_SEED + i)
    decision = dispatch(scenario, None)
    result = evaluate(scenario, decision, repairs=None, include_repair_rule=False)
    rule8b = next(r for r in result.rules if r.rule_id == "rule_8b")
    if not rule8b.passed:
        vol_class, method = state_volatility_class(scenario)
        mismatches.append({
            "seed": scenario.seed, "profile": profile.value,
            "chosen_floor_pct": decision.applied_floor_pct,
            "expected_band": f"{scenario.expected_floor_min_pct}-{scenario.expected_floor_max_pct}%",
            "dispatcher_volatility_class": vol_class, "dispatcher_method": method,
            "electricity_price_per_mwh": scenario.electricity_price_per_mwh,
            "storm_alert": scenario.storm_alert,
            "any_battery_offline": any(not b.available for b in scenario.batteries),
        })

print(f"{len(mismatches)}/{N_ORACLE} rule_8b mismatches")
by_profile = {}
for m in mismatches:
    by_profile[m["profile"]] = by_profile.get(m["profile"], 0) + 1
print("by profile:", by_profile)
print()
for m in mismatches[:10]:
    print(m)
print("..." if len(mismatches) > 10 else "")

print()
print(f"DISPATCHER_PRICE_SPIKE_THRESHOLD_USD = {DISPATCHER_PRICE_SPIKE_THRESHOLD_USD}")
print("shortfall_day price range (scenario_agent._PRICE_RANGES) = (120, 250) -- every shortfall_day")
print("scenario's price draw is >= 120, which always exceeds the flat $100 threshold.")
print()
print("Is the volatility class computed from scenario state or mapped from the profile name?")
print("BOTH exist, and they are two different, independent things:")
print("- scenario.expected_floor_min_pct/max_pct (what rule_8b checks the MODEL's proposed floor")
print("  against) comes from scenario_agent._VOLATILITY_CLASS, a static dict keyed by Difficulty")
print("  (profile name) -- shortfall_day maps to 'stable' (20-30%) unconditionally, regardless of")
print("  the scenario's actual randomized price.")
print("- dispatcher.state_volatility_class (what the DISPATCHER uses to pick its OWN floor) is")
print("  computed from live scenario state: storm_alert, any battery offline, or")
print("  electricity_price_per_mwh >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD -- never the profile name.")
print("These two are independent by design (the dispatcher docstring says so explicitly) and were")
print("never reconciled against each other for shortfall_day's price range.")
