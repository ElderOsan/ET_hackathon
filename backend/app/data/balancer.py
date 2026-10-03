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
            cap = physics.max_charge_mw(battery)
            amt = round(min(max(action.amount_mw, 0.0), cap), 1)
            if amt != action.amount_mw:
                repairs.append(FieldRepair(field=f"battery_actions[{battery.id}].amount_mw", proposed=action.amount_mw, applied=amt, delta_mw=amt - action.amount_mw, reason=f"capped to max charge headroom ({cap:.1f}MW)"))
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

    # --- Phase A: load must be met before any sale or curtailment is allowed ---------------
    if served < total_demand - BALANCE_TOLERANCE_MW and sale > 0:
        repairs.append(FieldRepair(field="market_amount_mw(sell)", proposed=sale, applied=0.0, delta_mw=-sale, reason="load unserved — cannot sell while demand is unmet"))
        sale = 0.0
        served = served_mw(curtail_solar, curtail_wind, purchase, sale)
    if served < total_demand - BALANCE_TOLERANCE_MW and (curtail_solar > 0 or curtail_wind > 0):
        repairs.append(FieldRepair(field="curtailment", proposed=curtail_solar + curtail_wind, applied=0.0, delta_mw=-(curtail_solar + curtail_wind), reason="load unserved — cannot curtail while demand is unmet"))
        curtail_solar = curtail_wind = 0.0
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
        if extra_sale > 0.05:
            repairs.append(FieldRepair(field="market_amount_mw(sell)", proposed=sale, applied=sale + extra_sale, delta_mw=extra_sale, reason=f"increased to absorb surplus within transmission headroom ({scenario.transmission_headroom_mw:.1f}MW)"))
        sale += extra_sale
        remaining = round(leftover - extra_sale, 1)
        if remaining > BALANCE_TOLERANCE_MW:
            new_cs, new_cw = _split_curtailment(curtail_solar + curtail_wind + remaining, scenario.solar_output_mw, scenario.wind_output_mw, curtail_solar, curtail_wind)
            if abs(new_cs - curtail_solar) > 0.05 or abs(new_cw - curtail_wind) > 0.05:
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
    )
    return applied, repairs


def reference_dispatch(scenario: EnvironmentState) -> dict:
    """The autonomous optimal dispatch (no proposal): cheapest/cleanest way to meet demand
    using renewables, then battery down to the scenario's expected floor band, then grid
    import for whatever's left — and the maximum sellable surplus, for the profit side.
    This is what rule 9 compares the actual decision against.
    """
    floor_assumption = scenario.expected_floor_min_pct
    generation = scenario.solar_output_mw + scenario.wind_output_mw
    total_demand = scenario.total_demand_mw

    battery_headroom = sum(physics.max_discharge_mw(b, floor_assumption, emergency=False) for b in scenario.batteries)
    remaining = max(0.0, total_demand - generation)
    battery_used = min(remaining, battery_headroom)
    remaining = max(0.0, remaining - battery_used)
    min_grid_import_mw = round(remaining, 1)

    renewable_surplus_mw = max(0.0, generation - total_demand)
    max_sellable_mw = round(min(renewable_surplus_mw, scenario.transmission_headroom_mw), 1)

    reference_cost = round(min_grid_import_mw * scenario.electricity_price_per_mwh, 1)
    reference_revenue = round(max_sellable_mw * scenario.electricity_price_per_mwh, 1)

    return {
        "min_grid_import_mw": min_grid_import_mw,
        "renewable_surplus_mw": round(renewable_surplus_mw, 1),
        "max_sellable_mw": max_sellable_mw,
        "reference_cost": reference_cost,
        "reference_revenue": reference_revenue,
    }
