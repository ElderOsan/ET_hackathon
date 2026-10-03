"""The rule set: Layer 1 golden rules (severity "fail", never traded away) and Layer 2 /
reserve-floor / cascade / repair checks (severity "flagged", worth a look but not an
automatic failure). Every rule is deterministic Python built only on app/data/physics.py
and app/data/balancer.py — no rule re-derives a power-balance quantity itself. Rules run
against the APPLIED decision (post-balancer), per Brief 2.
"""
from __future__ import annotations

from app.data import physics
from app.data.balancer import reference_dispatch
from app.data.tuning import (
    BALANCE_TOLERANCE_MW,
    CURTAIL_TOLERANCE_MW,
    FLOOR_BANDS,
    FLOOR_MAX,
    FLOOR_MIN,
    FREQ_BAND_HZ,
    OBJECTIVE_TOLERANCE_PCT,
    REPAIR_TOLERANCE_MW,
    RESERVE_MARGIN_PCT,
)
from app.models.schemas import Decision, EnvironmentState, FieldRepair, Objective, RuleResult


def _daily_high_threshold(scenario: EnvironmentState) -> float:
    # Simple proxy until historical price series exist (see Next Steps doc).
    return scenario.electricity_price_per_mwh * 0.95 if scenario.difficulty.value == "price_spike" else scenario.electricity_price_per_mwh + 1


def _volatility_signal_present(scenario: EnvironmentState) -> bool:
    return bool(
        scenario.storm_alert
        or scenario.electricity_price_per_mwh >= _daily_high_threshold(scenario)
        or any(not b.available for b in scenario.batteries)
        or "demand_surge" in scenario.events
        or "transmission_at_capacity" in scenario.events
    )


def is_emergency(scenario: EnvironmentState, floor_pct: float) -> bool:
    return physics.is_emergency(scenario, floor_pct)


# ---- Layer 1: golden rules (severity "fail") ----------------------------------------------


def rule_1_no_curtail_while_buying(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    curtailing = decision.curtail_solar_mw + decision.curtail_wind_mw
    buying = decision.market_action == "buy" and decision.market_amount_mw > 0
    min_required = physics.min_required_curtailment_mw(scenario)
    exempt_amount = min(curtailing, min_required)
    non_exempt = max(0.0, curtailing - exempt_amount)
    violation = non_exempt > 0 and buying
    passed = not violation
    if violation:
        detail = f"Curtailing {non_exempt:.1f}MW beyond the {min_required:.1f}MW physically required, while also buying from the grid."
    elif curtailing > 0 and buying:
        detail = f"Curtailing {curtailing:.1f}MW while buying, but all of it is within the {min_required:.1f}MW minimum physically required (stability-forced, exempt)."
    else:
        detail = "No simultaneous curtailment + grid purchase."
    return RuleResult(rule_id="rule_1", description="No curtailment beyond the minimum required while buying from the grid", severity="fail", passed=passed, detail=detail)


def rule_2a_battery_absolute_floor(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    batteries_by_id = {b.id: b for b in scenario.batteries}
    violations = []
    for action in decision.battery_actions:
        battery = batteries_by_id.get(action.battery_id)
        if battery is None or action.action != "discharge" or action.amount_mw <= 0:
            continue
        resulting_soc = physics.resulting_soc_pct(battery, action.amount_mw)
        if resulting_soc < battery.min_safe_soc_pct:
            violations.append(f"{battery.id} would drop to {resulting_soc:.1f}% (absolute floor {battery.min_safe_soc_pct}%)")
    passed = not violations
    detail = "; ".join(violations) if violations else "No battery discharged below its absolute minimum safe charge."
    return RuleResult(rule_id="rule_2a", description="Battery must not discharge below its absolute minimum safe charge", severity="fail", passed=passed, detail=detail)


def rule_3_unserved_load(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    unserved = physics.unserved_mw(scenario, decision)
    passed = unserved <= BALANCE_TOLERANCE_MW
    detail = (
        f"{unserved:.1f}MW of total demand ({scenario.total_demand_mw:.1f}MW) went unserved."
        if not passed
        else f"Total demand ({scenario.total_demand_mw:.1f}MW) fully served (unserved={unserved:.1f}MW)."
    )
    return RuleResult(rule_id="rule_3", description="Total demand must be served (unserved_mw within tolerance)", severity="fail", passed=passed, detail=detail)


def rule_3b_reserve_margin(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    unserved = physics.unserved_mw(scenario, decision)
    if unserved > BALANCE_TOLERANCE_MW:
        return RuleResult(rule_id="rule_3b", description="Reserve-margin headroom meets the requirement", severity="flagged", passed=True, detail="Not applicable — load is already unserved (see rule_3).")
    headroom = physics.reserve_margin_headroom_mw(scenario, decision, decision.applied_floor_pct)
    required = scenario.total_demand_mw * (RESERVE_MARGIN_PCT / 100)
    passed = headroom >= required
    detail = (
        f"Reserve-margin headroom {headroom:.1f}MW meets the {required:.1f}MW requirement ({RESERVE_MARGIN_PCT:.0f}% of total demand)."
        if passed
        else f"Reserve-margin headroom {headroom:.1f}MW is below the {required:.1f}MW requirement ({RESERVE_MARGIN_PCT:.0f}% of total demand) — load is served now but with thin margin."
    )
    return RuleResult(rule_id="rule_3b", description="Reserve-margin headroom meets the requirement", severity="flagged", passed=passed, detail=detail)


def rule_4_no_sell_while_unmet(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    unserved = physics.unserved_mw(scenario, decision)
    selling = decision.market_action == "sell" and decision.market_amount_mw > 0
    violation = selling and unserved > BALANCE_TOLERANCE_MW
    passed = not violation
    detail = (
        f"Selling {decision.market_amount_mw:.1f}MW while {unserved:.1f}MW of demand is unserved."
        if violation
        else "No sale while demand is unserved."
    )
    return RuleResult(rule_id="rule_4", description="No selling to the grid while demand is unserved (same unserved_mw as rule_3)", severity="fail", passed=passed, detail=detail)


def rule_5_no_charge_at_price_peak(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    threshold = _daily_high_threshold(scenario)
    charging = any(a.action == "charge" and a.amount_mw > 0 for a in decision.battery_actions)
    at_peak = scenario.electricity_price_per_mwh >= threshold
    emergency = physics.is_emergency(scenario, decision.applied_floor_pct)
    passed = not (charging and at_peak) or emergency
    if emergency and charging and at_peak:
        detail = "Charging at a price peak, but legitimate given the emergency."
    else:
        detail = (
            f"Charging battery while price ${scenario.electricity_price_per_mwh:.0f}/MWh is at/near the daily high (${threshold:.0f})."
            if not passed
            else "No charging during a price peak."
        )
    return RuleResult(rule_id="rule_5", description="Should not charge the battery at a daily price high outside an emergency", severity="flagged", passed=passed, detail=detail)


def rule_6_curtailment_amount(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    actual = decision.curtail_solar_mw + decision.curtail_wind_mw
    min_required = physics.min_required_curtailment_mw(scenario)
    excess = actual - min_required
    passed = excess <= CURTAIL_TOLERANCE_MW
    detail = (
        f"Curtailed {actual:.1f}MW vs {min_required:.1f}MW minimum required (excess {excess:.1f}MW > {CURTAIL_TOLERANCE_MW}MW tolerance)."
        if not passed
        else f"Curtailed {actual:.1f}MW vs {min_required:.1f}MW minimum required (within {CURTAIL_TOLERANCE_MW}MW tolerance)."
    )
    return RuleResult(rule_id="rule_6", description="Curtailment must not exceed the minimum physically required (amount-based)", severity="fail", passed=passed, detail=detail)


def rule_7_transmission_and_frequency(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    net_flow = physics.net_transmission_flow_mw(decision)
    flow_ok = abs(net_flow) <= scenario.transmission_headroom_mw + BALANCE_TOLERANCE_MW
    freq_ok = FREQ_BAND_HZ[0] <= scenario.grid_frequency_hz <= FREQ_BAND_HZ[1]
    passed = flow_ok and freq_ok
    problems = []
    if not flow_ok:
        problems.append(f"net flow {net_flow:.1f}MW exceeds transmission headroom {scenario.transmission_headroom_mw:.1f}MW")
    if not freq_ok:
        problems.append(f"grid frequency {scenario.grid_frequency_hz}Hz outside {FREQ_BAND_HZ[0]}-{FREQ_BAND_HZ[1]}Hz")
    detail = "; ".join(problems) if problems else "Net transmission flow and grid frequency both within limits."
    return RuleResult(rule_id="rule_7", description="Transmission headroom and grid frequency band respected", severity="fail", passed=passed, detail=detail)


def rule_8a_floor_hard_bounds(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    passed = FLOOR_MIN <= decision.applied_floor_pct <= FLOOR_MAX
    detail = (
        f"Applied floor {decision.applied_floor_pct}% is within [{FLOOR_MIN}, {FLOOR_MAX}]%."
        if passed
        else f"Applied floor {decision.applied_floor_pct}% is outside the hard bounds [{FLOOR_MIN}, {FLOOR_MAX}]% — the clamp should have prevented this."
    )
    return RuleResult(rule_id="rule_8a", description="Applied reserve floor stays within hard bounds (backstop)", severity="fail", passed=passed, detail=detail)


# ---- Layer 2: cascade, reserve-floor behavior, repairs (severity "flagged") ---------------


def rule_2b_battery_applied_floor(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    batteries_by_id = {b.id: b for b in scenario.batteries}
    emergency = physics.is_emergency(scenario, decision.applied_floor_pct)
    violations = []
    for action in decision.battery_actions:
        battery = batteries_by_id.get(action.battery_id)
        if battery is None or action.action != "discharge" or action.amount_mw <= 0:
            continue
        resulting_soc = physics.resulting_soc_pct(battery, action.amount_mw)
        if resulting_soc < decision.applied_floor_pct:
            violations.append(f"{battery.id} would drop to {resulting_soc:.1f}% (applied floor {decision.applied_floor_pct}%)")
    passed = not violations or emergency
    if emergency and violations:
        detail = "Discharged below the applied floor, but the Evaluator's own emergency check agrees this was necessary."
    else:
        detail = "; ".join(violations) if violations else "No battery discharged below the Orchestrator's own applied floor."
    return RuleResult(rule_id="rule_2b", description="Battery should not discharge below the Orchestrator's own applied floor outside an emergency", severity="flagged", passed=passed, detail=detail)


def rule_8b_floor_band_match(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    in_band = scenario.expected_floor_min_pct <= decision.proposed_floor_pct <= scenario.expected_floor_max_pct
    detail = (
        f"Proposed floor {decision.proposed_floor_pct}% is within the expected {scenario.expected_floor_min_pct}-{scenario.expected_floor_max_pct}% band."
        if in_band
        else f"Proposed floor {decision.proposed_floor_pct}% is outside the expected {scenario.expected_floor_min_pct}-{scenario.expected_floor_max_pct}% band for this scenario's volatility."
    )
    return RuleResult(rule_id="rule_8b", description="Proposed floor matches the expected band for this scenario's volatility", severity="flagged", passed=in_band, detail=detail)


def rule_8c_floor_raised_without_signal(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    calm_upper = FLOOR_BANDS["stable"][1]
    raised_above_calm = decision.proposed_floor_pct > calm_upper
    signal_present = _volatility_signal_present(scenario)
    passed = not raised_above_calm or signal_present
    detail = (
        f"Floor proposed at {decision.proposed_floor_pct}% (above the calm band's {calm_upper}%) with no volatility signal in the scenario."
        if not passed
        else f"Floor at {decision.proposed_floor_pct}% is either within the calm band or justified by a volatility signal."
    )
    return RuleResult(rule_id="rule_8c", description="A floor raised above the calm band needs a volatility signal", severity="flagged", passed=passed, detail=detail)


def rule_8d_floor_justification_present(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    passed = bool(decision.floor_justification and decision.floor_justification.strip())
    detail = "Floor justification provided." if passed else "No floor justification given in the decision."
    return RuleResult(rule_id="rule_8d", description="Decision states a justification for the proposed floor", severity="flagged", passed=passed, detail=detail)


def rule_8e_floor_clamped_or_ramped(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    passed = decision.proposed_floor_pct == decision.applied_floor_pct
    detail = (
        "Applied floor matches the proposed floor — no clamp or ramp adjustment needed."
        if passed
        else f"Code adjusted the floor: proposed {decision.proposed_floor_pct}% -> applied {decision.applied_floor_pct}% (clamp and/or ramp-down limit applied)."
    )
    return RuleResult(rule_id="rule_8e", description="Proposed floor required no clamp or ramp-down adjustment", severity="flagged", passed=passed, detail=detail)


_CASCADE_PRIORITY = {
    Objective.COST_EFFICIENCY: "cost",
    Objective.MIN_CARBON: "carbon",
    Objective.MAX_RENEWABLE_UTILISATION: "renewable_utilisation",
    Objective.MAX_PROFIT: "profit",
    None: "cost",
}


def rule_9_cascade_deviation(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    top_priority = _CASCADE_PRIORITY[scenario.objective]
    ref = reference_dispatch(scenario)

    if top_priority == "cost":
        actual_cost = (decision.market_amount_mw if decision.market_action == "buy" else 0.0) * scenario.electricity_price_per_mwh
        tolerance = max(ref["reference_cost"], 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        passed = actual_cost <= ref["reference_cost"] + tolerance
        detail = f"Net import cost ${actual_cost:.0f} vs reference ${ref['reference_cost']:.0f}" + ("." if passed else f" (exceeds {OBJECTIVE_TOLERANCE_PCT:.0f}% tolerance).")
    elif top_priority == "carbon":
        actual_import = decision.market_amount_mw if decision.market_action == "buy" else 0.0
        tolerance = max(ref["min_grid_import_mw"], 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        passed = actual_import <= ref["min_grid_import_mw"] + tolerance
        detail = f"Grid import {actual_import:.1f}MW (carbon proxy) vs reference minimum {ref['min_grid_import_mw']:.1f}MW" + ("." if passed else f" (exceeds {OBJECTIVE_TOLERANCE_PCT:.0f}% tolerance).")
    elif top_priority == "renewable_utilisation":
        actual_curtail = decision.curtail_solar_mw + decision.curtail_wind_mw
        min_required = physics.min_required_curtailment_mw(scenario)
        passed = actual_curtail <= min_required + CURTAIL_TOLERANCE_MW
        detail = f"Curtailed {actual_curtail:.1f}MW vs {min_required:.1f}MW minimum required" + ("." if passed else f" (exceeds {CURTAIL_TOLERANCE_MW}MW tolerance).")
    else:  # profit
        actual_revenue = (decision.market_amount_mw if decision.market_action == "sell" else 0.0) * scenario.electricity_price_per_mwh
        tolerance = max(ref["reference_revenue"], 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        passed = actual_revenue >= ref["reference_revenue"] - tolerance
        detail = f"Net revenue ${actual_revenue:.0f} vs reference ${ref['reference_revenue']:.0f}" + ("." if passed else f" (below {OBJECTIVE_TOLERANCE_PCT:.0f}% tolerance).")

    return RuleResult(rule_id="rule_9", description=f"Decision matches the declared cascade (top priority: {top_priority})", severity="flagged", passed=passed, detail=detail)


def rule_10_repair_magnitude(repairs: list[FieldRepair]) -> RuleResult:
    total_repair = sum(abs(r.delta_mw) for r in repairs)
    passed = total_repair <= REPAIR_TOLERANCE_MW
    detail = (
        f"Proposal needed {total_repair:.1f}MW of total repair across {len(repairs)} field(s) — above the {REPAIR_TOLERANCE_MW}MW tolerance."
        if not passed
        else f"Proposal needed {total_repair:.1f}MW of repair (within {REPAIR_TOLERANCE_MW}MW tolerance)." if repairs
        else "Proposal needed no repair."
    )
    return RuleResult(rule_id="rule_10", description="Proposal needed no more than minor balancer repair", severity="flagged", passed=passed, detail=detail)


def run_rules(scenario: EnvironmentState, decision: Decision, repairs: list[FieldRepair] | None = None) -> list[RuleResult]:
    repairs = repairs or []
    return [
        rule_1_no_curtail_while_buying(scenario, decision),
        rule_2a_battery_absolute_floor(scenario, decision),
        rule_2b_battery_applied_floor(scenario, decision),
        rule_3_unserved_load(scenario, decision),
        rule_3b_reserve_margin(scenario, decision),
        rule_4_no_sell_while_unmet(scenario, decision),
        rule_5_no_charge_at_price_peak(scenario, decision),
        rule_6_curtailment_amount(scenario, decision),
        rule_7_transmission_and_frequency(scenario, decision),
        rule_8a_floor_hard_bounds(scenario, decision),
        rule_8b_floor_band_match(scenario, decision),
        rule_8c_floor_raised_without_signal(scenario, decision),
        rule_8d_floor_justification_present(scenario, decision),
        rule_8e_floor_clamped_or_ramped(scenario, decision),
        rule_9_cascade_deviation(scenario, decision),
        rule_10_repair_magnitude(repairs),
    ]
