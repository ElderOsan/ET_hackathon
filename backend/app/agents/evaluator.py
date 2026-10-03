"""Evaluator (Comparison Layer).

Runs the full rule set (golden rules, severity "fail"; cascade/reserve-floor/repair checks,
severity "flagged") on the APPLIED decision (post-balancer, per Brief 2) — never the raw
model proposal. A failed "fail" rule means the decision is wrong regardless of objective; a
failed "flagged" rule means it diverges from what the declared objective would prefer, or
needed more than minor repair, without being unsafe.
"""
from __future__ import annotations

from app.data.rules import run_rules
from app.models.schemas import Decision, EnvironmentState, EvalResult, EvalStatus, FieldRepair


def evaluate(scenario: EnvironmentState, applied_decision: Decision, repairs: list[FieldRepair] | None = None) -> EvalResult:
    rules = run_rules(scenario, applied_decision, repairs)

    any_fail = any(not r.passed and r.severity == "fail" for r in rules)
    any_flagged = any(not r.passed and r.severity == "flagged" for r in rules)

    if any_fail:
        status = EvalStatus.FAIL
    elif any_flagged:
        status = EvalStatus.FLAGGED
    else:
        status = EvalStatus.PASS

    notes = (
        "All checks passed."
        if status == EvalStatus.PASS
        else "One or more golden rules violated." if status == EvalStatus.FAIL
        else "Golden rules held, but the decision diverges from the expected cascade, reserve-floor behavior, or needed balancer repair."
    )

    return EvalResult(tick=scenario.tick, status=status, rules=rules, notes=notes)
