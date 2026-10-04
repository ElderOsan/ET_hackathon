"""The deterministic balancer (Brief 2, Step 4) and the reference dispatcher it shares its
physics with (used by rule 9). Both are built only on app/data/physics.py — no other module
computes power-balance quantities.

Balancer design note: the balancer REPAIRS infeasible numbers (caps a proposal to what's
physically possible); it never INVENTS supply the model didn't propose. If the model's
proposal under-provisions demand, that shortfall is left standing — it's a model mistake
for the Evaluator to catch (rule 3), not something the balancer should paper over.
"""
from __future__ import annotations

from app.data import physics
from app.data.tuning import BALANCE_TOLERANCE_MW
from app.models.schemas import BatteryAction, Decision, EnvironmentState, FieldRepair


def _split_curtailment(total: float, solar_output: float, wind_output: float, prior_solar: float, prior_wind: float) -> tuple[float, float]:
    prior_total = prior_solar + prior_wind
    if prior_total > 0:
        solar_share = prior_solar / prior_total
    else:
        gen_total = solar_output + wind_output
        solar_share = solar_output / gen_total if gen_total > 0 else 0.5
    solar = min(solar_output, round(total * solar_share, 1))
    wind = min(wind_output, round(total - solar, 1))
    return solar, wind


def balance(scenario: EnvironmentState, proposal: Decision) -> tuple[Decision, list[FieldRepair]]:
    repairs: list[FieldRepair] = []
    emergency = physics.is_emergency(scenario, proposal.applied_floor_pct)
    batteries_by_id = {b.id: b for b in scenario.batteries}

    # --- Step 1: cap every battery action to feasibility -----------------------------------
    applied_battery_actions: list[BatteryAction] = []
    # Addendum C, point 6: charging may not exceed the renewable surplus -- this is a repair
    # (the model's own mistake is caught separately by rule_11 on the raw proposal), so the
    # cap is spent across battery actions in proposal order as a shared budget.
    remaining_surplus_budget = physics.renewable_surplus_mw(scenario)
    for action in proposal.battery_actions:
        battery = batteries_by_id.get(action.battery_id)
        if battery is None:
            applied_battery_actions.append(action)
            continue
        if not battery.available:
            if action.action != "hold" and action.amount_mw != 0:
                repairs.append(FieldRepair(field=f"battery_actions[{battery.id}]", proposed=action.amount_mw, applied=0.0, delta_mw=-action.amount_mw, reason=f"{battery.id} is offline"))
            applied_battery_actions.append(BatteryAction(battery_id=battery.id, action="hold", amount_mw=0.0))
        elif action.action == "charge":
            cap = min(physics.max_charge_mw(battery), max(remaining_surplus_budget, 0.0))
            amt = round(min(max(action.amount_mw, 0.0), cap), 1)
            if amt != action.amount_mw:
                reason = (
                    f"capped to the {remaining_surplus_budget:.1f}MW renewable surplus (no buying to charge)"
                    if remaining_surplus_budget < physics.max_charge_mw(battery)
                    else f"capped to max charge headroom ({cap:.1f}MW)"
                )
                repairs.append(FieldRepair(field=f"battery_actions[{battery.id}].amount_mw", proposed=action.amount_mw, applied=amt, delta_mw=amt - action.amount_mw, reason=reason))
            remaining_surplus_budget -= amt
            applied_battery_actions.append(BatteryAction(battery_id=battery.id, action="charge" if amt > 0 else "hold", amount_mw=amt))
        elif action.action == "discharge":
            cap = physics.max_discharge_mw(battery, proposal.applied_floor_pct, emergency)
            amt = round(min(max(action.amount_mw, 0.0), cap), 1)
            if amt != action.amount_mw:
                reason = f"capped to max discharge headroom ({cap:.1f}MW" + (", emergency floor)" if emergency else f", applied floor {proposal.applied_floor_pct}%)")
                repairs.append(FieldRepair(field=f"battery_actions[{battery.id}].amount_mw", proposed=action.amount_mw, applied=amt, delta_mw=amt - action.amount_mw, reason=reason))
            applied_battery_actions.append(BatteryAction(battery_id=battery.id, action="discharge" if amt > 0 else "hold", amount_mw=amt))
        else:
            applied_battery_actions.append(BatteryAction(battery_id=battery.id, action="hold", amount_mw=0.0))

    total_charge = sum(a.amount_mw for a in applied_battery_actions if a.action == "charge")
    total_discharge = sum(a.amount_mw for a in applied_battery_actions if a.action == "discharge")
    generation = scenario.solar_output_mw + scenario.wind_output_mw

    # --- Cap curtailment to availability, purchase/sale to transmission headroom -----------
    curtail_solar = round(min(max(proposal.curtail_solar_mw, 0.0), scenario.solar_output_mw), 1)
    curtail_wind = round(min(max(proposal.curtail_wind_mw, 0.0), scenario.wind_output_mw), 1)
    if curtail_solar != proposal.curtail_solar_mw:
        repairs.append(FieldRepair(field="curtail_solar_mw", proposed=proposal.curtail_solar_mw, applied=curtail_solar, delta_mw=curtail_solar - proposal.curtail_solar_mw, reason="capped to available solar output"))
    if curtail_wind != proposal.curtail_wind_mw:
        repairs.append(FieldRepair(field="curtail_wind_mw", proposed=proposal.curtail_wind_mw, applied=curtail_wind, delta_mw=curtail_wind - proposal.curtail_wind_mw, reason="capped to available wind output"))

    purchase = proposal.market_amount_mw if proposal.market_action == "buy" else 0.0
    sale = proposal.market_amount_mw if proposal.market_action == "sell" else 0.0
    capped_purchase = round(min(purchase, scenario.transmission_headroom_mw), 1)
    capped_sale = round(min(sale, scenario.transmission_headroom_mw), 1)
    if capped_purchase != purchase:
        repairs.append(FieldRepair(field="market_amount_mw(buy)", proposed=purchase, applied=capped_purchase, delta_mw=capped_purchase - purchase, reason=f"capped to transmission headroom ({scenario.transmission_headroom_mw:.1f}MW)"))
    if capped_sale != sale:
        repairs.append(FieldRepair(field="market_amount_mw(sell)", proposed=sale, applied=capped_sale, delta_mw=capped_sale - sale, reason=f"capped to transmission headroom ({scenario.transmission_headroom_mw:.1f}MW)"))
    purchase, sale = capped_purchase, capped_sale

    def served_mw(cs: float, cw: float, p: float, s: float) -> float:
        return generation - (cs + cw) + total_discharge + p - total_charge - s

    served = served_mw(curtail_solar, curtail_wind, purchase, sale)
    total_demand = scenario.total_demand_mw

    # --- Phase A: load must be met before any sale or curtailment is allowed. If still short
    # after both, unwind battery charging too (largest proposed charge first) — charging while
    # load is unmet is never correct, same as selling or curtailing while unmet (Brief 2 Patch,
    # Step 5, finding #4). Unwind order: curtailment, then sale, then charging. -------------
    if served < total_demand - BALANCE_TOLERANCE_MW and sale > 0:
        repairs.append(FieldRepair(field="market_amount_mw(sell)", proposed=sale, applied=0.0, delta_mw=-sale, reason="load unserved — cannot sell while demand is unmet"))
        sale = 0.0
        served = served_mw(curtail_solar, curtail_wind, purchase, sale)
    if served < total_demand - BALANCE_TOLERANCE_MW and (curtail_solar > 0 or curtail_wind > 0):
        repairs.append(FieldRepair(field="curtailment", proposed=curtail_solar + curtail_wind, applied=0.0, delta_mw=-(curtail_solar + curtail_wind), reason="load unserved — cannot curtail while demand is unmet"))
        curtail_solar = curtail_wind = 0.0
        served = served_mw(curtail_solar, curtail_wind, purchase, sale)
    if served < total_demand - BALANCE_TOLERANCE_MW:
        charge_indices = sorted(
            (i for i, a in enumerate(applied_battery_actions) if a.action == "charge"),
            key=lambda i: -applied_battery_actions[i].amount_mw,
        )
        for i in charge_indices:
            if served >= total_demand - BALANCE_TOLERANCE_MW:
                break
            action = applied_battery_actions[i]
            shortfall = total_demand - served
            reduction = round(min(action.amount_mw, shortfall), 1)
            if reduction <= 0:
                continue
            new_amount = round(action.amount_mw - reduction, 1)
            repairs.append(FieldRepair(
                field=f"battery_actions[{action.battery_id}].amount_mw", proposed=action.amount_mw, applied=new_amount,
                delta_mw=new_amount - action.amount_mw,
                reason="load unserved — unwound charging to free generation for load (curtailment and sale already removed)",
            ))
            applied_battery_actions[i] = BatteryAction(battery_id=action.battery_id, action="charge" if new_amount > 0 else "hold", amount_mw=new_amount)
            total_charge = sum(a.amount_mw for a in applied_battery_actions if a.action == "charge")
            served = served_mw(curtail_solar, curtail_wind, purchase, sale)
    # If still short here, it's a genuine shortfall — left standing, not invented away.

    # --- Phase A.5: drop a purchase that surplus makes unnecessary -------------------------
    if purchase > 0 and served - purchase >= total_demand - BALANCE_TOLERANCE_MW:
        repairs.append(FieldRepair(field="market_amount_mw(buy)", proposed=purchase, applied=0.0, delta_mw=-purchase, reason="surplus exists without it — purchase was not needed"))
        served -= purchase
        purchase = 0.0

    # --- Phase B: absorb genuine surplus — more sale first, then forced curtailment --------
    leftover = served - total_demand
    if leftover > BALANCE_TOLERANCE_MW:
        more_sale_room = max(0.0, scenario.transmission_headroom_mw - sale)
        extra_sale = round(min(leftover, more_sale_room), 1)
        if extra_sale > 0:
            # Brief 2 Patch 2, Step 4: every change is recorded, however small. The old
            # ">0.05" gate here was dead in practice (every value in this function is
            # rounded to 1 decimal, so a nonzero delta is always >=0.1) but it was still an
            # arbitrary threshold with no CONFIG home, disconnected from BALANCE_TOLERANCE_MW
            # and REPAIR_TOLERANCE_MW — removed rather than left as a trap for a future edit.
            repairs.append(FieldRepair(field="market_amount_mw(sell)", proposed=sale, applied=sale + extra_sale, delta_mw=extra_sale, reason=f"increased to absorb surplus within transmission headroom ({scenario.transmission_headroom_mw:.1f}MW)"))
        sale += extra_sale
        remaining = round(leftover - extra_sale, 1)
        if remaining > BALANCE_TOLERANCE_MW:
            new_cs, new_cw = _split_curtailment(curtail_solar + curtail_wind + remaining, scenario.solar_output_mw, scenario.wind_output_mw, curtail_solar, curtail_wind)
            if new_cs != curtail_solar or new_cw != curtail_wind:
                repairs.append(FieldRepair(field="curtailment", proposed=curtail_solar + curtail_wind, applied=new_cs + new_cw, delta_mw=(new_cs + new_cw) - (curtail_solar + curtail_wind), reason="forced: surplus remained after load, max charge, and sale up to transmission headroom"))
            curtail_solar, curtail_wind = new_cs, new_cw
        served = served_mw(curtail_solar, curtail_wind, purchase, sale)

    # --- Final residual nudge (rounding only) onto whichever market side is active ---------
    residual = total_demand - served if served < total_demand else served - total_demand
    if abs(residual) > BALANCE_TOLERANCE_MW:
        if served < total_demand:
            pass  # genuine shortfall, not a rounding artifact — leave as-is
        elif sale > 0:
            old_sale = sale
            sale = round(max(0.0, sale - residual), 1)
            repairs.append(FieldRepair(field="market_amount_mw(sell)", proposed=old_sale, applied=sale, delta_mw=sale - old_sale, reason="rounding nudge to close the power balance within tolerance"))

    market_action = "sell" if sale > 0 else ("buy" if purchase > 0 else "hold")
    market_amount = sale if sale > 0 else purchase

    applied = Decision(
        tick=proposal.tick,
        objective_used=proposal.objective_used,
        battery_actions=applied_battery_actions,
        market_action=market_action,
        market_amount_mw=round(market_amount, 1),
        curtail_solar_mw=round(curtail_solar, 1),
        curtail_wind_mw=round(curtail_wind, 1),
        demand_response_triggered=proposal.demand_response_triggered,
        proposed_floor_pct=proposal.proposed_floor_pct,
        applied_floor_pct=proposal.applied_floor_pct,
        floor_justification=proposal.floor_justification,
        reasoning=proposal.reasoning,
        mode=proposal.mode,  # the balancer repairs the decision, not where it came from -- carry mode/failure_detail through, don't silently default back to "agent"
        failure_detail=proposal.failure_detail,
    )
    return applied, repairs


def _worst_feasible_decision(scenario: EnvironmentState) -> Decision:
    """The worst still-feasible dispatch: serves load if possible using ONLY grid import
    (zero battery help), sells and charges nothing. Used as the common "worst" baseline for
    every objective's reference (Addendum C) — one decision, run through the same physics
    functions as the "best" one, instead of a hand-rolled number per metric."""
    generation = physics.total_generation_mw(scenario)
    shortfall = max(0.0, scenario.total_demand_mw - generation)
    hold_actions = [BatteryAction(battery_id=b.id, action="hold", amount_mw=0.0) for b in scenario.batteries]
    if shortfall > 0:
        import_mw = round(min(shortfall, physics.max_import_mw(scenario)), 1)
        return Decision(
            tick=scenario.tick, objective_used=scenario.objective.value if scenario.objective else "cost_efficiency",
            battery_actions=hold_actions, market_action="buy" if import_mw > 0 else "hold", market_amount_mw=import_mw,
            curtail_solar_mw=0.0, curtail_wind_mw=0.0, demand_response_triggered=False,
            proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
            floor_justification="worst-feasible reference", reasoning="worst-feasible reference", mode="agent",
        )
    surplus = physics.renewable_surplus_mw(scenario)
    curtail_solar, curtail_wind = _split_curtailment(surplus, scenario.solar_output_mw, scenario.wind_output_mw, 0.0, 0.0)
    return Decision(
        tick=scenario.tick, objective_used=scenario.objective.value if scenario.objective else "cost_efficiency",
        battery_actions=hold_actions, market_action="hold", market_amount_mw=0.0,
        curtail_solar_mw=curtail_solar, curtail_wind_mw=curtail_wind, demand_response_triggered=False,
        proposed_floor_pct=scenario.previous_floor_pct, applied_floor_pct=scenario.previous_floor_pct,
        floor_justification="worst-feasible reference", reasoning="worst-feasible reference", mode="agent",
    )


def reference_dispatch(scenario: EnvironmentState, floor_pct: float) -> dict:
    """The autonomous optimal dispatch (no proposal): cheapest/cleanest way to meet demand
    using renewables, then battery down to floor_pct, then grid import for whatever's left —
    and the maximum sellable surplus, for the profit side. This is what rule 9 compares the
    actual decision against.

    floor_pct is the DECISION's own applied_floor_pct (Patch 3 addendum) — not
    expected_floor_min_pct. Scoring the model against more battery headroom than its own
    floor choice allowed itself isn't a fair comparison; a higher floor may be the right,
    deliberate call (e.g. a cascade's own volatility), and the reference must respect it the
    same way the balancer does. An informational (not scored) alternate — what the reference
    cost would have been at expected_floor_min_pct instead — is also returned, so the size of
    that gap stays visible without it silently driving rule_9's verdict.

    Addendum C: best/worst for EVERY metric (cost, emissions, renewable utilisation, profit)
    are now derived from two actual Decision objects (best = dispatch_at_floor's own choice,
    worst = _worst_feasible_decision) run through the exact same physics functions the
    scored decision is judged with — profit, emissions and utilisation can no longer drift
    out of sync with each other or with the scored side's formula.

    Also returns the WORST still-feasible outcome per metric (Brief 2 Patch 2, Step 2):
    rule_9 reports N/A when best and worst coincide (within tolerance): no decision could
    have moved this metric, so there's nothing to judge the model's choice against.
    """
    from app.data.dispatcher import dispatch_at_floor

    def _min_import_at(floor: float) -> float:
        alt = dispatch_at_floor(scenario, scenario.objective, floor)
        return alt.market_amount_mw if alt.market_action == "buy" else 0.0

    best = dispatch_at_floor(scenario, scenario.objective, floor_pct)
    worst = _worst_feasible_decision(scenario)

    min_grid_import_mw = round(best.market_amount_mw, 1) if best.market_action == "buy" else 0.0
    max_sellable_mw = round(best.market_amount_mw, 1) if best.market_action == "sell" else 0.0
    worst_grid_import_mw = round(worst.market_amount_mw, 1) if worst.market_action == "buy" else 0.0
    worst_sellable_mw = 0.0

    reference_cost_at_expected_floor_pct = round(_min_import_at(scenario.expected_floor_min_pct) * scenario.buy_price_per_mwh, 1)

    best_profit = physics.decision_profit(scenario, best)
    worst_profit = physics.decision_profit(scenario, worst)

    best_emissions = physics.emissions_tonnes(scenario, best)
    worst_emissions = physics.emissions_tonnes(scenario, worst)

    best_curtail_mw = round(best.curtail_solar_mw + best.curtail_wind_mw, 1)
    worst_curtail_mw = round(worst.curtail_solar_mw + worst.curtail_wind_mw, 1)
    best_utilisation_pct = physics.renewable_utilisation_pct(scenario, best)
    worst_utilisation_pct = physics.renewable_utilisation_pct(scenario, worst)

    return {
        "min_grid_import_mw": min_grid_import_mw,
        "worst_grid_import_mw": worst_grid_import_mw,
        "renewable_surplus_mw": round(physics.renewable_surplus_mw(scenario), 1),
        "max_sellable_mw": max_sellable_mw,
        "worst_sellable_mw": worst_sellable_mw,
        "reference_cost": best_profit["cost"],
        "worst_cost": worst_profit["cost"],
        "reference_revenue": best_profit["revenue"],
        "worst_revenue": worst_profit["revenue"],
        "reference_profit": best_profit["net_profit"],
        "worst_profit": worst_profit["net_profit"],
        "best_emissions_tonnes": best_emissions,
        "worst_emissions_tonnes": worst_emissions,
        "best_curtail_mw": best_curtail_mw,
        "worst_curtail_mw": worst_curtail_mw,
        "best_utilisation_pct": best_utilisation_pct,
        "worst_utilisation_pct": worst_utilisation_pct,
        "floor_used_for_reference_pct": floor_pct,
        "reference_cost_at_expected_floor_pct": reference_cost_at_expected_floor_pct,  # informational only, not scored
    }
