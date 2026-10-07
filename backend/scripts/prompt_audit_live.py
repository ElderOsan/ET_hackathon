#!/usr/bin/env python
"""Live-build prompt audit: unlike step6_evidence.py's prompt-audit piece (which scans
TEXT ALREADY RECORDED under recordings/*/calls/*.json -- a historical record of what was
actually sent, under whatever prompt was live at recording time), this script calls
orchestrator_agent.build_request(scenario) directly against freshly generated scenarios.
No recorder, no API key, no network call -- it audits exactly what the CURRENT prompt +
schema + orchestrator_facts() would send, for scenarios no recording has ever covered.

Checks per request, same categories as step6_evidence.py's audit:
  - no hidden scenario field (app.agents.orchestrator_agent._HIDDEN_FIELDS) anywhere in the
    built contents or system_instruction
  - no evaluator/rule-output-shaped text (RuleResult/EvalResult/"passed":/rule_<n> id strings)
  - no API key substring (either Google key shape, or the literal configured key if one is set)
  - no fixture-specific literal text ("fixture", "smoke", "audit_h", "round0", run-id-looking
    strings) that would mean a test artifact leaked into the live prompt path
  - every value orchestrator_facts() computes is present in the built contents (sanity check
    that build_request and orchestrator_facts haven't drifted apart)

Usage: python scripts/prompt_audit_live.py [n_per_difficulty]  (default 50 -> 300 requests
across the 6 generated difficulties x cost_efficiency/min_carbon/max_renewable_utilisation/
max_profit/None, cycled)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import orchestrator_agent
from app.agents.scenario_agent import generate_scenario
from app.core.config import GEMINI_API_KEY
from app.data import physics
from app.models.schemas import GENERATED_DIFFICULTIES, Objective

N_PER_DIFFICULTY = int(sys.argv[1]) if len(sys.argv) > 1 else 50
BASE_SEED = 700_000_000

OBJECTIVE_CYCLE = [None, Objective.COST_EFFICIENCY, Objective.MIN_CARBON, Objective.MAX_RENEWABLE_UTILISATION, Objective.MAX_PROFIT]

API_KEY_PATTERNS = ("AIza", "AQ.")
EVALUATOR_SHAPED_NEEDLES = ("RuleResult", "EvalResult", '"passed":', "ruleresult", "evalresult")
RULE_ID_NEEDLE_PREFIXES = ("rule_1", "rule_2", "rule_3", "rule_4", "rule_5", "rule_6", "rule_7", "rule_8", "rule_9", "rule_10", "rule_11")
FIXTURE_HINT_NEEDLES = ("fixture", "smoke_", "audit_h", "round0", "day_report_example", "probe_ladder_reword", "example_96row_day")


def check_request(scenario, request: dict) -> list[str]:
    problems = []
    haystack = request["contents"] + "\n" + request["system_instruction"]
    haystack_lower = haystack.lower()

    for hidden in orchestrator_agent._HIDDEN_FIELDS:
        if f'"{hidden}"' in haystack:
            problems.append(f"hidden field {hidden!r} present in built request")

    for needle in EVALUATOR_SHAPED_NEEDLES:
        if needle.lower() in haystack_lower:
            problems.append(f"evaluator-output-shaped text {needle!r} present")

    for prefix in RULE_ID_NEEDLE_PREFIXES:
        # the SYSTEM_PROMPT legitimately names rule concepts in prose (golden rules, etc.) but
        # never the bare rule_<n> ids the Evaluator uses internally -- those must never appear.
        if prefix in haystack_lower:
            problems.append(f"rule-id-shaped text {prefix!r} present")

    for pattern in API_KEY_PATTERNS:
        if pattern in haystack:
            problems.append(f"possible API key shape {pattern!r} present")
    if GEMINI_API_KEY and GEMINI_API_KEY in haystack:
        problems.append("the configured API key literal is present")

    for needle in FIXTURE_HINT_NEEDLES:
        if needle in haystack_lower:
            problems.append(f"fixture/test-artifact hint {needle!r} present")

    facts = physics.orchestrator_facts(scenario, scenario.previous_floor_pct)
    for key in facts:
        if key not in request["contents"]:
            problems.append(f"orchestrator_facts() key {key!r} missing from the built request")

    return problems


def main():
    checked = 0
    all_problems: list[tuple[int, int, str]] = []
    seed = BASE_SEED
    for difficulty in GENERATED_DIFFICULTIES:
        for i in range(N_PER_DIFFICULTY):
            objective = OBJECTIVE_CYCLE[i % len(OBJECTIVE_CYCLE)]
            scenario = generate_scenario(difficulty, objective, seed=seed)
            seed += 1
            request = orchestrator_agent.build_request(scenario)
            checked += 1
            for p in check_request(scenario, request):
                all_problems.append((scenario.tick, scenario.seed, p))

    print(f"checked {checked} requests built from current code (orchestrator_agent.build_request), "
          f"across {len(GENERATED_DIFFICULTIES)} difficulties x up to {len(OBJECTIVE_CYCLE)} objectives -- "
          f"no model calls, no recordings read.")
    if all_problems:
        print(f"\n{len(all_problems)} FINDING(S):")
        for tick, seed_val, p in all_problems:
            print(f"  seed={seed_val}: {p}")
        sys.exit(1)
    print("no hidden fields, evaluator-output-shaped text, rule ids, API key fragments, "
          "fixture hints, or missing facts found in any built request.")


if __name__ == "__main__":
    main()
