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
    achievable = physics.min_achievable_unserved_mw(scenario)
    excess = unserved - achievable
    passed = excess <= BALANCE_TOLERANCE_MW
    detail = (
        f"{unserved:.1f}MW unserved vs {achievable:.1f}MW achievable minimum — {excess:.1f}MW is the decision's own fault, not physics."
        if not passed
        else (
            f"{unserved:.1f}MW unserved matches the {achievable:.1f}MW physically achievable minimum — this scenario is infeasible, not a decision error."
            if achievable > BALANCE_TOLERANCE_MW
            else f"Total demand ({scenario.total_demand_mw:.1f}MW) fully served (unserved={unserved:.1f}MW)."
        )
    )
    return RuleResult(
        rule_id="rule_3", description="Unserved load must not exceed the physically achievable minimum", severity="fail", passed=passed, detail=detail,
        value_label="unserved vs. achievable minimum", value_actual=round(unserved, 1), value_reference=round(achievable, 1),
    )


def rule_3b_reserve_margin(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    unserved = physics.unserved_mw(scenario, decision)
    if unserved > BALANCE_TOLERANCE_MW:
        return RuleResult(rule_id="rule_3b", description="Reserve-margin headroom meets the achievable target", severity="flagged", passed=True, applicable=False, detail="N/A — load is already unserved (see rule_3).")
    headroom = physics.reserve_margin_headroom_mw(scenario, decision, decision.applied_floor_pct)
    achievable = physics.max_achievable_headroom_mw(scenario, decision.applied_floor_pct)
    required = scenario.total_demand_mw * (RESERVE_MARGIN_PCT / 100)
    target = min(required, achievable)
    margin_infeasible = achievable < required - BALANCE_TOLERANCE_MW
    passed = headroom >= target - BALANCE_TOLERANCE_MW
    if margin_infeasible:
        detail = (
            f"Reserve-margin headroom {headroom:.1f}MW meets the best achievable {achievable:.1f}MW — "
            f"margin infeasible this tick; best possible {achievable:.1f}MW (the {required:.1f}MW requirement cannot be reached by any decision)."
            if passed
            else f"Reserve-margin headroom {headroom:.1f}MW is below the best achievable {achievable:.1f}MW — "
            f"margin infeasible this tick; best possible {achievable:.1f}MW (the {required:.1f}MW requirement cannot be reached by any decision)."
        )
    else:
        detail = (
            f"Reserve-margin headroom {headroom:.1f}MW meets the {required:.1f}MW requirement ({RESERVE_MARGIN_PCT:.0f}% of total demand)."
            if passed
            else f"Reserve-margin headroom {headroom:.1f}MW is below the {required:.1f}MW requirement ({RESERVE_MARGIN_PCT:.0f}% of total demand) — load is served now but with thin margin."
        )
    return RuleResult(
        rule_id="rule_3b", description="Reserve-margin headroom meets the achievable target", severity="flagged", passed=passed, detail=detail,
        value_label="headroom vs. target", value_actual=round(headroom, 1), value_reference=round(target, 1),
    )


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
    description = "Should not charge the battery at a daily price high outside an emergency, beyond what unsellable surplus justifies"
    if scenario.objective in (Objective.MIN_CARBON, Objective.MAX_RENEWABLE_UTILISATION):
        return RuleResult(rule_id="rule_5", description=description, severity="flagged", passed=True, applicable=False, detail=f"N/A — this objective ({scenario.objective.value}) doesn't trade cost against a price-peak charging decision.")

    threshold = _daily_high_threshold(scenario)
    at_peak = scenario.electricity_price_per_mwh >= threshold
    emergency = physics.is_emergency(scenario, decision.applied_floor_pct)

    generation = physics.total_generation_mw(scenario)
    surplus_mw = max(0.0, generation - scenario.total_demand_mw)
    sellable_surplus_mw = min(surplus_mw, scenario.transmission_headroom_mw)
    unsellable_surplus_mw = max(0.0, surplus_mw - sellable_surplus_mw)
    charge = sum(a.amount_mw for a in decision.battery_actions if a.action == "charge")
    avoidable_charge_mw = max(0.0, charge - unsellable_surplus_mw)

    violation = avoidable_charge_mw > BALANCE_TOLERANCE_MW and at_peak and not emergency
    passed = not violation
    if emergency and avoidable_charge_mw > BALANCE_TOLERANCE_MW and at_peak:
        detail = f"Charging {avoidable_charge_mw:.1f}MW (avoidable) at a price peak, but legitimate given the emergency."
    elif not passed:
        detail = (
            f"Charging {avoidable_charge_mw:.1f}MW beyond the {unsellable_surplus_mw:.1f}MW of unsellable surplus "
            f"(sellable surplus {sellable_surplus_mw:.1f}MW) while price ${scenario.electricity_price_per_mwh:.0f}/MWh is at/near the daily high (${threshold:.0f})."
        )
    elif charge > BALANCE_TOLERANCE_MW and at_peak:
        detail = f"Charging {charge:.1f}MW at a price peak, but all of it absorbs the {unsellable_surplus_mw:.1f}MW of surplus that couldn't be sold (the alternative was curtailment) — not avoidable."
    else:
        detail = "No avoidable charging during a price peak."
    return RuleResult(
        rule_id="rule_5", description=description, severity="flagged", passed=passed, detail=detail,
        value_label="avoidable charge vs. tolerance (MW)", value_actual=round(avoidable_charge_mw, 1), value_reference=BALANCE_TOLERANCE_MW,
    )


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
    return RuleResult(
        rule_id="rule_6", description="Curtailment must not exceed the minimum physically required (amount-based)", severity="fail", passed=passed, detail=detail,
        value_label="curtailed vs. minimum required", value_actual=round(actual, 1), value_reference=round(min_required, 1),
    )


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


def _rule9_na(best: float, worst: float, tolerance: float) -> bool:
    """No real decision freedom: best and worst feasible outcomes coincide, or both the
    reference and the gap are already ~0 (Brief 2 Patch 2, Step 2)."""
    return abs(best - worst) < tolerance


def rule_9_cascade_deviation(scenario: EnvironmentState, decision: Decision) -> RuleResult:
    top_priority = _CASCADE_PRIORITY[scenario.objective]
    ref = reference_dispatch(scenario)

    if top_priority == "cost":
        actual_cost = (decision.market_amount_mw if decision.market_action == "buy" else 0.0) * scenario.buy_price_per_mwh
        best, worst = ref["reference_cost"], ref["worst_cost"]
        tolerance = max(abs(best), 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        if _rule9_na(best, worst, tolerance):
            return RuleResult(rule_id="rule_9", description="Decision matches the declared cascade (top priority: cost)", severity="flagged", passed=True, applicable=False, detail=f"N/A — no decision could change net import cost here (best and worst feasible outcomes both ~${best:.0f}).")
        passed = actual_cost <= best + tolerance
        detail = f"Net import cost ${actual_cost:.0f} vs reference ${best:.0f}" + ("." if passed else f" (exceeds {OBJECTIVE_TOLERANCE_PCT:.0f}% tolerance).")
        label, actual_val, ref_val = "net cost vs. reference ($)", actual_cost, best
    elif top_priority == "carbon":
        actual_import = decision.market_amount_mw if decision.market_action == "buy" else 0.0
        best, worst = ref["min_grid_import_mw"], ref["worst_grid_import_mw"]
        tolerance = max(abs(best), 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        if _rule9_na(best, worst, tolerance):
            return RuleResult(rule_id="rule_9", description="Decision matches the declared cascade (top priority: carbon)", severity="flagged", passed=True, applicable=False, detail=f"N/A — no decision could change grid import here (best and worst feasible outcomes both ~{best:.1f}MW).")
        passed = actual_import <= best + tolerance
        detail = f"Grid import {actual_import:.1f}MW (carbon proxy) vs reference minimum {best:.1f}MW" + ("." if passed else f" (exceeds {OBJECTIVE_TOLERANCE_PCT:.0f}% tolerance).")
        label, actual_val, ref_val = "grid import vs. reference minimum (MW)", actual_import, best
    elif top_priority == "renewable_utilisation":
        actual_curtail = decision.curtail_solar_mw + decision.curtail_wind_mw
        best = physics.min_required_curtailment_mw(scenario)
        worst = ref["renewable_surplus_mw"]
        tolerance = max(abs(best), 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        if _rule9_na(best, worst, tolerance):
            return RuleResult(rule_id="rule_9", description="Decision matches the declared cascade (top priority: renewable_utilisation)", severity="flagged", passed=True, applicable=False, detail=f"N/A — no decision could change curtailment here (best and worst feasible outcomes both ~{best:.1f}MW).")
        passed = actual_curtail <= best + CURTAIL_TOLERANCE_MW
        detail = f"Curtailed {actual_curtail:.1f}MW vs {best:.1f}MW minimum required" + ("." if passed else f" (exceeds {CURTAIL_TOLERANCE_MW}MW tolerance).")
        label, actual_val, ref_val = "curtailed vs. minimum required (MW)", actual_curtail, best
    else:  # profit
        profit = physics.decision_profit(scenario, decision)
        actual_profit = profit["net_profit"]
        best, worst = ref["reference_profit"], ref["worst_profit"]
        tolerance = max(abs(best), 1.0) * (OBJECTIVE_TOLERANCE_PCT / 100)
        if _rule9_na(best, worst, tolerance) or (abs(best) < tolerance and abs(actual_profit) < tolerance):
            return RuleResult(rule_id="rule_9", description="Decision matches the declared cascade (top priority: profit)", severity="flagged", passed=True, applicable=False, detail=f"N/A — no decision could change net profit here (best and worst feasible outcomes both ~${best:.0f}).")
        passed = actual_profit >= best - tolerance
        detail = (
            f"Revenue ${profit['revenue']:.0f} (sell {profit['sale_mw']:.1f}MW @ ${scenario.sell_price_per_mwh:.0f}/MWh) "
            f"- cost ${profit['cost']:.0f} (buy {profit['purchase_mw']:.1f}MW @ ${scenario.buy_price_per_mwh:.0f}/MWh) "
            f"= net profit ${actual_profit:.0f} vs reference ${best:.0f}"
        ) + ("." if passed else f" (below {OBJECTIVE_TOLERANCE_PCT:.0f}% tolerance).")
        label, actual_val, ref_val = "net profit vs. reference ($)", actual_profit, best

    return RuleResult(
        rule_id="rule_9", description=f"Decision matches the declared cascade (top priority: {top_priority})", severity="flagged", passed=passed, detail=detail,
        value_label=label, value_actual=round(actual_val, 1), value_reference=round(ref_val, 1),
    )


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


def run_rules(scenario: EnvironmentState, decision: Decision, repairs: list[FieldRepair] | None = None, include_repair_rule: bool = True) -> list[RuleResult]:
    """include_repair_rule=False for the 'raw' stage (pre-balancer) — rule_10 measures
    balancer repair, which doesn't apply to a decision that hasn't been through it yet."""
    repairs = repairs or []
    rules = [
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
    ]
    if include_repair_rule:
        rules.append(rule_10_repair_magnitude(repairs))
    return rules
