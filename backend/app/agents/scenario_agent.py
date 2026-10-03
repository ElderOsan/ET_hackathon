"""Scenario Agent (Environment Generator).

Generates a full environment state per tick, at increasing difficulty:
  stable_day (D1) -> cloudy_afternoon / price_spike (D2) -> multi_failure_cascade (D3)

Numeric generation is deterministic Python (seedable, not LLM-driven — this file calls no
model) — this keeps every scenario reproducible and keeps the Evaluator's hidden tag
grounded in the same heuristics and physics the rest of the system uses, rather than asking
a model to invent one. Every scenario carries the concrete seed that produced it (generated
if the caller didn't pass one) so any run can be reproduced later.
"""
from __future__ import annotations

import random

from app.data import physics
from app.data.tuning import (
    DEFAULT_PREVIOUS_FLOOR_PCT,
    FLOOR_BANDS,
    TRANSMISSION_HEADROOM_CONSTRAINED_MW,
    TRANSMISSION_LINE_RATING_MW,
)
from app.models.schemas import Battery, Difficulty, EnvironmentState, Objective, SolarFarm, WindFarm

_TICK_COUNTER = 0

N_SOLAR_FARMS = 5
N_WIND_FARMS = 3


def _next_tick() -> int:
    global _TICK_COUNTER
    _TICK_COUNTER += 1
    return _TICK_COUNTER


def _base_batteries(rng: random.Random, degraded: bool = False) -> list[Battery]:
    return [
        Battery(
            id="battery_1",
            capacity_mwh=40.0,
            state_of_charge_pct=round(rng.uniform(20, 90), 1),
            max_charge_rate_mw=10.0,
            max_discharge_rate_mw=10.0,
            charging_efficiency_pct=92.0,
            degradation_pct=round(rng.uniform(1, 5), 1),
            available=True,
        ),
        Battery(
            id="battery_2",
            capacity_mwh=25.0,
            state_of_charge_pct=round(rng.uniform(20, 90), 1),
            max_charge_rate_mw=6.0,
            max_discharge_rate_mw=6.0,
            charging_efficiency_pct=90.0,
            degradation_pct=round(rng.uniform(1, 5), 1),
            available=not degraded,
        ),
    ]


def _split_solar_farms(rng: random.Random, total_output: float, total_forecast: float) -> list[SolarFarm]:
    weights = [rng.uniform(0.6, 1.4) for _ in range(N_SOLAR_FARMS)]
    weight_sum = sum(weights)
    farms = []
    for i, w in enumerate(weights):
        share = w / weight_sum
        output = round(total_output * share, 1)
        forecast = round(total_forecast * share, 1)
        capacity = round(max(output, forecast, 0.1) * rng.uniform(1.2, 1.8), 1)
        farms.append(SolarFarm(id=f"solar_{i + 1}", capacity_mw=capacity, output_mw=output, forecast_mw=forecast))
    return farms


def _split_wind_farms(rng: random.Random, total_output: float, total_forecast: float) -> list[WindFarm]:
    weights = [rng.uniform(0.6, 1.4) for _ in range(N_WIND_FARMS)]
    weight_sum = sum(weights)
    farms = []
    for i, w in enumerate(weights):
        share = w / weight_sum
        output = round(total_output * share, 1)
        forecast = round(total_forecast * share, 1)
        capacity = round(max(output, forecast, 0.1) * rng.uniform(1.2, 1.8), 1)
        farms.append(WindFarm(id=f"wind_{i + 1}", capacity_mw=capacity, output_mw=output, forecast_mw=forecast))
    return farms


def _volatility_class(difficulty: Difficulty) -> str:
    return {
        Difficulty.D1_STABLE_DAY: "stable",
        Difficulty.D2_CLOUDY_AFTERNOON: "some_volatility",
        Difficulty.D2_PRICE_SPIKE: "some_volatility",
        Difficulty.D3_MULTI_FAILURE_CASCADE: "heavy_volatility",
    }[difficulty]


def _expected_ladder_step(volatility_class: str, events: list[str]) -> str:
    if volatility_class == "heavy_volatility":
        return "renewables -> battery (pre-charged above floor) -> demand response -> grid import -> reserve floor only if the Evaluator's own emergency check agrees"
    if volatility_class == "some_volatility":
        return "renewables -> battery -> grid import, battery pre-charged ahead of the forecast event"
    return "renewables -> battery -> grid import (rarely needed on a calm day)"


def _expected_behavior(difficulty: Difficulty, objective: Objective | None, events: list[str]) -> str:
    base = {
        Objective.COST_EFFICIENCY: "Cascade: cost, then carbon, then renewable utilisation (within tolerance at each step).",
        Objective.MIN_CARBON: "Cascade: carbon, then cost, then renewable utilisation (within tolerance at each step).",
        Objective.MAX_RENEWABLE_UTILISATION: "Cascade: renewable utilisation, then cost, then carbon (within tolerance at each step).",
        Objective.MAX_PROFIT: "Cascade: profit, then cost, then carbon (carbon drops to last).",
        None: "No objective declared: cost_efficiency cascade applies under the golden rules.",
    }[objective]
    base += " Golden rules (reliability, grid stability, minimal curtailment, battery protection) are never traded away for any objective."
    if "battery_2_offline" in events:
        base += " One battery is offline — do not schedule actions against it."
    if "transmission_at_capacity" in events:
        base += " Transmission headroom is nearly exhausted — curtailment up to the minimum physically required may be a stability-forced exception, unlike normal conditions."
    if "demand_surge" in events:
        base += " Industrial demand has surged — reliability takes precedence over cost/carbon optimization."
    return base


_PROFILES = {
    Difficulty.D1_STABLE_DAY: dict(solar_range=(60, 90), wind_range=(30, 50), price_range=(30, 50), events=[]),
    Difficulty.D2_CLOUDY_AFTERNOON: dict(solar_range=(10, 30), wind_range=(30, 50), price_range=(30, 60), events=["cloud_cover"]),
    Difficulty.D2_PRICE_SPIKE: dict(solar_range=(50, 80), wind_range=(20, 40), price_range=(150, 300), events=["price_spike"]),
    Difficulty.D3_MULTI_FAILURE_CASCADE: dict(
        solar_range=(5, 20), wind_range=(60, 90), price_range=(180, 350),
        events=["battery_2_offline", "transmission_at_capacity", "demand_surge", "storm_alert"],
    ),
}


def generate_scenario(
    difficulty: Difficulty,
    objective: Objective | None = None,
    seed: int | None = None,
    previous_floor_pct: float = DEFAULT_PREVIOUS_FLOOR_PCT,
) -> EnvironmentState:
    concrete_seed = seed if seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
    rng = random.Random(concrete_seed)
    profile = _PROFILES[difficulty]
    events = list(profile["events"])

    solar_output = round(rng.uniform(*profile["solar_range"]), 1)
    wind_output = round(rng.uniform(*profile["wind_range"]), 1)
    price = round(rng.uniform(*profile["price_range"]), 1)
    solar_forecast = round(solar_output * rng.uniform(0.9, 1.1), 1)
    wind_forecast = round(wind_output * rng.uniform(0.9, 1.1), 1)

    degraded = "battery_2_offline" in events
    batteries = _base_batteries(rng, degraded=degraded)

    base_demand = round(rng.uniform(70, 110), 1)
    industrial_demand = round(rng.uniform(20, 40), 1)
    if "demand_surge" in events:
        industrial_demand = round(industrial_demand * 1.6, 1)
    base_demand_forecast = round(base_demand * rng.uniform(0.95, 1.1), 1)
    total_demand = round(base_demand + industrial_demand, 1)
    total_demand_forecast = round(base_demand_forecast + industrial_demand, 1)

    transmission_headroom = (
        TRANSMISSION_HEADROOM_CONSTRAINED_MW if "transmission_at_capacity" in events else TRANSMISSION_LINE_RATING_MW
    )

    volatility_class = _volatility_class(difficulty)
    floor_min, floor_max = FLOOR_BANDS[volatility_class]

    scenario = EnvironmentState(
        tick=_next_tick(),
        seed=concrete_seed,
        difficulty=difficulty,
        objective=objective,
        solar_output_mw=solar_output,
        solar_forecast_mw=solar_forecast,
        wind_output_mw=wind_output,
        wind_forecast_mw=wind_forecast,
        solar_farms=_split_solar_farms(rng, solar_output, solar_forecast),
        wind_farms=_split_wind_farms(rng, wind_output, wind_forecast),
        base_demand_mw=base_demand,
        base_demand_forecast_mw=base_demand_forecast,
        total_demand_mw=total_demand,
        total_demand_forecast_mw=total_demand_forecast,
        grid_frequency_hz=round(rng.uniform(49.9, 50.1), 3),
        transmission_constraint_mw=TRANSMISSION_LINE_RATING_MW,
        transmission_headroom_mw=transmission_headroom,
        batteries=batteries,
        previous_floor_pct=previous_floor_pct,
        electricity_price_per_mwh=price,
        carbon_price_per_ton=round(rng.uniform(20, 40), 1),
        demand_response_incentive_per_mwh=round(rng.uniform(10, 30), 1),
        weather_forecast="storm" if "storm_alert" in events else "clear",
        storm_alert="storm_alert" in events,
        maintenance_scheduled=False,
        industrial_demand_mw=industrial_demand,
        events=events,
        expected_behavior=_expected_behavior(difficulty, objective, events),
        expected_floor_min_pct=floor_min,
        expected_floor_max_pct=floor_max,
        expected_ladder_step=_expected_ladder_step(volatility_class, events),
        expected_emergency=False,  # placeholder, computed below once total_demand_mw etc. exist
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

    return normalized, corrections
