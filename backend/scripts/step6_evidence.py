#!/usr/bin/env python
"""Step 6: deterministic evidence suite. No API calls anywhere in this script -- every
decision is either the deterministic dispatcher's own output or a hand-built bad/faulty
decision, evaluated with reevaluate_stored / evaluate directly.

Five pieces:
  A. Oracle run: the dispatcher's own decision over 200 scenarios should pass almost always
     (>=99%) -- it is the reference implementation, not just another decision-maker.
  B. Known-bad baselines: four naive strategies (random, always-hold, always-sell,
     always-charge) over the same 200 scenarios should each pass rarely (<=25%).
  C. Fault-injection matrix: 12 fault types x 6 profiles = 72 cases -- each fault is a single-field
     perturbation of a known-clean dispatcher decision, checked against the ONE rule it is
     designed to trip. Rules that are structurally coupled (e.g. rule_1/rule_6 both react to
     excess curtailment) are expected to co-trigger and are reported as such, not as false
     alarms; a true false alarm is any OTHER rule firing that has no such documented coupling.
  D. Prompt audit: every call actually recorded this session (recordings/*/calls/*.json) is
     scanned for hidden scenario fields, evaluator/rule output, an API key, or fixture text.
  E. Determinism: same seed -> identical scenario; same (scenario, decision) -> identical
     verdict, run twice.

Usage: python scripts/step6_evidence.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.evaluator import evaluate
from app.agents.orchestrator_agent import _HIDDEN_FIELDS
from app.agents.pipeline import reevaluate_stored
from app.agents.scenario_agent import generate_scenario
from app.data import physics
from app.data.dispatcher import dispatch
from app.data.tuning import FLOOR_MAX, FLOOR_MIN, GRID_CHARGE_CAP_TOLERANCE_MW
from app.models.schemas import BatteryAction, Decision, Difficulty, EvalStatus

ROOT = Path(__file__).resolve().parents[2]
PROFILES = [Difficulty.D1_STABLE_DAY, Difficulty.D2_CLOUDY_AFTERNOON, Difficulty.D2_PRICE_SPIKE, Difficulty.D3_MULTI_FAILURE_CASCADE, Difficulty.D4_SURPLUS_DAY, Difficulty.D5_SHORTFALL_DAY]
N_ORACLE = 200
BASELINE_SEED = 500_000


def _scenarios(n: int, base_seed: int):
    out = []
    for i in range(n):
        profile = PROFILES[i % len(PROFILES)]
        out.append(generate_scenario(profile, None, seed=base_seed + i))
    return out


# ---- A + B: oracle run and known-bad baselines --------------------------------------------


def _random_bad_decision(scenario, rng: random.Random) -> Decision:
    battery_actions = []
    for b in scenario.batteries:
        action = rng.choice(["charge", "discharge", "hold"])
        rate = b.max_charge_rate_mw if action == "charge" else b.max_discharge_rate_mw
        amount = round(rng.uniform(0, rate), 1) if action != "hold" else 0.0
        battery_actions.append(BatteryAction(battery_id=b.id, action=action, amount_mw=amount))
    market_action = rng.choice(["buy", "sell", "hold"])
    market_amount = round(rng.uniform(0, 50), 1) if market_action != "hold" else 0.0
    floor = round(rng.uniform(FLOOR_MIN, FLOOR_MAX), 1)
    return Decision(
        tick=scenario.tick, objective_used="cost_efficiency", battery_actions=battery_actions,
        market_action=market_action, market_amount_mw=market_amount,
        curtail_solar_mw=0.0, curtail_wind_mw=0.0, demand_response_triggered=False,
        proposed_floor_pct=floor, applied_floor_pct=floor,
        floor_justification="random baseline", reasoning="random baseline", mode="agent",
    )


def _always_hold_decision(scenario) -> Decision:
    return Decision(
        tick=scenario.tick, objective_used="cost_efficiency",
        battery_actions=[BatteryAction(battery_id=b.id, action="hold", amount_mw=0.0) for b in scenario.batteries],
        market_action="hold", market_amount_mw=0.0, curtail_solar_mw=0.0, curtail_wind_mw=0.0,
        demand_response_triggered=False, proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
        floor_justification="always-hold baseline", reasoning="always-hold baseline", mode="agent",
    )


def _always_sell_decision(scenario) -> Decision:
    return Decision(
        tick=scenario.tick, objective_used="cost_efficiency",
        battery_actions=[BatteryAction(battery_id=b.id, action="hold", amount_mw=0.0) for b in scenario.batteries],
        market_action="sell", market_amount_mw=scenario.transmission_headroom_mw, curtail_solar_mw=0.0, curtail_wind_mw=0.0,
        demand_response_triggered=False, proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
        floor_justification="always-sell baseline", reasoning="always-sell baseline", mode="agent",
    )


def _always_charge_decision(scenario) -> Decision:
    return Decision(
        tick=scenario.tick, objective_used="cost_efficiency",
        battery_actions=[BatteryAction(battery_id=b.id, action="charge", amount_mw=b.max_charge_rate_mw) for b in scenario.batteries],
        market_action="hold", market_amount_mw=0.0, curtail_solar_mw=0.0, curtail_wind_mw=0.0,
        demand_response_triggered=False, proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
        floor_justification="always-charge baseline", reasoning="always-charge baseline", mode="agent",
    )


def run_oracle_and_baselines():
    scenarios = _scenarios(N_ORACLE, BASELINE_SEED)
    rng = random.Random(42)

    def pass_rate(builder):
        passed = 0
        for s in scenarios:
            result = reevaluate_stored(s, builder(s, rng) if builder is _random_bad_decision else builder(s))
            applied = next(st for st in result.stages if st.name == "applied")
            if applied.evaluation.status == EvalStatus.PASS:
                passed += 1
        return passed, len(scenarios), round(100 * passed / len(scenarios), 1)

    results = {
        "oracle (dispatcher)": pass_rate(lambda s, r=None: dispatch(s, None)),
        "always-hold": pass_rate(_always_hold_decision),
        "always-sell": pass_rate(_always_sell_decision),
        "always-charge": pass_rate(_always_charge_decision),
        "random": pass_rate(_random_bad_decision),
    }
    return results


# ---- C: fault-injection matrix -------------------------------------------------------------


def _clean_baseline(scenario) -> Decision:
    return dispatch(scenario, None)


def _inject_rule_1_6(decision, scenario):
    # Extra curtailment beyond what's required removes that much served generation with
    # nothing compensating it, which necessarily shows up as unserved load too (rule_3) --
    # a structural consequence of the injection, not an unrelated false alarm.
    extra = physics.min_required_curtailment_mw(scenario) + 5.0
    d = decision.model_copy(update={"curtail_solar_mw": decision.curtail_solar_mw + extra, "market_action": "buy", "market_amount_mw": max(decision.market_amount_mw, 1.0)})
    return d, "rule_1", {"rule_6", "rule_3", "rule_9"}


def _inject_rule_2a(decision, scenario):
    # Amount far beyond anything a rate limit would allow -- guarantees resulting_soc deeply
    # negative regardless of the battery's starting SoC, isolating the absolute-floor check
    # from the rate-headroom question rule_2a doesn't itself consider.
    battery = scenario.batteries[0]
    huge_amount = battery.capacity_mwh / physics.TICK_HOURS * 2
    actions = [a for a in decision.battery_actions if a.battery_id != battery.id]
    actions.append(BatteryAction(battery_id=battery.id, action="discharge", amount_mw=huge_amount))
    d = decision.model_copy(update={"battery_actions": actions})
    return d, "rule_2a", {"rule_2b", "rule_3b"}


def _inject_rule_3(decision, scenario):
    # Curtail every MW of generation with nothing else changed -- forces unserved ==
    # total_demand_mw regardless of whether this scenario naturally has a shortfall.
    d = decision.model_copy(update={
        "curtail_solar_mw": scenario.solar_output_mw, "curtail_wind_mw": scenario.wind_output_mw,
        "market_action": "hold", "market_amount_mw": 0.0,
        "battery_actions": [BatteryAction(battery_id=a.battery_id, action="hold", amount_mw=0.0) for a in decision.battery_actions],
    })
    return d, "rule_3", {"rule_3b", "rule_6"}


def _inject_rule_4(decision, scenario):
    # Same forced-unserved trick as rule_3, plus a sale -- the sale while unmet is what rule_4
    # specifically checks; the unserved condition itself is the (documented) rule_3 co-trigger.
    d = decision.model_copy(update={
        "curtail_solar_mw": scenario.solar_output_mw, "curtail_wind_mw": scenario.wind_output_mw,
        "battery_actions": [BatteryAction(battery_id=a.battery_id, action="hold", amount_mw=0.0) for a in decision.battery_actions],
        "market_action": "sell", "market_amount_mw": 5.0,
    })
    return d, "rule_4", {"rule_3", "rule_3b", "rule_6", "rule_7"}


def _inject_rule_5(decision, scenario):
    # Convert a battery that was HOLDING in the clean baseline into a charge -- this must not
    # touch a battery that was actively discharging to cover real demand (that would create an
    # unserved-load side effect unrelated to the price-peak charging question rule_5 checks).
    holding = [a for a in decision.battery_actions if a.action == "hold"]
    target = holding[0].battery_id if holding else decision.battery_actions[0].battery_id
    battery = next(b for b in scenario.batteries if b.id == target)
    actions = [a for a in decision.battery_actions if a.battery_id != target]
    actions.append(BatteryAction(battery_id=target, action="charge", amount_mw=min(5.0, battery.max_charge_rate_mw)))
    d = decision.model_copy(update={"battery_actions": actions})
    # _daily_high_threshold only ever reaches "at peak" on a price_spike-tagged scenario
    # (threshold = price * 0.95); on every other profile threshold = price + 1, which price
    # itself can never reach. Tag the scenario price_spike so the fault is actually live.
    scenario_at_peak = scenario.model_copy(update={"difficulty": Difficulty.D2_PRICE_SPIKE, "electricity_price_per_mwh": scenario.electricity_price_per_mwh * 2 + 50})
    return d, "rule_5", {"rule_11", "rule_3"}, scenario_at_peak


def _inject_rule_6(decision, scenario):
    # Same unserved-load consequence as rule_1's injection, without the buy -- isolates the
    # pure amount-based excess-curtailment check from rule_1's buy-while-curtailing check.
    extra = physics.min_required_curtailment_mw(scenario) + 5.0
    d = decision.model_copy(update={"curtail_solar_mw": decision.curtail_solar_mw + extra, "market_action": "hold", "market_amount_mw": 0.0})
    return d, "rule_6", {"rule_3"}


def _inject_rule_7(decision, scenario):
    # A purchase this large overshoots total_demand_mw too, which can itself look like extra
    # (now unneeded) reserve-margin headroom or push rule_9's reference comparison off --
    # both are indirect numeric spillover from the same oversized purchase, not separate bugs.
    d = decision.model_copy(update={"market_action": "buy", "market_amount_mw": scenario.transmission_headroom_mw + 50.0})
    return d, "rule_7", {"rule_1", "rule_3b", "rule_9"}


def _inject_rule_8a(decision, scenario):
    # Forcing applied_floor_pct directly also breaks the clamp/ramp consistency check (rule_8e,
    # since no real clamp of the proposed floor would ever land outside the hard bounds) and,
    # if the baseline discharges at all, can make a previously-fine discharge look like it now
    # crosses the (moved) floor (rule_2b) -- both are mechanical consequences of moving the
    # same single field, not independent findings.
    d = decision.model_copy(update={"applied_floor_pct": FLOOR_MAX + 20.0})
    return d, "rule_8a", {"rule_8e", "rule_2b"}


def _inject_rule_8b(decision, scenario):
    # proposed_floor_pct changes without applied_floor_pct following it -- the clamp/ramp
    # consistency check (rule_8e) necessarily disagrees, a mechanical consequence of the same
    # single-field edit, not a separate finding.
    d = decision.model_copy(update={"proposed_floor_pct": max(FLOOR_MIN - 5.0, 0.0)})
    return d, "rule_8b", {"rule_8e"}


def _inject_rule_8d(decision, scenario):
    d = decision.model_copy(update={"floor_justification": ""})
    return d, "rule_8d", set()


def _inject_rule_8e(decision, scenario):
    d = decision.model_copy(update={"applied_floor_pct": round(decision.proposed_floor_pct + 15.0, 1)})
    return d, "rule_8e", {"rule_8a", "rule_2b"} if decision.proposed_floor_pct + 15.0 > FLOOR_MAX else {"rule_2b"}


def _inject_rule_11(decision, scenario):
    # The extra charge consumes generation/surplus that would otherwise have served load or
    # been sold -- unserved load (rule_3) and, if a sale was also active, selling-while-unmet
    # (rule_4) are structural consequences of the same single injected charge, not separate
    # findings. rule_5 (charging beyond unsellable surplus at a price peak) is ALSO a
    # structural consequence on any profile whose price clears DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    # -- state-based since the rule_8c/rule_5 fix, so no longer confined to the price_spike
    # profile the way the old difficulty-gated threshold was. Documented here, not a new
    # finding each time it fires.
    battery = scenario.batteries[0]
    surplus = physics.renewable_surplus_mw(scenario)
    actions = [a for a in decision.battery_actions if a.battery_id != battery.id]
    actions.append(BatteryAction(battery_id=battery.id, action="charge", amount_mw=surplus + 10.0))
    d = decision.model_copy(update={"battery_actions": actions})
    return d, "rule_11", {"rule_3", "rule_4", "rule_5"}


FAULT_INJECTORS = [
    _inject_rule_1_6, _inject_rule_2a, _inject_rule_3, _inject_rule_4, _inject_rule_5,
    _inject_rule_6, _inject_rule_7, _inject_rule_8a, _inject_rule_8b, _inject_rule_8d,
    _inject_rule_8e, _inject_rule_11,
]


def run_fault_matrix():
    rows = []
    for i, profile in enumerate(PROFILES):
        scenario = generate_scenario(profile, None, seed=900_000 + i)
        baseline = _clean_baseline(scenario)
        baseline_eval = evaluate(scenario, baseline, repairs=None, include_repair_rule=False)
        baseline_failed = {r.rule_id for r in baseline_eval.rules if not r.passed and r.applicable}

        for injector in FAULT_INJECTORS:
            out = injector(baseline, scenario)
            if len(out) == 4:
                faulty_decision, intended_rule, expected_cotriggers, eval_scenario = out
            else:
                faulty_decision, intended_rule, expected_cotriggers = out
                eval_scenario = scenario
            result = evaluate(eval_scenario, faulty_decision, repairs=None, include_repair_rule=False)
            failed = {r.rule_id for r in result.rules if not r.passed and r.applicable} - baseline_failed
            intended_caught = intended_rule in failed
            unexpected = failed - {intended_rule} - expected_cotriggers
            rows.append({
                "profile": profile.value, "fault": intended_rule, "intended_caught": intended_caught,
                "cotriggered": sorted(failed - {intended_rule}), "unexpected_false_alarms": sorted(unexpected),
            })
    return rows


# ---- D: prompt audit ------------------------------------------------------------------------


def run_prompt_audit():
    recordings_dir = ROOT / "recordings"
    findings = []
    checked = 0
    if not recordings_dir.exists():
        return {"checked": 0, "findings": ["no recordings/ directory found"]}
    for call_file in recordings_dir.glob("*/calls/*.json"):
        checked += 1
        text = call_file.read_text()
        for hidden in _HIDDEN_FIELDS:
            if f'"{hidden}"' in text:
                findings.append(f"{call_file}: hidden field {hidden!r} present")
        for needle in ("rule_1", "rule_2", "RuleResult", "EvalResult", "\"passed\":", "evaluator"):
            if needle.lower() in text.lower():
                findings.append(f"{call_file}: evaluator-output-shaped text {needle!r} present")
        for needle in ("AIza", "AQ."):
            if needle in text:
                findings.append(f"{call_file}: possible API key fragment {needle!r} present")
        if "fixture" in text.lower():
            findings.append(f"{call_file}: fixture hint present")
    return {"checked": checked, "findings": findings}


# ---- E: determinism -------------------------------------------------------------------------


def run_determinism_checks():
    s1 = generate_scenario(Difficulty.D3_MULTI_FAILURE_CASCADE, None, seed=777)
    s2 = generate_scenario(Difficulty.D3_MULTI_FAILURE_CASCADE, None, seed=777)
    # tick is a process-global counter, documented as never affected by the seed (see
    # orchestrator_agent.scenario_hash) -- excluded here for the same reason it's excluded there.
    scenario_identical = s1.model_dump(exclude={"tick"}) == s2.model_dump(exclude={"tick"})

    decision = dispatch(s1, None)
    e1 = evaluate(s1, decision, repairs=None, include_repair_rule=False)
    e2 = evaluate(s1, decision, repairs=None, include_repair_rule=False)
    verdict_identical = [r.model_dump() for r in e1.rules] == [r.model_dump() for r in e2.rules]
    return {"same_seed_identical_scenario": scenario_identical, "same_proposal_identical_verdict": verdict_identical}


def main():
    print("=== A + B: oracle run and known-bad baselines (200 scenarios each, no model calls) ===")
    oracle_and_baselines = run_oracle_and_baselines()
    for name, (passed, total, pct) in oracle_and_baselines.items():
        print(f"{name:24s} {passed:4d}/{total} = {pct:5.1f}% pass")

    print("\n=== C: fault-injection matrix (12 fault types x 6 profiles = 72 cases) ===")
    rows = run_fault_matrix()
    caught = sum(1 for r in rows if r["intended_caught"])
    false_alarms = [r for r in rows if r["unexpected_false_alarms"]]
    print(f"{caught}/{len(rows)} intended-rule detections")
    print(f"{len(false_alarms)} cases with an unexpected (undocumented) co-trigger")
    for r in rows:
        if not r["intended_caught"] or r["unexpected_false_alarms"]:
            print(" ", r)
    print("\nfull matrix:")
    for r in rows:
        print(f"  {r['profile']:22s} {r['fault']:10s} caught={r['intended_caught']!s:6s} cotriggered={r['cotriggered']} false_alarms={r['unexpected_false_alarms']}")

    print("\n=== D: prompt audit (recorded calls this session) ===")
    audit = run_prompt_audit()
    print(f"checked {audit['checked']} recorded call(s)")
    if audit["findings"]:
        for f in audit["findings"]:
            print("  FINDING:", f)
    else:
        print("  no hidden fields, evaluator output, API key fragments, or fixture hints found.")

    print("\n=== E: determinism checks ===")
    det = run_determinism_checks()
    for k, v in det.items():
        print(f"  {k}: {v}")

    out_path = ROOT / "evidence" / "step6_evidence.json"
    out_path.write_text(json.dumps({
        "oracle_and_baselines": {k: {"passed": v[0], "total": v[1], "pct": v[2]} for k, v in oracle_and_baselines.items()},
        "fault_matrix": rows,
        "prompt_audit": audit,
        "determinism": det,
    }, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
