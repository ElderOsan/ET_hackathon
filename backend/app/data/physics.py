"""The single physics module. Used by the balancer, the Evaluator, and the reference
calculator — nothing else computes these quantities (Brief 2, Step 2).

Transmission definition (the one used everywhere in this codebase): the limit applies to
NET FLOW across the grid interconnection — sale minus purchase, in either direction.
`transmission_constraint_mw` is the fixed line rating; `transmission_headroom_mw` is the
remaining net-flow capacity available this tick (normally equal to the rating, driven near
zero by the transmission_at_capacity event). A decision's net flow is
`market_amount_mw` (positive for sell, negative for buy), and must satisfy
`abs(net_flow) <= transmission_headroom_mw`.

Battery MW throughout are bus-side (what flows to/from the grid bus); charging/discharge
efficiency affects only the battery's own state-of-charge update, never the bus-side MW
used in the power balance.
"""
from __future__ import annotations

from app.data.tuning import BALANCE_TOLERANCE_MW, FLOOR_MAX, FLOOR_MIN, FLOOR_STEP_DOWN, PRICE_SPREAD_PCT, TICK_HOURS
from app.models.schemas import Battery, Decision, EnvironmentState


def apply_floor_clamp_and_ramp(proposed_floor_pct: float, previous_floor_pct: float) -> float:
    """Hard bounds, then the ramp-down limit (the floor may rise by any amount in one tick,
    but fall by at most FLOOR_STEP_DOWN). Shared by the Orchestrator's post-proposal clamp
    (orchestrator_agent.py) and the dispatcher's from-scratch floor choice (dispatcher.py,
    Patch 3 Step 3) — one definition, not two."""
    clamped = min(max(proposed_floor_pct, FLOOR_MIN), FLOOR_MAX)
    floor_after_ramp = max(clamped, previous_floor_pct - FLOOR_STEP_DOWN)
    return min(max(floor_after_ramp, FLOOR_MIN), FLOOR_MAX)


def buy_price_per_mwh(electricity_price_per_mwh: float) -> float:
    """What a purchase costs — above the quoted price by the spread (Brief 2 Patch 2, Step
    2). A spread of 0 reproduces the old single-price behaviour exactly."""
    return round(electricity_price_per_mwh * (1 + PRICE_SPREAD_PCT / 100), 2)


def sell_price_per_mwh(electricity_price_per_mwh: float) -> float:
    """What a sale earns — below the quoted price by the spread. A spread of 0 reproduces
    the old single-price behaviour exactly."""
    return round(electricity_price_per_mwh * (1 - PRICE_SPREAD_PCT / 100), 2)


def net_stored_energy_change_mwh(scenario: EnvironmentState, decision: Decision) -> float:
    """Addendum C, point 2: the net MWh added to (positive) or removed from (negative)
    battery storage this tick, across every battery action. Charging efficiency applies to
    what's ADDED (max_charge_mw's own inverse formula: bus-side MW x TICK_HOURS x efficiency
    is the energy that actually lands in the battery); discharge removes bus-side MW x
    TICK_HOURS directly, with no efficiency factor, matching resulting_soc_pct."""
    batteries_by_id = {b.id: b for b in scenario.batteries}
    net_mwh = 0.0
    for action in decision.battery_actions:
        battery = batteries_by_id.get(action.battery_id)
        if battery is None or action.amount_mw <= 0:
            continue
        if action.action == "charge":
            efficiency = max(battery.charging_efficiency_pct / 100.0, 0.01)
            net_mwh += action.amount_mw * TICK_HOURS * efficiency
        elif action.action == "discharge":
            net_mwh -= action.amount_mw * TICK_HOURS
    return net_mwh


def decision_profit(scenario: EnvironmentState, decision: Decision) -> dict:
    """Addendum C, point 2: sale revenue minus purchase cost, PLUS the value of the net
    change in stored energy (valued at sell_price_per_mwh — what that energy could earn if
    sold) — replaces the single-tick, revenue-only metric that credited $0 for charging and
    so could not distinguish "stored for later" from "wasted." The single source of truth
    for this arithmetic; rule_9's profit branch, reference_dispatch, and the Decision panel
    all use it."""
    sale_mw = decision.market_amount_mw if decision.market_action == "sell" else 0.0
    purchase_mw = decision.market_amount_mw if decision.market_action == "buy" else 0.0
    revenue = round(sale_mw * scenario.sell_price_per_mwh, 1)
    cost = round(purchase_mw * scenario.buy_price_per_mwh, 1)
    stored_mwh = net_stored_energy_change_mwh(scenario, decision)
    stored_value = round(stored_mwh * scenario.sell_price_per_mwh, 1)
    return {
        "sale_mw": sale_mw, "purchase_mw": purchase_mw, "revenue": revenue, "cost": cost,
        "stored_energy_mwh": round(stored_mwh, 2), "stored_energy_value": stored_value,
        "net_profit": round(revenue - cost + stored_value, 1),
    }


def renewable_surplus_mw(scenario: EnvironmentState) -> float:
    """generation - total_demand, floored at 0 — the pool battery charging may never exceed
    (Addendum C, point 6: no buying to charge)."""
    return max(0.0, total_generation_mw(scenario) - scenario.total_demand_mw)


def emissions_tonnes(scenario: EnvironmentState, decision: Decision) -> float:
    """Addendum C, point 3: grid import (MWh, not MW) x grid_carbon_intensity_t_per_mwh.
    Replaces the old raw-import-MW proxy as min_carbon's actual metric."""
    purchase_mw = decision.market_amount_mw if decision.market_action == "buy" else 0.0
    import_mwh = purchase_mw * TICK_HOURS
    return round(import_mwh * scenario.grid_carbon_intensity_t_per_mwh, 3)


def renewable_utilisation_pct(scenario: EnvironmentState, decision: Decision) -> float:
    """Addendum C, point 4: (generation - curtailment) / generation x 100. Stored and sold
    energy both count as utilised — only curtailment counts against it."""
    generation = total_generation_mw(scenario)
    if generation <= 0:
        return 100.0
    curtailment = decision.curtail_solar_mw + decision.curtail_wind_mw
    return round(max(0.0, generation - curtailment) / generation * 100, 1)


def renewable_share_of_delivered_pct(scenario: EnvironmentState, decision: Decision) -> float:
    """Addendum C, point 4 (informational): how much of total demand was met by non-curtailed
    renewable generation this tick, capped at 100%."""
    if scenario.total_demand_mw <= 0:
        return 0.0
    generation = total_generation_mw(scenario)
    curtailment = decision.curtail_solar_mw + decision.curtail_wind_mw
    delivered = max(0.0, generation - curtailment)
    return round(min(100.0, delivered / scenario.total_demand_mw * 100), 1)


def build_tick_ledger(scenario: EnvironmentState, decision: Decision) -> dict:
    """Addendum C, point 8: the per-tick ledger, computed here (and only here) from the same
    functions every rule and reference already uses — never recomputed ad hoc elsewhere."""
    profit = decision_profit(scenario, decision)
    emissions = emissions_tonnes(scenario, decision)
    return {
        "purchase_cost": profit["cost"],
        "sales_revenue": profit["revenue"],
        "stored_energy_value_change": profit["stored_energy_value"],
        "profit": profit["net_profit"],
        "emissions_tonnes": emissions,
        "carbon_cost": round(emissions * scenario.carbon_price_per_ton, 1),
        "renewable_utilisation_pct": renewable_utilisation_pct(scenario, decision),
        "renewable_share_of_delivered_pct": renewable_share_of_delivered_pct(scenario, decision),
    }


def max_charge_mw(battery: Battery) -> float:
    if not battery.available:
        return 0.0
    efficiency = max(battery.charging_efficiency_pct / 100.0, 0.01)
    soc_headroom_mwh = (100.0 - battery.state_of_charge_pct) / 100.0 * battery.capacity_mwh
    return max(0.0, min(battery.max_charge_rate_mw, soc_headroom_mwh / (TICK_HOURS * efficiency)))


def resulting_soc_pct(battery: Battery, discharge_mw: float) -> float:
    """The battery's state of charge after discharging discharge_mw for one tick. MW -> MWh
    needs TICK_HOURS; skipping it (treating MW as if it ran for a full hour) is a 4x error
    at a 15-minute tick — every SoC-after-discharge check must go through this function."""
    discharged_pct = (discharge_mw * TICK_HOURS / battery.capacity_mwh) * 100 if battery.capacity_mwh else 0.0
    return battery.state_of_charge_pct - discharged_pct


def max_discharge_mw(battery: Battery, floor_pct: float, emergency: bool) -> float:
    if not battery.available:
        return 0.0
    effective_floor = battery.min_safe_soc_pct if emergency else floor_pct
    usable_mwh = max(0.0, (battery.state_of_charge_pct - effective_floor) / 100.0) * battery.capacity_mwh
    return max(0.0, min(battery.max_discharge_rate_mw, usable_mwh / TICK_HOURS))


def is_emergency(scenario: EnvironmentState, floor_pct: float) -> bool:
    """True only if total_demand_mw cannot be served after every shortfall-ladder step except
    the reserve floor (renewables, battery above floor, grid import up to transmission
    headroom) has been used. Computed from state, never taken on the model's word."""
    generation = scenario.solar_output_mw + scenario.wind_output_mw
    battery_headroom = sum(
        max_discharge_mw(b, floor_pct, emergency=False) for b in scenario.batteries
    )
    best_case_supply = generation + battery_headroom + scenario.transmission_headroom_mw
    return best_case_supply < scenario.total_demand_mw


def min_required_curtailment_mw(scenario: EnvironmentState) -> float:
    """The least curtailment that is physically necessary: surplus remaining after load,
    maximum battery charge, and sale up to transmission headroom are all used."""
    generation = scenario.solar_output_mw + scenario.wind_output_mw
    total_max_charge = sum(max_charge_mw(b) for b in scenario.batteries)
    return max(0.0, generation - scenario.total_demand_mw - total_max_charge - scenario.transmission_headroom_mw)


def unserved_mw(scenario: EnvironmentState, decision: Decision) -> float:
    """max(0, total_demand - (generation - curtailment + discharge + purchase - charge - sale))"""
    generation = scenario.solar_output_mw + scenario.wind_output_mw
    curtailment = decision.curtail_solar_mw + decision.curtail_wind_mw
    discharge = sum(a.amount_mw for a in decision.battery_actions if a.action == "discharge")
    charge = sum(a.amount_mw for a in decision.battery_actions if a.action == "charge")
    purchase = decision.market_amount_mw if decision.market_action == "buy" else 0.0
    sale = decision.market_amount_mw if decision.market_action == "sell" else 0.0
    load_served = generation - curtailment + discharge + purchase - charge - sale
    return max(0.0, scenario.total_demand_mw - load_served)


def power_balance_residual(scenario: EnvironmentState, decision: Decision) -> float:
    """sources - sinks. Should be ~0 (within BALANCE_TOLERANCE_MW) for a consistent decision."""
    generation = scenario.solar_output_mw + scenario.wind_output_mw
    curtailment = decision.curtail_solar_mw + decision.curtail_wind_mw
    discharge = sum(a.amount_mw for a in decision.battery_actions if a.action == "discharge")
    charge = sum(a.amount_mw for a in decision.battery_actions if a.action == "charge")
    purchase = decision.market_amount_mw if decision.market_action == "buy" else 0.0
    sale = decision.market_amount_mw if decision.market_action == "sell" else 0.0
    load_served = min(scenario.total_demand_mw, generation - curtailment + discharge + purchase - charge - sale)
    sources = (generation - curtailment) + discharge + purchase
    sinks = load_served + charge + sale + curtailment
    return sources - sinks


def net_transmission_flow_mw(decision: Decision) -> float:
    """Positive = net export (selling), negative = net import (buying)."""
    if decision.market_action == "sell":
        return decision.market_amount_mw
    if decision.market_action == "buy":
        return -decision.market_amount_mw
    return 0.0


def reserve_margin_headroom_mw(scenario: EnvironmentState, decision: Decision, floor_pct: float) -> float:
    """Unused discharge capacity above the applied floor, plus unused import headroom."""
    total_discharge_capacity = sum(max_discharge_mw(b, floor_pct, emergency=False) for b in scenario.batteries)
    used_discharge = sum(a.amount_mw for a in decision.battery_actions if a.action == "discharge")
    unused_discharge = max(0.0, total_discharge_capacity - used_discharge)

    used_import = decision.market_amount_mw if decision.market_action == "buy" else 0.0
    unused_import_headroom = max(0.0, scenario.transmission_headroom_mw - used_import)

    return unused_discharge + unused_import_headroom


def sellable_surplus_mw(scenario: EnvironmentState) -> float:
    """The most surplus that could actually be sold this tick: generation above demand,
    capped by transmission headroom. Single definition shared by rule_5, reference_dispatch,
    and orchestrator_facts (Patch 3 addendum) — nothing recomputes this independently."""
    surplus = max(0.0, total_generation_mw(scenario) - scenario.total_demand_mw)
    return min(surplus, scenario.transmission_headroom_mw)


def max_import_mw(scenario: EnvironmentState) -> float:
    """The hard ceiling on a purchase this tick. Net flow = sale - purchase, bounded in
    absolute value by transmission_headroom_mw (see module docstring) — a planned sale would
    RAISE the purchase ceiling, not lower it, and buying and selling in the same tick is
    never a sensible decision anyway, so this is simply the full headroom (Patch 3
    addendum — corrects an earlier wrong "headroom minus planned sale" proposal)."""
    return scenario.transmission_headroom_mw


def max_achievable_headroom_mw(scenario: EnvironmentState, floor_pct: float) -> float:
    """The best reserve-margin headroom any decision could achieve this tick: available
    battery discharge above floor_pct (rate- and SoC-limited) plus import headroom, with
    any current shortfall covered first (Brief 2 Patch 2, Step 1). Tells rule_3b's target
    apart from an unattainable one — judging a decision against more margin than physically
    exists would be unfair, not strict."""
    generation = total_generation_mw(scenario)
    shortfall = max(0.0, scenario.total_demand_mw - generation)
    lever_capacity = sum(max_discharge_mw(b, floor_pct, emergency=False) for b in scenario.batteries) + scenario.transmission_headroom_mw
    return max(0.0, lever_capacity - shortfall)


def min_achievable_unserved_mw(scenario: EnvironmentState) -> float:
    """The best ANY decision could do: generation + every battery discharged all the way to
    its absolute minimum safe charge (not just the reserve floor — this is "what's physically
    possible", not "what's policy-compliant") + import up to transmission headroom. If this is
    still short of total demand, the scenario is physically infeasible — a generator bug, not
    a model mistake (Brief 2 Patch, Step 5)."""
    generation = scenario.solar_output_mw + scenario.wind_output_mw
    max_emergency_discharge = sum(max_discharge_mw(b, 0.0, emergency=True) for b in scenario.batteries)
    best_case_supply = generation + max_emergency_discharge + scenario.transmission_headroom_mw
    return max(0.0, scenario.total_demand_mw - best_case_supply)


def total_generation_mw(scenario: EnvironmentState) -> float:
    return scenario.solar_output_mw + scenario.wind_output_mw


def net_position_mw(generation_mw: float, demand_mw: float) -> float:
    """Positive = surplus, negative = shortfall."""
    return generation_mw - demand_mw


def position_label(net_position: float) -> str:
    if net_position > BALANCE_TOLERANCE_MW:
        return "surplus"
    if net_position < -BALANCE_TOLERANCE_MW:
        return "shortfall"
    return "balanced"


def battery_headroom_facts(scenario: EnvironmentState, floor_pct: float) -> dict:
    """Per-battery and total discharge-available (above the applied floor) and charge-headroom
    — the input facts the Orchestrator needs to reason about the shortfall/surplus ladder
    without re-deriving battery math itself (Brief 2 Patch, Step 3)."""
    per_battery = []
    total_discharge = 0.0
    total_charge = 0.0
    for b in scenario.batteries:
        discharge_available = round(max_discharge_mw(b, floor_pct, emergency=False), 1)
        charge_headroom = round(max_charge_mw(b), 1)
        per_battery.append({
            "battery_id": b.id,
            "discharge_available_mw": discharge_available,
            "charge_headroom_mw": charge_headroom,
        })
        total_discharge += discharge_available
        total_charge += charge_headroom
    return {
        "per_battery": per_battery,
        "total_discharge_available_mw": round(total_discharge, 1),
        "total_charge_headroom_mw": round(total_charge, 1),
    }


def orchestrator_facts(scenario: EnvironmentState, floor_pct: float) -> dict:
    """Everything in Step 3: generation, net position (current and forecast), and battery
    headroom — derived from scenario state ONLY. No hidden-tag content, objective expectation,
    or Evaluator output belongs here; the Evaluator's independence from the Orchestrator's
    input must stay intact."""
    generation = total_generation_mw(scenario)
    net_position = net_position_mw(generation, scenario.total_demand_mw)
    forecast_generation = scenario.solar_forecast_mw + scenario.wind_forecast_mw
    forecast_net_position = net_position_mw(forecast_generation, scenario.total_demand_forecast_mw)
    return {
        "total_generation_mw": round(generation, 1),
        "net_position_mw": round(net_position, 1),
        "position": position_label(net_position),
        "forecast_total_generation_mw": round(forecast_generation, 1),
        "forecast_net_position_mw": round(forecast_net_position, 1),
        "forecast_position": position_label(forecast_net_position),
        "sellable_surplus_mw": round(sellable_surplus_mw(scenario), 1),
        "max_import_mw": round(max_import_mw(scenario), 1),
        **battery_headroom_facts(scenario, floor_pct),
    }
