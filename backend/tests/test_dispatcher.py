"""Patch 3, Step 3: the single deterministic dispatcher. At least 25 cases covering the
golden rules, both ladders, floor bands, the ramp rule, offline batteries, zero headroom,
the tolerance band, and each of the four objectives. No API calls.
"""
from __future__ import annotations

from app.data import dispatcher, physics
from app.data.tuning import BALANCE_TOLERANCE_MW, FLOOR_BANDS, FLOOR_MAX, FLOOR_MIN, FLOOR_STEP_DOWN
from app.models.schemas import Battery, Difficulty, Objective
from tests.test_acceptance import _tick88_scenario

# ---- volatility signal / floor choice: 8 cases -------------------------------------------


def test_01_state_volatility_stable_no_signals():
    scenario = _tick88_scenario(storm_alert=False)
    cls, method = dispatcher.state_volatility_class(scenario)
    assert cls == "stable" and "none" in method


def test_02_state_volatility_some_storm_alone():
    scenario = _tick88_scenario(storm_alert=True)
    cls, _ = dispatcher.state_volatility_class(scenario)
    assert cls == "some_volatility"


def test_03_state_volatility_some_outage_alone():
    scenario = _tick88_scenario(batteries=[
        Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
        Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=False),
    ])
    cls, _ = dispatcher.state_volatility_class(scenario)
    assert cls == "some_volatility"


def test_04_state_volatility_some_price_spike_alone():
    scenario = _tick88_scenario(electricity_price_per_mwh=150.0)
    cls, _ = dispatcher.state_volatility_class(scenario)
    assert cls == "some_volatility"


def test_05_state_volatility_heavy_two_signals():
    scenario = _tick88_scenario(storm_alert=True, electricity_price_per_mwh=150.0)
    cls, _ = dispatcher.state_volatility_class(scenario)
    assert cls == "heavy_volatility"


def test_06_state_volatility_heavy_three_signals():
    scenario = _tick88_scenario(
        storm_alert=True, electricity_price_per_mwh=150.0,
        batteries=[
            Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
            Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=False),
        ],
    )
    cls, method = dispatcher.state_volatility_class(scenario)
    assert cls == "heavy_volatility" and method.count("+") == 2


def test_07_choose_floor_is_band_midpoint_stable():
    scenario = _tick88_scenario(previous_floor_pct=25.0)  # within ramp range of the midpoint
    floor_pct, _ = dispatcher.choose_floor(scenario)
    lo, hi = FLOOR_BANDS["stable"]
    assert floor_pct == (lo + hi) / 2


def test_08_choose_floor_respects_hard_bounds():
    scenario = _tick88_scenario(storm_alert=True, electricity_price_per_mwh=150.0, previous_floor_pct=50.0)
    floor_pct, _ = dispatcher.choose_floor(scenario)
    assert FLOOR_MIN <= floor_pct <= FLOOR_MAX


# ---- ramp rule: 3 cases --------------------------------------------------------------------


def test_09_ramp_limits_a_large_drop():
    assert physics.apply_floor_clamp_and_ramp(20.0, 50.0) == 50.0 - FLOOR_STEP_DOWN


def test_10_ramp_allows_any_rise():
    assert physics.apply_floor_clamp_and_ramp(60.0, 20.0) == 60.0


def test_11_ramp_clamps_below_floor_min_even_after_ramp():
    assert physics.apply_floor_clamp_and_ramp(5.0, 15.0) == FLOOR_MIN  # 15-10=5, but hard bound wins


# ---- shortfall ladder: 6 cases --------------------------------------------------------------


def test_12_shortfall_uses_battery_before_import():
    scenario = _tick88_scenario(total_demand_mw=110.0, total_demand_forecast_mw=110.0)  # shortfall 8.3MW, well within battery capacity
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    assert decision.market_action == "hold"
    assert any(a.action == "discharge" and a.amount_mw > 0 for a in decision.battery_actions)


def test_13_shortfall_imports_remainder_after_battery():
    scenario = _tick88_scenario()  # shortfall 37.3MW, battery capacity 16MW
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    assert decision.market_action == "buy"
    assert round(decision.market_amount_mw, 1) == round(37.3 - 16.0, 1)


def test_14_shortfall_import_capped_by_zero_headroom():
    scenario = _tick88_scenario(transmission_headroom_mw=0.0)
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    assert decision.market_action == "hold" or decision.market_amount_mw == 0.0
    unserved = physics.unserved_mw(scenario, decision)
    assert unserved > 0  # genuinely infeasible to fully serve -- left standing, not invented away


def test_15_shortfall_offline_battery_excluded():
    scenario = _tick88_scenario(batteries=[
        Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
        Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=False),
    ])
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    b2_action = next(a for a in decision.battery_actions if a.battery_id == "battery_2")
    assert b2_action.amount_mw == 0.0


def test_16_shortfall_emergency_discharges_below_floor():
    # SoC close to the floor so the FLOOR (not the rate limit) binds at floor=25%, leaving
    # headroom for the emergency pass (floor=min_safe_soc_pct=10%) to unlock more.
    scenario = _tick88_scenario(
        total_demand_mw=200.0, total_demand_forecast_mw=200.0, transmission_headroom_mw=5.0,
        batteries=[
            Battery(id="battery_1", capacity_mwh=40.0, state_of_charge_pct=30.0, min_safe_soc_pct=10.0, max_charge_rate_mw=10.0, max_discharge_rate_mw=10.0, charging_efficiency_pct=92.0, degradation_pct=2.0, available=True),
            Battery(id="battery_2", capacity_mwh=25.0, state_of_charge_pct=80.0, min_safe_soc_pct=10.0, max_charge_rate_mw=6.0, max_discharge_rate_mw=6.0, charging_efficiency_pct=90.0, degradation_pct=2.0, available=True),
        ],
    )
    assert physics.is_emergency(scenario, 25.0)
    non_emergency_cap = physics.max_discharge_mw(scenario.batteries[0], 25.0, emergency=False)
    emergency_cap = physics.max_discharge_mw(scenario.batteries[0], 25.0, emergency=True)
    assert emergency_cap > non_emergency_cap  # confirms the floor, not the rate, is what's binding here

    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    battery_1 = next(b for b in scenario.batteries if b.id == "battery_1")
    b1_action = next(a for a in decision.battery_actions if a.battery_id == "battery_1")
    resulting = physics.resulting_soc_pct(battery_1, b1_action.amount_mw)
    assert resulting < 25.0  # discharged below the floor -- only legitimate because is_emergency agreed


def test_17_shortfall_no_emergency_never_breaches_floor():
    scenario = _tick88_scenario(transmission_headroom_mw=0.0)  # shortfall, but not an emergency (not enough to force it)
    if not physics.is_emergency(scenario, 25.0):
        decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
        for a in decision.battery_actions:
            if a.action == "discharge":
                battery = next(b for b in scenario.batteries if b.id == a.battery_id)
                assert physics.resulting_soc_pct(battery, a.amount_mw) >= 25.0 - BALANCE_TOLERANCE_MW


# ---- surplus ladder, per objective: 6 cases -------------------------------------------------


def test_18_surplus_cost_efficiency_charges_before_selling():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # 11.7MW surplus < 16MW battery capacity
    decision = dispatcher.dispatch_at_floor(scenario, Objective.COST_EFFICIENCY, 25.0)
    assert decision.market_action == "hold"  # fully absorbed by charging
    assert sum(a.amount_mw for a in decision.battery_actions if a.action == "charge") > 0


def test_19_surplus_min_carbon_charges_before_selling():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)
    decision = dispatcher.dispatch_at_floor(scenario, Objective.MIN_CARBON, 25.0)
    assert decision.market_action == "hold"


def test_20_surplus_max_renewable_charges_before_selling():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)
    decision = dispatcher.dispatch_at_floor(scenario, Objective.MAX_RENEWABLE_UTILISATION, 25.0)
    assert decision.market_action == "hold"


def test_21_surplus_max_profit_sells_before_charging():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)  # 11.7MW surplus, plenty of headroom
    decision = dispatcher.dispatch_at_floor(scenario, Objective.MAX_PROFIT, 25.0)
    assert decision.market_action == "sell"
    assert round(decision.market_amount_mw, 1) == 11.7
    assert all(a.amount_mw == 0 for a in decision.battery_actions)  # nothing left to charge


def test_22_surplus_none_objective_defaults_to_charge_first():
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0)
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    assert decision.market_action == "hold"


def test_23_surplus_curtails_only_after_charge_and_sell_exhausted():
    scenario = _tick88_scenario(total_demand_mw=50.0, total_demand_forecast_mw=50.0, transmission_headroom_mw=10.0)
    # surplus 51.7MW; 16MW battery + 10MW headroom = 26MW absorbed; 25.7MW must curtail.
    decision = dispatcher.dispatch_at_floor(scenario, Objective.COST_EFFICIENCY, 25.0)
    assert decision.curtail_solar_mw + decision.curtail_wind_mw > 0
    assert round(decision.market_amount_mw, 1) == 10.0  # sold exactly the headroom


# ---- transmission headroom and battery rate limits respected: 2 cases ----------------------


def test_24_surplus_sale_never_exceeds_headroom():
    scenario = _tick88_scenario(total_demand_mw=50.0, total_demand_forecast_mw=50.0, transmission_headroom_mw=3.0)
    decision = dispatcher.dispatch_at_floor(scenario, Objective.MAX_PROFIT, 25.0)
    assert decision.market_amount_mw <= 3.0 + BALANCE_TOLERANCE_MW


def test_25_battery_discharge_never_exceeds_rate_limit():
    scenario = _tick88_scenario()  # battery_1 rate limit 10MW, battery_2 rate limit 6MW
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    for a in decision.battery_actions:
        battery = next(b for b in scenario.batteries if b.id == a.battery_id)
        if a.action == "discharge":
            assert a.amount_mw <= battery.max_discharge_rate_mw + BALANCE_TOLERANCE_MW


# ---- golden rules hold on the dispatcher's own output: 3 cases ------------------------------


def test_26_dispatcher_output_never_curtails_while_buying():
    scenario = _tick88_scenario()  # shortfall -- buys, never curtails
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    buying = decision.market_action == "buy" and decision.market_amount_mw > 0
    curtailing = decision.curtail_solar_mw + decision.curtail_wind_mw > 0
    assert not (buying and curtailing)


def test_27_dispatcher_output_never_sells_while_unmet():
    scenario = _tick88_scenario(transmission_headroom_mw=0.0)  # shortfall, infeasible to fully serve
    decision = dispatcher.dispatch_at_floor(scenario, None, 25.0)
    assert decision.market_action != "sell"


def test_28_dispatcher_full_dispatch_picks_its_own_floor_from_state():
    scenario = _tick88_scenario(storm_alert=True, electricity_price_per_mwh=150.0, previous_floor_pct=25.0)
    decision = dispatcher.dispatch(scenario, None)
    lo, hi = FLOOR_BANDS["heavy_volatility"]
    assert decision.applied_floor_pct == physics.apply_floor_clamp_and_ramp((lo + hi) / 2, 25.0)
    assert "state(" in decision.floor_justification
