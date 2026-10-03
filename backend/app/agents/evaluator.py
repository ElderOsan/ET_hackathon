"""Evaluator (Comparison Layer).

Runs the full rule set (golden rules, severity "fail"; cascade/reserve-floor/repair checks,
severity "flagged") against a decision. Brief 2 Patch: called once per stage — "raw" (the
model's proposal, before the balancer, rule_10 excluded) and "applied" (after the balancer,
all rules) — so both the model's own score and the system's final score are visible.
"""
from __future__ import annotations

from app.data.rules import run_rules
from app.models.schemas import Decision, EnvironmentState, EvalResult, EvalStatus, FieldRepair


def evaluate(scenario: EnvironmentState, decision: Decision, repairs: list[FieldRepair] | None = None, include_repair_rule: bool = True) -> EvalResult:
    rules = run_rules(scenario, decision, repairs, include_repair_rule=include_repair_rule)

    any_fail = any(not r.passed and r.applicable and r.severity == "fail" for r in rules)
    any_flagged = any(not r.passed and r.applicable and r.severity == "flagged" for r in rules)

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
