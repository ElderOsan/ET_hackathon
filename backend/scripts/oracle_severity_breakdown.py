#!/usr/bin/env python
"""Report only: the Step 6 oracle's 200 scenarios, split by severity -- golden-rule (fail)
pass count, and advisory (flagged) rule failure counts by rule_id. No model calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.pipeline import reevaluate_stored
from app.agents.scenario_agent import generate_scenario
from app.data.dispatcher import dispatch
from app.models.schemas import Difficulty

PROFILES = [Difficulty.D1_STABLE_DAY, Difficulty.D2_CLOUDY_AFTERNOON, Difficulty.D2_PRICE_SPIKE, Difficulty.D3_MULTI_FAILURE_CASCADE, Difficulty.D4_SURPLUS_DAY, Difficulty.D5_SHORTFALL_DAY]
BASELINE_SEED = 500_000
N_ORACLE = 200

golden_pass = 0
golden_fail_rules: dict[str, int] = {}
advisory_flag_rules: dict[str, int] = {}
clean_pass = 0

for i in range(N_ORACLE):
    profile = PROFILES[i % len(PROFILES)]
    scenario = generate_scenario(profile, None, seed=BASELINE_SEED + i)
    decision = dispatch(scenario, None)
    result = reevaluate_stored(scenario, decision)
    applied = next(s for s in result.stages if s.name == "applied")
    rules = applied.evaluation.rules

    any_golden_fail = False
    for r in rules:
        if not r.applicable:
            continue
        if r.severity == "fail" and not r.passed:
            any_golden_fail = True
            golden_fail_rules[r.rule_id] = golden_fail_rules.get(r.rule_id, 0) + 1
        elif r.severity == "flagged" and not r.passed:
            advisory_flag_rules[r.rule_id] = advisory_flag_rules.get(r.rule_id, 0) + 1

    if not any_golden_fail:
        golden_pass += 1
    if applied.evaluation.status.value == "pass":
        clean_pass += 1

print(f"=== Dispatcher-as-oracle, 200 scenarios, by severity ===")
print(f"Golden-rule pass (no severity='fail' rule failed): {golden_pass}/{N_ORACLE} = {round(100*golden_pass/N_ORACLE,1)}%")
print(f"Golden-rule fail counts by rule: {golden_fail_rules}")
print(f"Clean pass (status=='pass', i.e. no fail AND no flag): {clean_pass}/{N_ORACLE} = {round(100*clean_pass/N_ORACLE,1)}%")
print(f"Advisory (flagged) failure counts by rule_id: {advisory_flag_rules}")
