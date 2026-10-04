"""The one pipeline every run mode shares (Brief 2 / Brief 2 Patch): scenario ->
Orchestrator -> balancer -> Evaluator, evaluated at both the "raw" (pre-balancer) and
"applied" (post-balancer) stages. Auto single, manual single, and batch all call
run_decision_pipeline — none of them re-implement rule or demand logic, or call
decide()/balance()/evaluate() directly.
"""
from __future__ import annotations

from app.agents.evaluator import evaluate
from app.agents.orchestrator_agent import decide
from app.data import physics
from app.data.balancer import balance
from app.data.tuning import BALANCE_TOLERANCE_MW, REPAIR_TOLERANCE_MW, RESERVE_MARGIN_PCT
from app.models.schemas import DecisionStage, EnvironmentState, ScenarioRunResult


def run_decision_pipeline(scenario: EnvironmentState) -> ScenarioRunResult:
    proposal = decide(scenario)
    raw_evaluation = evaluate(scenario, proposal, repairs=None, include_repair_rule=False)

    applied, repairs = balance(scenario, proposal)
    repaired = sum(abs(r.delta_mw) for r in repairs) > REPAIR_TOLERANCE_MW
    applied_evaluation = evaluate(scenario, applied, repairs, include_repair_rule=True)

    infeasible = physics.min_achievable_unserved_mw(scenario) > 0

    unserved = physics.unserved_mw(scenario, applied)
    margin_required = scenario.total_demand_mw * (RESERVE_MARGIN_PCT / 100)
    margin_achievable = physics.max_achievable_headroom_mw(scenario, applied.applied_floor_pct)
    margin_infeasible = unserved <= BALANCE_TOLERANCE_MW and margin_achievable < margin_required - BALANCE_TOLERANCE_MW

    return ScenarioRunResult(
        scenario=scenario,
        stages=[
            DecisionStage(name="raw", decision=proposal, evaluation=raw_evaluation),
            DecisionStage(name="applied", decision=applied, evaluation=applied_evaluation),
        ],
        repairs=repairs,
        repaired=repaired,
        infeasible=infeasible,
        margin_infeasible=margin_infeasible,
    )
