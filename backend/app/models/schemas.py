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
    D4_SURPLUS_DAY = "surplus_day"
    D5_SHORTFALL_DAY = "shortfall_day"


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
    buy_price_per_mwh: float = Field(description="Code-computed: electricity_price_per_mwh with the PRICE_SPREAD_PCT markup — what a purchase actually costs. Never re-derive it yourself.")
    sell_price_per_mwh: float = Field(description="Code-computed: electricity_price_per_mwh with the PRICE_SPREAD_PCT markdown — what a sale actually earns. Never re-derive it yourself.")
    carbon_price_per_ton: float
    grid_carbon_intensity_t_per_mwh: float = Field(description="Addendum C: tonnes of CO2 per MWh of grid import, sampled independently of electricity_price_per_mwh — cheap-and-dirty and expensive-and-clean scenarios both occur. min_carbon's metric is emissions (import_mwh x this), not raw import MW. carbon_price_per_ton converts emissions to an informational dollar cost only; it is never added to the cost metric.")
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
    mode: Literal["agent", "model_call_failed", "parse_failed", "safe_mode"] = Field(
        default="agent",
        description="'agent' is a real model decision. 'model_call_failed'/'parse_failed' are placeholder decisions (hold everything) produced only when EVEN the safe-mode dispatcher fallback could not run — always evaluated as FAIL (Patch 3, Step 1). 'safe_mode' (Patch 3, Step 4) is the deterministic dispatcher's own complete decision, used when the Orchestrator couldn't respond, judged by the Evaluator exactly like an agent decision — never counted in the agent's own pass rate (see BatchRunSummary.safe_mode_*).",
    )
    failure_detail: Optional[str] = Field(default=None, description="Error detail when mode is not 'agent'.")


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
    applicable: bool = Field(default=True, description="False means this rule could not be judged for this decision (e.g. rule_3b when load is already unserved) — display as N/A, not as a pass.")
    detail: str
    value_label: Optional[str] = Field(default=None, description="For two-number rules (3, 6, 9): what the two values are, e.g. 'unserved vs. achievable minimum'.")
    value_actual: Optional[float] = None
    value_reference: Optional[float] = None


class EvalStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    FLAGGED = "flagged"


class EvalResult(BaseModel):
    tick: int
    status: EvalStatus
    rules: list[RuleResult]
    notes: str = ""


class DecisionStage(BaseModel):
    name: Literal["raw", "applied"] = Field(description="'raw' = the Orchestrator's proposal exactly as submitted, before the balancer. 'applied' = after the balancer. A list, not two fixed fields, so a later stage (Brief 3's preflight loop) can be inserted between them without another schema change.")
    decision: Decision
    evaluation: EvalResult


class TickLedger(BaseModel):
    """Addendum C, point 8: computed per tick, by code, never by the model. Displaying this
    is later report work, not Round 0 — it's stored on every run record starting now so
    nothing has to be recomputed retroactively."""
    purchase_cost: float
    sales_revenue: float
    stored_energy_value_change: float = Field(description="Net change in stored energy (charge added minus discharge removed, after charging efficiency) valued at sell_price_per_mwh. Positive = batteries gained value this tick.")
    profit: float = Field(description="sales_revenue - purchase_cost + stored_energy_value_change.")
    emissions_tonnes: float = Field(description="grid import MWh x grid_carbon_intensity_t_per_mwh.")
    carbon_cost: float = Field(description="emissions_tonnes x carbon_price_per_ton — informational only, never added to the cost metric.")
    renewable_utilisation_pct: float = Field(description="(generation - curtailment) / generation x 100. Stored and sold energy both count as utilised; only curtailment counts against it.")
    renewable_share_of_delivered_pct: float = Field(description="(generation - curtailment) / total_demand x 100, capped at 100 — informational: how much of total demand was met by non-curtailed renewable generation this tick.")


class ScenarioRunResult(BaseModel):
    scenario: EnvironmentState
    stages: list[DecisionStage]
    repairs: list[FieldRepair] = Field(default_factory=list)
    repaired: bool = Field(description="True if any repair's magnitude exceeded REPAIR_TOLERANCE_MW.")
    infeasible: bool = Field(default=False, description="True if this scenario's min_achievable_unserved_mw > 0 — full service was physically impossible no matter the decision. The generator should never produce these; a nonzero count means a generator bug, not a model error.")
    margin_infeasible: bool = Field(default=False, description="True if load is served but max_achievable_headroom_mw is below the reserve-margin requirement — no decision could reach rule_3b's target this tick. Unlike `infeasible`, this is expected to happen sometimes (extreme cascades are the point) and is reported, not treated as a bug.")
    ledger: Optional[TickLedger] = Field(default=None, description="Addendum C: the applied decision's computed per-tick ledger.")


class ObjectiveBreakdown(BaseModel):
    objective: str
    total: int
    passed: int
    flagged: int
    failed: int


class CategoryBreakdown(BaseModel):
    category: str
    failed_or_flagged: int


class UnresolvedRun(BaseModel):
    tick: int
    seed: int
    profile: str
    objective: str
    mode: str = Field(description="'model_call_failed' (infrastructure, retries exhausted) or 'parse_failed' (schema/parse error).")
    detail: str


class BatchRunSummary(BaseModel):
    seed: int = Field(description="The base seed for this batch — reusing it reproduces every scenario in the run.")
    seed_set: Optional[str] = Field(default=None, description="Name of the benchmark seed set used ('dev' or 'held_out'), if this run used one rather than an ad-hoc seed.")
    total: int
    infeasible_count: int = Field(description="Scenarios where min_achievable_unserved_mw > 0 — full service was physically impossible. Should always be 0; nonzero means a generator bug, not a model error.")
    judged_count: int = Field(default=0, description="Scenarios counted in first_attempt/applied_pass_rate_pct below: not infeasible AND mode=='agent'. Patch 3, Step 1: N/A is a per-rule result, never a scenario exclusion (replaces Patch 2's na_count-based denominator shrinkage). Patch 3, Step 4 honesty requirement: a safe_mode (or the now-rare model_call_failed/parse_failed) row is excluded here too, reported separately via safe_mode_* / unresolved below — it never inflates or deflates the agent's own score.")
    margin_infeasible_count: int = Field(default=0, description="Scenarios where load is served but no decision could reach the reserve-margin target (rule_3b). Expected to be nonzero sometimes — extreme cascades are the point, not a bug.")
    na_counts_by_rule: dict[str, int] = Field(default_factory=dict, description="Per-rule N/A counts at the applied stage (e.g. rule_9, rule_5, rule_3b) — informational only, never subtracted from any denominator.")
    unresolved_count: int = Field(default=0, description="Scenarios where EVEN the safe-mode dispatcher fallback could not run (model_call_failed or parse_failed, no CallFailure handler caught it) — always evaluated as FAIL on their own merits, but excluded from judged_count like a safe_mode row (Patch 3, Step 4).")
    unresolved: list[UnresolvedRun] = Field(default_factory=list)

    safe_mode_count: int = Field(default=0, description="Scenarios where the Orchestrator couldn't respond and the deterministic dispatcher (app/data/dispatcher.py) produced the decision instead, mode=='safe_mode'. The Evaluator judges these exactly like an agent decision — see safe_mode_passed/safe_mode_pass_rate_pct — but they are never mixed into the agent's own first_attempt/applied_pass_rate_pct (Patch 3, Step 4 honesty requirement).")
    safe_mode_passed: int = Field(default=0)
    safe_mode_pass_rate_pct: float = Field(default=0.0, description="Pass rate of safe-mode decisions alone, applied stage. Not comparable to the agent's own rate — it measures the dispatcher's floor, not the model.")

    first_attempt_passed: int = Field(description="The Orchestrator's own raw proposal, judged before any balancer repair — the true score of the model. mode=='agent' rows only.")
    first_attempt_pass_rate_pct: float

    applied_passed: int
    applied_failed: int
    applied_flagged: int
    applied_pass_rate_pct: float

    repaired_count: int
    repair_rate_pct: float = Field(description="Share of scenarios whose proposal needed repair above REPAIR_TOLERANCE_MW. A high applied pass rate alongside a high repair rate means the balancer is doing the work, not the model.")

    raw_category_breakdown: list[CategoryBreakdown] = Field(description="Raw-stage failed/flagged rules grouped into arithmetic / strategy / outcome via the CONFIG category map.")

    by_objective: list[ObjectiveBreakdown]
    results: list[ScenarioRunResult]
