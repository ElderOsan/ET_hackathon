"""C.4: the balancer's Phase A/B unwind order (balance(), app/data/balancer.py), asserted
against the SEQUENCE of repairs it records -- not final MW totals. A test checking only end
state would stay green if the order were reordered but the arithmetic happened to land in the
same place, which would make it worthless as the guard it claims to be.

balance() already exposes its repair sequence in an assertable form: `repairs` is a plain
list, appended to strictly in call order as each phase runs, with a human-readable `reason`
string per entry that names which branch produced it. No change to balancer.py was needed to
make the order observable -- these tests identify each step by a reason substring and assert
list-index order.
"""
from __future__ import annotations

from app.data.balancer import balance
from app.models.schemas import BatteryAction
from tests.test_acceptance import _decision, _tick88_scenario


def _reason_index(repairs, needle: str) -> int:
    for i, r in enumerate(repairs):
        if needle in r.reason:
            return i
    raise AssertionError(f"no repair found with {needle!r} in its reason; repairs were: {[r.reason for r in repairs]}")


def test_phase_a_unwinds_sale_before_curtailment_when_load_is_unmet():
    # A proposal that sells and curtails while load is unmet -- Phase A must remove the sale
    # FIRST, then the curtailment, in that order (balancer.py's own comment: "Unwind order:
    # curtailment, then sale, then charging" describes the ladder priority being undone, but
    # the code's actual sequence -- and what we assert here -- removes sale, then
    # curtailment, then attempts to unwind charging).
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=3.0)
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="sell", market_amount_mw=3.0,
        curtail_solar_mw=20.0, curtail_wind_mw=20.0,
    )
    _applied, repairs = balance(scenario, proposal)

    sale_idx = _reason_index(repairs, "cannot sell while demand is unmet")
    curtail_idx = _reason_index(repairs, "cannot curtail while demand is unmet")
    assert sale_idx < curtail_idx, f"expected the sale unwind to be recorded before the curtailment unwind; got order {[r.reason for r in repairs]}"


def test_phase_a_charge_unwind_branch_is_unreachable_given_the_surplus_cap():
    # Documents a real finding from building this test, not a bug being fixed: the
    # charge-unwind step inside Phase A's shortfall loop can never actually remove anything
    # under the current code. Step 1 caps any proposed charge to renewable_surplus_mw()
    # (generation - demand, floored at 0) BEFORE Phase A runs. Two cases:
    #   - demand > generation: surplus is 0, so charge is already 0 before Phase A starts --
    #     nothing to unwind.
    #   - demand <= generation: once Phase A removes sale and curtailment, served = generation
    #     + discharge - charge >= generation - surplus_cap(charge) = demand, so Phase A's own
    #     "still short" condition is already false by the time the charge-unwind loop would
    #     run, and its first iteration's break fires immediately.
    # Verified here with deliberately extreme over-curtailment and over-selling (not just the
    # ordinary case) to make sure no edge case trips it.
    scenario = _tick88_scenario(total_demand_mw=90.0, total_demand_forecast_mw=90.0, transmission_headroom_mw=3.0)
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="charge", amount_mw=11.7), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="sell", market_amount_mw=50.0,
        curtail_solar_mw=40.0, curtail_wind_mw=60.0,
    )
    _applied, repairs = balance(scenario, proposal)
    assert not any("unwound charging" in r.reason for r in repairs), (
        "a repair with 'unwound charging' fired -- the charge-unwind branch is reachable after "
        "all, which means something about the surplus-cap interaction changed; update this "
        "test's premise rather than deleting it."
    )


def test_phase_b_increases_sale_before_forcing_curtailment():
    # A large surplus the model proposed nothing for -- Phase B must try MORE SALE first (up
    # to transmission headroom), and only force curtailment for whatever's left over.
    scenario = _tick88_scenario(total_demand_mw=20.0, total_demand_forecast_mw=20.0, transmission_headroom_mw=30.0)
    proposal = _decision(
        battery_actions=[BatteryAction(battery_id="battery_1", action="hold", amount_mw=0.0), BatteryAction(battery_id="battery_2", action="hold", amount_mw=0.0)],
        market_action="hold", market_amount_mw=0.0,
        curtail_solar_mw=0.0, curtail_wind_mw=0.0,
    )
    applied, repairs = balance(scenario, proposal)

    sale_idx = _reason_index(repairs, "increased to absorb surplus within transmission headroom")
    curtail_idx = _reason_index(repairs, "forced: surplus remained after load, max charge, and sale up to transmission headroom")
    assert sale_idx < curtail_idx, f"expected the sale increase to be recorded before forced curtailment; got order {[r.reason for r in repairs]}"
    # Sanity: both steps actually did something (not a vacuous pass where one step's amount
    # was zero and the order couldn't have meant anything).
    assert repairs[sale_idx].delta_mw > 0
    assert repairs[curtail_idx].delta_mw > 0
    assert applied.market_action == "sell" and applied.market_amount_mw == 30.0
    assert round(applied.curtail_solar_mw + applied.curtail_wind_mw, 1) == 51.7
