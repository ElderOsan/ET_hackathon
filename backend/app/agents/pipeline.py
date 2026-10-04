"""The one pipeline every run mode shares (Brief 2 / Brief 2 Patch): scenario ->
Orchestrator -> balancer -> Evaluator, evaluated at both the "raw" (pre-balancer) and
"applied" (post-balancer) stages. Auto single, manual single, and batch all call
run_decision_pipeline — none of them re-implement rule or demand logic, or call
decide()/balance()/evaluate() directly.
"""
from __future__ import annotations

import logging

from app.agents.evaluator import evaluate
from app.agents.orchestrator_agent import decide
from app.data import physics
from app.data.balancer import balance
from app.data.tuning import BALANCE_TOLERANCE_MW, RESERVE_MARGIN_PCT
from app.models.schemas import DecisionStage, EnvironmentState, ScenarioRunResult

logger = logging.getLogger(__name__)


def run_decision_pipeline(scenario: EnvironmentState) -> ScenarioRunResult:
    proposal = decide(scenario)
    raw_evaluation = evaluate(scenario, proposal, repairs=None, include_repair_rule=False)

    applied, repairs = balance(scenario, proposal)
    # Brief 2 Patch 2, Step 4: "repaired" means any change was recorded, however small — the
    # repair-magnitude TOLERANCE belongs to rule_10 alone, not to this flag.
    repaired = len(repairs) > 0
    applied_evaluation = evaluate(scenario, applied, repairs, include_repair_rule=True)

    if not repairs and raw_evaluation.status != applied_evaluation.status:
        # The balancer recorded no change at all, so the applied decision is identical to
        # the raw proposal — the two verdicts must then agree (the only structural difference
        # is rule_10, which trivially passes with an empty repair log). Disagreement here
        # means the raw/applied evaluation paths disagree on an unchanged decision, not a
        # legitimate effect of balancer repair — log it loudly rather than let it pass
        # silently (this was row 49's "Repaired: no" symptom before the Step 4 fix).
        logger.error(
            "INCONSISTENT_VERDICT: tick=%s raw_status=%s applied_status=%s raw_decision=%s applied_decision=%s",
            scenario.tick, raw_evaluation.status, applied_evaluation.status,
            proposal.model_dump(), applied.model_dump(),
        )

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
