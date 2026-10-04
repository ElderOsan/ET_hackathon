"""Scenario Agent (Environment Generator).

Generates a full environment state per tick. Deterministic Python (seedable, not
LLM-driven — this file calls no model). Every scenario carries the concrete seed that
produced it (generated if the caller didn't pass one) so any run can be reproduced.

Brief 2 Patch calibration: the fleet (farm IDs, farm capacities, battery specs) is fixed —
a utility operates one portfolio — defined once in app/data/fleet.py. Only output,
forecast, demand, prices, battery state of charge, and events vary per scenario. Each
scenario is rejection-sampled against its profile's target generation/total_demand ratio
and checked for physical feasibility (min_achievable_unserved_mw == 0) before being
accepted — a scenario the generator itself can't make servable is a generator bug, not a
fair test of the Orchestrator.
"""
from __future__ import annotations

import random

from app.data import fleet, physics
from app.data.tuning import (
    DEFAULT_PREVIOUS_FLOOR_PCT,
    DEMAND_BAND_MW,
    FLOOR_BANDS,
    INDUSTRIAL_SHARE_RANGE,
    MAX_RESAMPLE_ATTEMPTS,
    PROFILE_RATIO_RANGES,
    TRANSMISSION_HEADROOM_CONSTRAINED_MW,
    TRANSMISSION_LINE_RATING_MW,
)
from app.models.schemas import Battery, Difficulty, EnvironmentState, Objective, SolarFarm, WindFarm

_TICK_COUNTER = 0


def _next_tick() -> int:
    global _TICK_COUNTER
    _TICK_COUNTER += 1
    return _TICK_COUNTER


_PROFILE_EVENTS = {
    Difficulty.D1_STABLE_DAY: [],
    Difficulty.D2_CLOUDY_AFTERNOON: ["cloud_cover"],
    Difficulty.D2_PRICE_SPIKE: ["price_spike"],
    Difficulty.D3_MULTI_FAILURE_CASCADE: ["battery_2_offline", "transmission_at_capacity", "demand_surge", "storm_alert"],
    Difficulty.D4_SURPLUS_DAY: [],
    Difficulty.D5_SHORTFALL_DAY: [],
}

_VOLATILITY_CLASS = {
    Difficulty.D1_STABLE_DAY: "stable",
    # Reclassified from "some_volatility" (Brief 2 Patch, Step 5 diagnostic): cloud cover is
    # a known current-tick condition, not forward-looking uncertainty, and rules.py's own
    # _volatility_signal_present() never treated "cloud_cover" as a signal either — the old
    # 30-45% expected band contradicted the code's own definition of what counts as volatile.
    Difficulty.D2_CLOUDY_AFTERNOON: "stable",
    Difficulty.D2_PRICE_SPIKE: "some_volatility",
    Difficulty.D3_MULTI_FAILURE_CASCADE: "heavy_volatility",
    Difficulty.D4_SURPLUS_DAY: "stable",
    # Reclassified from "some_volatility" (Brief 2 Patch, Step 5 diagnostic #2): same root
    # cause as cloudy_afternoon above — shortfall_day has no events by default, and
    # _daily_high_threshold() is structurally untriggerable for any difficulty except
    # price_spike (price >= price+1 is never true), so _volatility_signal_present() is
    # always False here too. Stronger physical argument this time: shortfall_day is an
    # ACTIVE current-tick shortfall — using battery capacity now rather than hoarding it
    # behind a high reserve floor is the economically sensible move, not a mistake.
    Difficulty.D5_SHORTFALL_DAY: "stable",
}

_PRICE_RANGES = {
    Difficulty.D1_STABLE_DAY: (30, 50),
    Difficulty.D2_CLOUDY_AFTERNOON: (30, 60),
    Difficulty.D2_PRICE_SPIKE: (150, 300),
    Difficulty.D3_MULTI_FAILURE_CASCADE: (180, 350),
    Difficulty.D4_SURPLUS_DAY: (20, 40),
    Difficulty.D5_SHORTFALL_DAY: (120, 250),
}


def _ladder_step_for_position(position: str) -> str:
    return {
        "surplus": "serve load -> charge battery -> sell to grid -> curtail (last resort)",
        "shortfall": "renewables -> battery discharge above floor -> grid import -> reserve floor only if the Evaluator's own emergency check agrees",
        "balanced": "renewables -> battery -> grid import (minimal action needed either way)",
    }[position]


def _expected_behavior(objective: Objective | None, events: list[str], position: str) -> str:
    base = {
        Objective.COST_EFFICIENCY: "Cascade: cost, then carbon, then renewable utilisation (within tolerance at each step).",
        Objective.MIN_CARBON: "Cascade: carbon, then cost, then renewable utilisation (within tolerance at each step).",
        Objective.MAX_RENEWABLE_UTILISATION: "Cascade: renewable utilisation, then cost, then carbon (within tolerance at each step).",
        Objective.MAX_PROFIT: "Cascade: profit, then cost, then carbon (carbon drops to last).",
        None: "No objective declared: cost_efficiency cascade applies under the golden rules.",
    }[objective]
    base += f" Golden rules are never traded away. This tick is a computed {position}."
    if "battery_2_offline" in events:
        base += " One battery is offline — do not schedule actions against it."
    if "transmission_at_capacity" in events:
        base += " Transmission headroom is nearly exhausted — curtailment up to the minimum physically required may be a stability-forced exception."
    if "demand_surge" in events:
        base += " Industrial demand has surged — reliability takes precedence over cost/carbon optimization."
    return base


def _build_batteries(rng: random.Random, degraded: bool) -> list[Battery]:
    batteries = []
    for spec in fleet.BATTERY_SPECS:
        available = not (degraded and spec["id"] == "battery_2")
        batteries.append(Battery(
            state_of_charge_pct=round(rng.uniform(20, 90), 1),
            min_safe_soc_pct=10.0,
            available=available,
            **spec,
        ))
    return batteries


def _split_farms(rng: random.Random, capacities: dict, total_output: float, total_forecast: float, cls):
    weights = [rng.uniform(0.6, 1.4) for _ in capacities]
    weight_sum = sum(weights)
    farms = []
    for (farm_id, capacity_mw), w in zip(capacities.items(), weights):
        share = w / weight_sum
        output = round(min(capacity_mw, total_output * share), 1)
        forecast = round(min(capacity_mw, total_forecast * share), 1)
        farms.append(cls(id=farm_id, capacity_mw=capacity_mw, output_mw=output, forecast_mw=forecast))
    return farms


def generate_scenario(
    difficulty: Difficulty,
    objective: Objective | None = None,
    seed: int | None = None,
    previous_floor_pct: float = DEFAULT_PREVIOUS_FLOOR_PCT,
    resample_log: list[str] | None = None,
) -> EnvironmentState:
    concrete_seed = seed if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
    rng = random.Random(concrete_seed)

    events = list(_PROFILE_EVENTS[difficulty])
    degraded = "battery_2_offline" in events
    ratio_lo, ratio_hi = PROFILE_RATIO_RANGES[difficulty.value]
    price_lo, price_hi = _PRICE_RANGES[difficulty]

    accepted = None
    for _attempt in range(MAX_RESAMPLE_ATTEMPTS):
        total_demand = round(rng.uniform(*DEMAND_BAND_MW), 1)
        industrial_share = rng.uniform(*INDUSTRIAL_SHARE_RANGE)
        if "demand_surge" in events:
            industrial_share = min(industrial_share * 1.6, 0.55)
        industrial_demand = round(total_demand * industrial_share, 1)
        base_demand = round(total_demand - industrial_demand, 1)

        solar_factor = rng.uniform(0.05, 0.95)
        wind_factor = rng.uniform(0.05, 0.95)
        solar_output = round(fleet.TOTAL_SOLAR_CAPACITY_MW * solar_factor, 1)
        wind_output = round(fleet.TOTAL_WIND_CAPACITY_MW * wind_factor, 1)
        generation = solar_output + wind_output
        ratio = generation / total_demand if total_demand else 0.0

        if not (ratio_lo <= ratio <= ratio_hi):
            if resample_log is not None:
                resample_log.append(f"{difficulty.value}: ratio {ratio:.2f} outside [{ratio_lo},{ratio_hi}]")
            continue

        batteries = _build_batteries(rng, degraded)
        transmission_headroom = (
            TRANSMISSION_HEADROOM_CONSTRAINED_MW if "transmission_at_capacity" in events else TRANSMISSION_LINE_RATING_MW
        )
        max_emergency_discharge = sum(physics.max_discharge_mw(b, 0.0, emergency=True) for b in batteries)
        best_case_supply = generation + max_emergency_discharge + transmission_headroom
        min_achievable_unserved = max(0.0, round(total_demand - best_case_supply, 1))

        if min_achievable_unserved > 0:
            if resample_log is not None:
                resample_log.append(f"{difficulty.value}: infeasible by {min_achievable_unserved:.1f}MW")
            continue

        accepted = dict(
            total_demand=total_demand, base_demand=base_demand, industrial_demand=industrial_demand,
            solar_output=solar_output, wind_output=wind_output, batteries=batteries,
            transmission_headroom=transmission_headroom,
        )
        break

    if accepted is None:
        # Should not happen in practice (see acceptance tests) — fall back to the last attempt
        # rather than crash the app, and make the fallback visible in the log.
        if resample_log is not None:
            resample_log.append(f"{difficulty.value}: EXHAUSTED {MAX_RESAMPLE_ATTEMPTS} attempts, using last candidate")
        accepted = dict(
            total_demand=total_demand, base_demand=base_demand, industrial_demand=industrial_demand,
            solar_output=solar_output, wind_output=wind_output, batteries=_build_batteries(rng, degraded),
            transmission_headroom=transmission_headroom,
        )

    solar_forecast = round(accepted["solar_output"] * rng.uniform(0.9, 1.1), 1)
    wind_forecast = round(accepted["wind_output"] * rng.uniform(0.9, 1.1), 1)
    base_demand_forecast = round(accepted["base_demand"] * rng.uniform(0.95, 1.1), 1)
    total_demand_forecast = round(base_demand_forecast + accepted["industrial_demand"], 1)

    price = round(rng.uniform(price_lo, price_hi), 1)
    volatility_class = _VOLATILITY_CLASS[difficulty]
    floor_min, floor_max = FLOOR_BANDS[volatility_class]

    generation = accepted["solar_output"] + accepted["wind_output"]
    position = physics.position_label(physics.net_position_mw(generation, accepted["total_demand"]))

    scenario = EnvironmentState(
        tick=_next_tick(),
        seed=concrete_seed,
        difficulty=difficulty,
        objective=objective,
        solar_output_mw=accepted["solar_output"],
        solar_forecast_mw=solar_forecast,
        wind_output_mw=accepted["wind_output"],
        wind_forecast_mw=wind_forecast,
        solar_farms=_split_farms(rng, fleet.SOLAR_FARM_CAPACITIES_MW, accepted["solar_output"], solar_forecast, SolarFarm),
        wind_farms=_split_farms(rng, fleet.WIND_FARM_CAPACITIES_MW, accepted["wind_output"], wind_forecast, WindFarm),
        base_demand_mw=accepted["base_demand"],
        base_demand_forecast_mw=base_demand_forecast,
        total_demand_mw=accepted["total_demand"],
        total_demand_forecast_mw=total_demand_forecast,
        grid_frequency_hz=round(rng.uniform(49.9, 50.1), 3),
        transmission_constraint_mw=TRANSMISSION_LINE_RATING_MW,
        transmission_headroom_mw=accepted["transmission_headroom"],
        batteries=accepted["batteries"],
        previous_floor_pct=previous_floor_pct,
        electricity_price_per_mwh=price,
        carbon_price_per_ton=round(rng.uniform(20, 40), 1),
        demand_response_incentive_per_mwh=round(rng.uniform(10, 30), 1),
        weather_forecast="storm" if "storm_alert" in events else "clear",
        storm_alert="storm_alert" in events,
        maintenance_scheduled=False,
        industrial_demand_mw=accepted["industrial_demand"],
        events=events,
        expected_behavior=_expected_behavior(objective, events, position),
        expected_floor_min_pct=floor_min,
        expected_floor_max_pct=floor_max,
        expected_ladder_step=_ladder_step_for_position(position),
        expected_emergency=False,
    )
    scenario.expected_emergency = physics.is_emergency(scenario, floor_min)
    return scenario


def normalize_scenario(scenario: EnvironmentState) -> tuple[EnvironmentState, list[str]]:
    """Recomputes everything no component may re-derive on its own, and auto-corrects
    inconsistencies a manual edit can introduce. Returns (normalized, corrections) where
    corrections is a human-readable list of what changed, for the manual form to display.
    """
    corrections: list[str] = []
    data = scenario.model_dump()

    total_demand = round(data["base_demand_mw"] + data["industrial_demand_mw"], 1)
    if total_demand != data["total_demand_mw"]:
        corrections.append(f"total_demand_mw recomputed: {data['total_demand_mw']} -> {total_demand}")
    data["total_demand_mw"] = total_demand

    total_demand_forecast = round(data["base_demand_forecast_mw"] + data["industrial_demand_mw"], 1)
    if total_demand_forecast != data["total_demand_forecast_mw"]:
        corrections.append(f"total_demand_forecast_mw recomputed: {data['total_demand_forecast_mw']} -> {total_demand_forecast}")
    data["total_demand_forecast_mw"] = total_demand_forecast

    battery_2_event = "battery_2_offline" in data["events"]
    for b in data["batteries"]:
        if b["id"] == "battery_2" and b["available"] == battery_2_event:
            b["available"] = not battery_2_event
            corrections.append(f"battery_2.available set to {b['available']} to match the battery_2_offline event switch")

    line_constrained_event = "transmission_at_capacity" in data["events"]
    expected_headroom = TRANSMISSION_HEADROOM_CONSTRAINED_MW if line_constrained_event else TRANSMISSION_LINE_RATING_MW
    if line_constrained_event and data["transmission_headroom_mw"] > TRANSMISSION_HEADROOM_CONSTRAINED_MW:
        corrections.append(f"transmission_headroom_mw set to {expected_headroom} to match the line-constrained event switch")
        data["transmission_headroom_mw"] = expected_headroom
    elif not line_constrained_event and data["transmission_headroom_mw"] <= TRANSMISSION_HEADROOM_CONSTRAINED_MW:
        corrections.append(f"transmission_headroom_mw restored to {TRANSMISSION_LINE_RATING_MW} — the line-constrained switch is off")
        data["transmission_headroom_mw"] = TRANSMISSION_LINE_RATING_MW

    normalized = EnvironmentState(**data)

    computed_emergency = physics.is_emergency(normalized, normalized.expected_floor_min_pct)
    if computed_emergency != normalized.expected_emergency:
        corrections.append(f"expected_emergency recomputed from state: {normalized.expected_emergency} -> {computed_emergency}")
        normalized.expected_emergency = computed_emergency

    generation = normalized.solar_output_mw + normalized.wind_output_mw
    position = physics.position_label(physics.net_position_mw(generation, normalized.total_demand_mw))
    new_ladder = _ladder_step_for_position(position)
    if new_ladder != normalized.expected_ladder_step:
        corrections.append(f"expected_ladder_step recomputed from net position ({position}): -> {new_ladder}")
        normalized.expected_ladder_step = new_ladder

    return normalized, corrections