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

from app.data.tuning import TICK_HOURS
from app.models.schemas import Battery, Decision, EnvironmentState


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
