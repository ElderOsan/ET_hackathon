"""The one pipeline every run mode shares (Brief 2 / Brief 2 Patch): scenario ->
Orchestrator -> balancer -> Evaluator, evaluated at both the "raw" (pre-balancer) and
"applied" (post-balancer) stages. Auto single, manual single, and batch all call
run_decision_pipeline — none of them re-implement rule or demand logic, or call
decide()/balance()/evaluate() directly.
"""
from __future__ import annotations

import logging

from app.agents.evaluator import evaluate
from app.agents.orchestrator_agent import CallFailure
from app.data import physics
from app.data.recording import LiveRecorder, Recorder
from app.data.balancer import balance
from app.data.tuning import BALANCE_TOLERANCE_MW, RESERVE_MARGIN_PCT
from app.models.schemas import (
    BatteryAction,
    Decision,
    DecisionStage,
    EnvironmentState,
    EvalResult,
    EvalStatus,
    RuleResult,
    ScenarioRunResult,
    TickLedger,
)

logger = logging.getLogger(__name__)


def _call_failure_result(scenario: EnvironmentState, failure: CallFailure) -> ScenarioRunResult:
    """Patch 3, Step 1: a model-call or parse failure is never silently dropped from a batch
    and never crashes it — it becomes a placeholder (hold-everything) decision, always
    evaluated as FAIL, so it's counted in every report exactly like any other scenario."""
    mode = "model_call_failed" if failure.kind == "infrastructure" else "parse_failed"
    placeholder = Decision(
        tick=scenario.tick,
        objective_used=scenario.objective.value if scenario.objective else "cost_efficiency",
        battery_actions=[BatteryAction(battery_id=b.id, action="hold", amount_mw=0.0) for b in scenario.batteries],
        market_action="hold", market_amount_mw=0.0,
        curtail_solar_mw=0.0, curtail_wind_mw=0.0,
        demand_response_triggered=False,
        proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
        floor_justification=f"N/A — {mode}", reasoning=f"No decision produced: {failure.detail}",
        mode=mode, failure_detail=failure.detail,
    )
    fail_rule = RuleResult(
        rule_id="rule_model_call", description="The Orchestrator must return a usable decision", severity="fail",
        passed=False, detail=f"{mode}: {failure.detail}",
    )
    fail_eval = EvalResult(tick=scenario.tick, status=EvalStatus.FAIL, rules=[fail_rule], notes=f"Model call failed ({failure.kind}) — scenario could not be judged on its merits.")
    infeasible = physics.min_achievable_unserved_mw(scenario) > 0
    return ScenarioRunResult(
        scenario=scenario,
        stages=[
            DecisionStage(name="raw", decision=placeholder, evaluation=fail_eval),
            DecisionStage(name="applied", decision=placeholder, evaluation=fail_eval),
        ],
        repairs=[], repaired=False, infeasible=infeasible, margin_infeasible=False,
        ledger=TickLedger(**physics.build_tick_ledger(scenario, placeholder)),
    )


def _evaluate_proposal(scenario: EnvironmentState, proposal: Decision) -> ScenarioRunResult:
    """Everything after a proposal exists: balance, evaluate both stages, compute infeasible/
    margin flags. Shared by run_decision_pipeline (a fresh or replayed model call) and
    reevaluate_stored (Patch 3 addendum — re-scoring an already-obtained proposal under
    today's rules/balancer/physics code, with no model call at all)."""
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
        ledger=TickLedger(**physics.build_tick_ledger(scenario, applied)),
    )


def run_decision_pipeline(scenario: EnvironmentState, recorder: Recorder | None = None) -> ScenarioRunResult:
    """recorder selects live / record / replay (Patch 3, Step 2) — defaults to a live call
    with nothing recorded, identical to every behavior before this step. Whichever recorder
    is used, everything below this line (balancer, Evaluator, physics) always runs live."""
    recorder = recorder or LiveRecorder()
    try:
        proposal = recorder.get_decision(scenario)
    except CallFailure as e:
        return _call_failure_result(scenario, e)
    return _evaluate_proposal(scenario, proposal)


def reevaluate_stored(scenario: EnvironmentState, proposal: Decision) -> ScenarioRunResult:
    """Re-scores an already-obtained raw proposal (e.g. loaded from a stored JSONL row) under
    the CURRENT rules/balancer/physics code — no model call, no recorder. This is how a rule
    change is tested against old results without spending API quota (Patch 3 addendum)."""
    return _evaluate_proposal(scenario, proposal)
