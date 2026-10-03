"""Pydantic schemas shared across the Scenario Agent, Orchestrator Agent, and Evaluator."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Difficulty(str, Enum):
    D1_STABLE_DAY = "stable_day"
    D2_CLOUDY_AFTERNOON = "cloudy_afternoon"
    D2_PRICE_SPIKE = "price_spike"
    D3_MULTI_FAILURE_CASCADE = "multi_failure_cascade"


class Objective(str, Enum):
    COST_EFFICIENCY = "cost_efficiency"
    MIN_CARBON = "min_carbon"
    MAX_RENEWABLE_UTILISATION = "max_renewable_utilisation"
    MAX_PROFIT = "max_profit"


class Battery(BaseModel):
    id: str
    capacity_mwh: float
    state_of_charge_pct: float
    min_safe_soc_pct: float = 10.0
    max_charge_rate_mw: float
    max_discharge_rate_mw: float
    charging_efficiency_pct: float
    degradation_pct: float
    available: bool = True


class SolarFarm(BaseModel):
    id: str
    capacity_mw: float
    output_mw: float
    forecast_mw: float


class WindFarm(BaseModel):
    id: str
    capacity_mw: float
    output_mw: float
    forecast_mw: float


class EnvironmentState(BaseModel):
    tick: int
    seed: int = Field(description="The RNG seed that produced this scenario — always concrete (generated if the caller didn't pass one), so any run can be reproduced.")
    difficulty: Difficulty
    objective: Optional[Objective] = Field(
        default=None,
        description="Declared Primary Objective for this scenario. None means cost_efficiency under the golden rules.",
    )

    solar_output_mw: float
    solar_forecast_mw: float
    wind_output_mw: float
    wind_forecast_mw: float

    solar_farms: list[SolarFarm] = Field(
        default_factory=list,
        description="Per-farm breakdown (5 farms) of solar_output_mw/solar_forecast_mw. Supplementary detail — totals above remain authoritative for dispatch logic.",
    )
    wind_farms: list[WindFarm] = Field(
        default_factory=list,
        description="Per-farm breakdown (3 farms) of wind_output_mw/wind_forecast_mw. Supplementary detail — totals above remain authoritative for dispatch logic.",
    )

    base_demand_mw: float = Field(description="Demand excluding industrial load. Combine with industrial_demand_mw via total_demand_mw — never add them yourself.")
    base_demand_forecast_mw: float
    total_demand_mw: float = Field(description="Code-computed: base_demand_mw + industrial_demand_mw. The only demand figure the prompt, Evaluator, and reference calculator may use.")
    total_demand_forecast_mw: float = Field(description="Code-computed: base_demand_forecast_mw + industrial_demand_mw.")
    grid_frequency_hz: float
    transmission_constraint_mw: float = Field(description="The grid interconnection's fixed line rating (MW). Not the per-tick available capacity — see transmission_headroom_mw.")
    transmission_headroom_mw: float = Field(
        description="Remaining capacity (MW) for net flow across the interconnection this tick (|sale - purchase| <= this). Normally equals transmission_constraint_mw; driven near zero by the transmission_at_capacity event. This is what the event actually constrains."
    )

    batteries: list[Battery]
    previous_floor_pct: float = Field(
        default=25.0,
        description="The reserve floor applied on the previous tick. Needed for the ramp-down rule; a single-tick scenario defaults to 25.",
    )

    electricity_price_per_mwh: float
    carbon_price_per_ton: float
    demand_response_incentive_per_mwh: float

    weather_forecast: str
    storm_alert: bool = False
    maintenance_scheduled: bool = False

    industrial_demand_mw: float
    events: list[str] = Field(default_factory=list)

    expected_behavior: str = Field(
        description="Heuristic-grounded narrative of what a correct decision should do here. Used by the Evaluator, never shown to the Orchestrator."
    )
    expected_floor_min_pct: float = Field(
        description="Hidden: the low end of the reserve-floor band expected for this scenario's volatility class."
    )
    expected_floor_max_pct: float = Field(
        description="Hidden: the high end of the reserve-floor band expected for this scenario's volatility class."
    )
    expected_ladder_step: str = Field(
        description="Hidden: the dispatch ladder step a correct decision should reach for this scenario."
    )
    expected_emergency: bool = Field(
        default=False,
        description="Hidden: whether this scenario is expected to force an emergency (reserve-floor) discharge.",
    )


class BatteryAction(BaseModel):
    battery_id: str
    action: str = Field(description="One of: charge, discharge, reserve, hold")
    amount_mw: float = 0.0


class Decision(BaseModel):
    tick: int
    objective_used: str = Field(description="Objective the orchestrator actually reasoned under (declared objective, or 'cost_efficiency' if none was supplied).")
    battery_actions: list[BatteryAction]
    market_action: str = Field(description="One of: buy, sell, hold, delay_sell")
    market_amount_mw: float = 0.0
    curtail_solar_mw: float = 0.0
    curtail_wind_mw: float = 0.0
    demand_response_triggered: bool = False
    proposed_floor_pct: float = Field(description="The reserve floor the model proposed, before code clamping/ramping.")
    applied_floor_pct: float = Field(description="The reserve floor actually in effect this tick, after the clamp and ramp-down rule.")
    floor_justification: str = Field(description="One-line reason for the proposed floor, naming the signals that drove it.")
    reasoning: str = Field(
        description="Step-by-step rationale: which golden rules were binding, which objective-cascade layer drove the choice, and which dispatch-ladder step was used."
    )


class FieldRepair(BaseModel):
    field: str
    proposed: float
    applied: float
    delta_mw: float
    reason: str


class RuleResult(BaseModel):
    rule_id: str
    description: str
    severity: Literal["fail", "flagged"]
    passed: bool
    detail: str


class EvalStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    FLAGGED = "flagged"


class EvalResult(BaseModel):
    tick: int
    status: EvalStatus
    rules: list[RuleResult]
    notes: str = ""


class ScenarioRunResult(BaseModel):
    scenario: EnvironmentState
    proposal: Decision = Field(description="What the Orchestrator (model) returned, before the balancer.")
    applied: Decision = Field(description="What was actually used — after the balancer made it physically consistent. The Evaluator judges this.")
    repairs: list[FieldRepair] = Field(default_factory=list)
    repaired: bool = Field(description="True if any repair's magnitude exceeded REPAIR_TOLERANCE_MW.")
    evaluation: EvalResult


class ObjectiveBreakdown(BaseModel):
    objective: str
    total: int
    passed: int
    flagged: int
    failed: int


class BatchRunSummary(BaseModel):
    seed: int = Field(description="The base seed for this batch — reusing it reproduces every scenario in the run.")
    total: int
    passed: int
    failed: int
    flagged: int
    pass_rate_pct: float
    repaired_count: int
    repair_rate_pct: float = Field(description="Share of scenarios whose proposal needed repair above REPAIR_TOLERANCE_MW. A high pass rate alongside a high repair rate means the balancer is doing the work, not the model.")
    by_objective: list[ObjectiveBreakdown]
    results: list[ScenarioRunResult]
