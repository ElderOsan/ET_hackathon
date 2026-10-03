"""The one pipeline every run mode shares (Brief 2): scenario -> Orchestrator -> balancer ->
Evaluator. Auto single, manual single, and batch all call run_decision_pipeline — none of
them re-implement rule or demand logic, or call decide()/balance()/evaluate() directly.
"""
from __future__ import annotations

from app.agents.evaluator import evaluate
from app.agents.orchestrator_agent import decide
from app.data.balancer import balance
from app.data.tuning import REPAIR_TOLERANCE_MW
from app.models.schemas import EnvironmentState, ScenarioRunResult


def run_decision_pipeline(scenario: EnvironmentState) -> ScenarioRunResult:
    proposal = decide(scenario)
    applied, repairs = balance(scenario, proposal)
    evaluation = evaluate(scenario, applied, repairs)
    repaired = sum(abs(r.delta_mw) for r in repairs) > REPAIR_TOLERANCE_MW
    return ScenarioRunResult(
        scenario=scenario,
        proposal=proposal,
        applied=applied,
        repairs=repairs,
        repaired=repaired,
        evaluation=evaluation,
    )
