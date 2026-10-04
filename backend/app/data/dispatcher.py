"""The single deterministic dispatcher (Patch 3, Step 3). Implements the golden rules, both
dispatch ladders, the declared objective cascade, and the reserve-floor choice -- built only
on app/data/physics.py, no formula of its own. Produces a COMPLETE Decision from scratch
(no proposal involved), unlike balancer.balance() which only repairs an existing proposal.

Three roles, one implementation:
  1. rule_9's reference baseline (app/data/rules.py calls dispatch_at_floor with the
     decision's own applied_floor_pct -- see balancer.reference_dispatch, Patch 3 addendum).
  2. The safe-mode controller (Patch 3, Step 4): dispatch() picks its own floor and returns
     a complete Decision when the Orchestrator can't.
  3. NOT merged into balancer.balance()'s repair logic -- repairing an existing proposal
     (cap/unwind what was given) and inventing one from scratch solve different problems;
     forcing them into one function risked destabilizing the well-tested repair path for a
     cosmetic merge. Both already share every physics primitive (physics.py) and now also
     share the floor clamp/ramp math (physics.apply_floor_clamp_and_ramp) and the sellable-
     surplus/max-import definitions (physics.sellable_surplus_mw / max_import_mw) -- the
     actual duplication the brief called out is gone; the two functions' distinct CONTROL
     FLOW (repair vs. invent) is not.
"""
from __future__ import annotations

from app.data import physics
from app.data.tuning import (
    BALANCE_TOLERANCE_MW,
    DISPATCHER_PRICE_SPIKE_THRESHOLD_USD,
    FLOOR_BANDS,
)
from app.models.schemas import BatteryAction, Decision, EnvironmentState, Objective


def state_volatility_class(scenario: EnvironmentState) -> tuple[str, str]:
    """The dispatcher's OWN volatility signal, computed from scenario state -- NOT
    scenario_agent._VOLATILITY_CLASS, which is a static map from the profile name and does
    not look at the scenario's actual randomized conditions (see the floor-calibration
    report, Patch 3 addendum). Returns (class, method) so callers can report which signals
    fired. Thresholds: storm_alert, any battery unavailable, and electricity_price_per_mwh
    >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD (a flat $/MWh threshold, not the existing
    _daily_high_threshold proxy in rules.py, which is structurally untriggerable outside
    price_spike)."""
    storm = scenario.storm_alert
    outage = any(not b.available for b in scenario.batteries)
    price_spike = scenario.electricity_price_per_mwh >= DISPATCHER_PRICE_SPIKE_THRESHOLD_USD
    signals = [s for s, present in (("storm_alert", storm), ("battery_outage", outage), ("price_spike", price_spike)) if present]
    if len(signals) >= 2:
        return "heavy_volatility", "state(" + "+".join(signals) + ")"
    if len(signals) == 1:
        return "some_volatility", "state(" + signals[0] + ")"
    return "stable", "state(none)"


def choose_floor(scenario: EnvironmentState) -> tuple[float, str]:
    """Midpoint of the state-derived volatility class's band, then the hard bounds and the
    ramp-down limit (physics.apply_floor_clamp_and_ramp). Returns (floor_pct, method)."""
    vol_class, method = state_volatility_class(scenario)
    band_lo, band_hi = FLOOR_BANDS[vol_class]
    midpoint = (band_lo + band_hi) / 2
    floor_pct = physics.apply_floor_clamp_and_ramp(midpoint, scenario.previous_floor_pct)
    return floor_pct, method


def _shortfall_ladder(scenario: EnvironmentState, floor_pct: float) -> tuple[list[BatteryAction], float]:
    """renewables (implicit — generation is already fixed) -> battery discharge above floor
    -> grid import -> emergency discharge below floor only if physics.is_emergency agrees.
    Same ladder for every objective: in a shortfall there is nothing to sell, so cost,
    carbon and renewable-utilisation all point the same way (use free battery capacity
    before paying for grid import)."""
    generation = physics.total_generation_mw(scenario)
    shortfall = max(0.0, scenario.total_demand_mw - generation)
    actions: list[BatteryAction] = []
    remaining = shortfall
    for b in scenario.batteries:
        cap = physics.max_discharge_mw(b, floor_pct, emergency=False)
        use = round(min(remaining, cap), 1)
        actions.append(BatteryAction(battery_id=b.id, action="discharge" if use > 0 else "hold", amount_mw=use))
        remaining = max(0.0, remaining - use)

    import_mw = round(min(remaining, physics.max_import_mw(scenario)), 1)
    remaining = max(0.0, round(remaining - import_mw, 1))

    if remaining > BALANCE_TOLERANCE_MW and physics.is_emergency(scenario, floor_pct):
        for i, b in enumerate(scenario.batteries):
            if remaining <= BALANCE_TOLERANCE_MW:
                break
            already = actions[i].amount_mw
            emergency_cap = physics.max_discharge_mw(b, 0.0, emergency=True)
            extra = round(min(remaining, max(0.0, emergency_cap - already)), 1)
            if extra > 0:
                actions[i] = BatteryAction(battery_id=b.id, action="discharge", amount_mw=round(already + extra, 1))
                remaining = max(0.0, round(remaining - extra, 1))
    return actions, import_mw


def _surplus_ladder(scenario: EnvironmentState, objective: Objective | None) -> tuple[list[BatteryAction], float, float, float]:
    """serve load -> charge -> sell -> curtail, EXCEPT under max_profit, where sell takes
    priority over charge: charging earns $0 of profit this tick (see the Step-1 "held
    nothing" finding) while selling earns real revenue now, so a profit-seeking autonomous
    dispatcher sells first and only charges what's left. Every other objective follows the
    SYSTEM_PROMPT's general ladder (charge before sell) since preserving renewable energy
    for later use is reasonable under cost/carbon/renewable-utilisation framing.
    Returns (battery_actions, sell_mw, curtail_solar_mw, curtail_wind_mw)."""
    generation = physics.total_generation_mw(scenario)
    surplus = max(0.0, generation - scenario.total_demand_mw)
    sellable = physics.sellable_surplus_mw(scenario)

    if objective == Objective.MAX_PROFIT:
        sell_mw = round(min(surplus, sellable), 1)
        remaining = round(surplus - sell_mw, 1)
        actions: list[BatteryAction] = []
        for b in scenario.batteries:
            cap = physics.max_charge_mw(b)
            use = round(min(remaining, cap), 1)
            actions.append(BatteryAction(battery_id=b.id, action="charge" if use > 0 else "hold", amount_mw=use))
            remaining = max(0.0, round(remaining - use, 1))
    else:
        actions = []
        remaining = surplus
        for b in scenario.batteries:
            cap = physics.max_charge_mw(b)
            use = round(min(remaining, cap), 1)
            actions.append(BatteryAction(battery_id=b.id, action="charge" if use > 0 else "hold", amount_mw=use))
            remaining = max(0.0, round(remaining - use, 1))
        sell_mw = round(min(remaining, sellable), 1)
        remaining = max(0.0, round(remaining - sell_mw, 1))

    curtail_total = max(0.0, remaining)
    if curtail_total > 0:
        from app.data.balancer import _split_curtailment
        curtail_solar, curtail_wind = _split_curtailment(curtail_total, scenario.solar_output_mw, scenario.wind_output_mw, 0.0, 0.0)
    else:
        curtail_solar = curtail_wind = 0.0
    return actions, sell_mw, curtail_solar, curtail_wind


def dispatch_at_floor(scenario: EnvironmentState, objective: Objective | None, floor_pct: float) -> Decision:
    """The complete autonomous decision at an EXPLICITLY GIVEN floor — used by rule_9's
    reference (floor = the decision being judged's own applied_floor_pct, never chosen by
    the dispatcher itself; see balancer.reference_dispatch)."""
    generation = physics.total_generation_mw(scenario)
    shortfall = max(0.0, scenario.total_demand_mw - generation)

    if shortfall > BALANCE_TOLERANCE_MW:
        battery_actions, import_mw = _shortfall_ladder(scenario, floor_pct)
        market_action = "buy" if import_mw > 0 else "hold"
        market_amount = import_mw
        curtail_solar = curtail_wind = 0.0
    else:
        battery_actions, sell_mw, curtail_solar, curtail_wind = _surplus_ladder(scenario, objective)
        market_action = "sell" if sell_mw > 0 else "hold"
        market_amount = sell_mw

    return Decision(
        tick=scenario.tick,
        objective_used=objective.value if objective else "cost_efficiency",
        battery_actions=battery_actions,
        market_action=market_action,
        market_amount_mw=market_amount,
        curtail_solar_mw=curtail_solar,
        curtail_wind_mw=curtail_wind,
        demand_response_triggered=False,
        proposed_floor_pct=floor_pct,
        applied_floor_pct=floor_pct,
        floor_justification="dispatcher: deterministic autonomous dispatch",
        reasoning="Deterministic autonomous dispatch (no model call) -- golden rules, the declared cascade, and the dispatch ladder applied directly.",
        mode="agent",
    )


def dispatch(scenario: EnvironmentState, objective: Objective | None) -> Decision:
    """The complete autonomous decision, CHOOSING its own floor from scenario state
    (choose_floor) -- this is what safe mode calls (Patch 3, Step 4) when there is no model
    decision to judge a floor from."""
    floor_pct, method = choose_floor(scenario)
    decision = dispatch_at_floor(scenario, objective, floor_pct)
    return decision.model_copy(update={"floor_justification": f"dispatcher: {method}, midpoint of the {state_volatility_class(scenario)[0]} band"})
