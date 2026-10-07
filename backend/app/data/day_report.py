"""Day report: per-tick table, cumulative totals, agent-vs-dispatcher-baseline comparison,
and a verdict summary, computed entirely by code from stored ScenarioRunResults -- never
written by the model. Additive only; reuses physics.build_tick_ledger, physics.unserved_mw,
physics.resulting_soc_pct, and dispatcher.dispatch exactly as they are.

Built for a completed file-input run (one tick per row, no state carry-over), but the
functions here operate on any list of ScenarioRunResult + its matching scenarios -- nothing
here is file-input-specific.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.data import physics
from app.data.balancer import balance
from app.data.dispatcher import dispatch
from app.data.tuning import TICK_HOURS
from app.models.schemas import Battery, Decision, EnvironmentState, Objective, ScenarioRunResult


def _battery_action_mw(decision: Decision, battery_id: str, action: str) -> float:
    for a in decision.battery_actions:
        if a.battery_id == battery_id and a.action == action:
            return a.amount_mw
    return 0.0


def _resulting_soc_pct(battery: Battery, decision: Decision) -> float:
    """SoC after this tick's own action on this battery -- charge or discharge, whichever the
    applied decision assigned it (never both; the schema allows only one action per battery
    per tick). Discharge reuses physics.resulting_soc_pct exactly; charge mirrors
    physics.max_charge_mw's own inverse formula (bus-side MW x TICK_HOURS x efficiency is
    what actually lands in the battery), same as net_stored_energy_change_mwh already does."""
    discharge_mw = _battery_action_mw(decision, battery.id, "discharge")
    if discharge_mw > 0:
        return physics.resulting_soc_pct(battery, discharge_mw)
    charge_mw = _battery_action_mw(decision, battery.id, "charge")
    if charge_mw > 0:
        efficiency = max(battery.charging_efficiency_pct / 100.0, 0.01)
        gained_pct = (charge_mw * TICK_HOURS * efficiency / battery.capacity_mwh) * 100 if battery.capacity_mwh else 0.0
        return round(battery.state_of_charge_pct + gained_pct, 2)
    return battery.state_of_charge_pct


def _applied(result: ScenarioRunResult):
    return next(s for s in result.stages if s.name == "applied")


def _row_ledger_entry(scenario: EnvironmentState, decision: Decision) -> dict[str, Any]:
    ledger = physics.build_tick_ledger(scenario, decision)
    sold_mw = decision.market_amount_mw if decision.market_action == "sell" else 0.0
    bought_mw = decision.market_amount_mw if decision.market_action == "buy" else 0.0
    charged_mw = sum(a.amount_mw for a in decision.battery_actions if a.action == "charge")
    discharged_mw = sum(a.amount_mw for a in decision.battery_actions if a.action == "discharge")
    curtailed_mw = round(decision.curtail_solar_mw + decision.curtail_wind_mw, 1)
    unserved_mw = physics.unserved_mw(scenario, decision)
    return {
        "sold_mw": sold_mw, "bought_mw": bought_mw, "charged_mw": charged_mw, "discharged_mw": discharged_mw,
        "curtailed_mw": curtailed_mw, "unserved_mw": unserved_mw,
        "cost": ledger["purchase_cost"], "revenue": ledger["sales_revenue"], "profit": ledger["profit"],
        "emissions_tonnes": ledger["emissions_tonnes"], "renewable_utilisation_pct": ledger["renewable_utilisation_pct"],
    }


def build_day_report(scenarios: list[EnvironmentState], agent_results: list[ScenarioRunResult]) -> dict:
    """scenarios[i] must be the exact scenario agent_results[i] was run against (same row).
    Computes the agent's own per-tick table, cumulative totals, and TWO deterministic
    dispatcher baselines for the same rows (zero model calls -- dispatch() is deterministic):
    "same_objective" runs the dispatcher under each tick's own declared objective (answers:
    does the agent match the deterministic fallback for the objective it was actually given);
    "fixed_cost" runs the dispatcher under a fixed cost_efficiency objective on every tick,
    regardless of what each row declares (answers: what does declaring an objective change,
    isolated from the agent entirely, since both sides of that comparison are the same
    deterministic dispatcher). Also returns the side-by-side comparison and verdict summary."""
    assert len(scenarios) == len(agent_results)

    per_tick = []
    rule_fire_counts: dict[str, int] = {}
    verdict_counts = {"pass": 0, "flagged": 0, "fail": 0}

    agent_cum = {"cost": 0.0, "revenue": 0.0, "profit": 0.0, "bought_mwh": 0.0, "sold_mwh": 0.0, "curtailed_mwh": 0.0, "unserved_mwh": 0.0, "emissions_tonnes": 0.0}
    same_obj_cum = dict(agent_cum)
    fixed_cost_cum = dict(agent_cum)
    utilisation_values = []

    def _accumulate(cum: dict, entry: dict) -> None:
        for key in ("cost", "revenue", "profit", "emissions_tonnes"):
            cum[key] += entry[key]
        cum["bought_mwh"] += entry["bought_mw"] * TICK_HOURS
        cum["sold_mwh"] += entry["sold_mw"] * TICK_HOURS
        cum["curtailed_mwh"] += entry["curtailed_mw"] * TICK_HOURS
        cum["unserved_mwh"] += entry["unserved_mw"] * TICK_HOURS

    for scenario, agent_result in zip(scenarios, agent_results):
        applied = _applied(agent_result)
        decision = applied.decision

        same_obj_decision = dispatch(scenario, scenario.objective)
        same_obj_applied, _repairs = balance(scenario, same_obj_decision)

        fixed_cost_decision = dispatch(scenario, Objective.COST_EFFICIENCY)
        fixed_cost_applied, _repairs = balance(scenario, fixed_cost_decision)

        agent_entry = _row_ledger_entry(scenario, decision)
        same_obj_entry = _row_ledger_entry(scenario, same_obj_applied)
        fixed_cost_entry = _row_ledger_entry(scenario, fixed_cost_applied)

        _accumulate(agent_cum, agent_entry)
        _accumulate(same_obj_cum, same_obj_entry)
        _accumulate(fixed_cost_cum, fixed_cost_entry)
        utilisation_values.append(agent_entry["renewable_utilisation_pct"])

        batteries_by_id = {b.id: b for b in scenario.batteries}
        resulting_soc = {bid: _resulting_soc_pct(b, decision) for bid, b in batteries_by_id.items()}

        status = applied.evaluation.status.value
        verdict_counts[status] = verdict_counts.get(status, 0) + 1
        failing_rules = []
        for rule in applied.evaluation.rules:
            if not rule.passed and rule.applicable:
                failing_rules.append(rule.rule_id)
                rule_fire_counts[rule.rule_id] = rule_fire_counts.get(rule.rule_id, 0) + 1

        per_tick.append({
            "tick": scenario.tick, "seed": scenario.seed, "objective": scenario.objective.value if scenario.objective else "none",
            "inputs": {
                "solar_output_mw": scenario.solar_output_mw, "wind_output_mw": scenario.wind_output_mw,
                "total_demand_mw": scenario.total_demand_mw, "electricity_price_per_mwh": scenario.electricity_price_per_mwh,
                "battery_soc_pct": {bid: b.state_of_charge_pct for bid, b in batteries_by_id.items()},
            },
            "decision": {
                "market_action": decision.market_action, "market_amount_mw": decision.market_amount_mw,
                "battery_actions": [{"battery_id": a.battery_id, "action": a.action, "amount_mw": a.amount_mw} for a in decision.battery_actions],
                "curtail_solar_mw": decision.curtail_solar_mw, "curtail_wind_mw": decision.curtail_wind_mw, "mode": decision.mode,
            },
            "applied_floor_pct": decision.applied_floor_pct,
            "resulting_soc_pct": resulting_soc,
            "verdict": {"raw": next(s for s in agent_result.stages if s.name == "raw").evaluation.status.value, "applied": status, "failing_rules": failing_rules},
            "ledger": agent_entry,
        })

    def _round_cum(d):
        return {k: round(v, 2) for k, v in d.items()}

    agent_cum = _round_cum(agent_cum)
    same_obj_cum = _round_cum(same_obj_cum)
    fixed_cost_cum = _round_cum(fixed_cost_cum)

    def _pct(diff: float, base: float, zero_diff_ok: float) -> float | None:
        if abs(base) > 1e-9:
            return round((diff / abs(base)) * 100, 1)
        return 0.0 if abs(zero_diff_ok) < 1e-9 else None

    comparison = {}
    for key in ("cost", "profit", "emissions_tonnes", "curtailed_mwh", "unserved_mwh"):
        a, s, f = agent_cum[key], same_obj_cum[key], fixed_cost_cum[key]
        diff_agent_vs_same_objective = round(a - s, 2)
        diff_same_objective_vs_fixed_cost = round(s - f, 2)
        comparison[key] = {
            "agent": a, "same_objective_baseline": s, "fixed_cost_baseline": f,
            "diff_agent_vs_same_objective": diff_agent_vs_same_objective,
            "pct_agent_vs_same_objective": _pct(diff_agent_vs_same_objective, s, a),
            "diff_same_objective_vs_fixed_cost": diff_same_objective_vs_fixed_cost,
            "pct_same_objective_vs_fixed_cost": _pct(diff_same_objective_vs_fixed_cost, f, s),
        }

    mean_utilisation = round(sum(utilisation_values) / len(utilisation_values), 1) if utilisation_values else 0.0

    return {
        "row_count": len(scenarios),
        "per_tick": per_tick,
        "cumulative": {
            "agent": agent_cum,
            "same_objective_baseline": same_obj_cum,
            "fixed_cost_baseline": fixed_cost_cum,
            "mean_renewable_utilisation_pct": mean_utilisation,
        },
        "comparison": comparison,
        "verdict_summary": {"counts": verdict_counts, "rule_fire_counts": rule_fire_counts},
    }


def report_to_json(report: dict) -> str:
    return json.dumps(report, indent=2)


def report_to_csv(report: dict) -> str:
    buf = io.StringIO()
    fieldnames = [
        "tick", "seed", "objective", "solar_output_mw", "wind_output_mw", "total_demand_mw", "electricity_price_per_mwh",
        "battery_1_soc_pct_before", "battery_2_soc_pct_before", "battery_1_soc_pct_after", "battery_2_soc_pct_after",
        "market_action", "market_amount_mw", "battery_1_action", "battery_1_amount_mw", "battery_2_action", "battery_2_amount_mw",
        "curtail_solar_mw", "curtail_wind_mw", "applied_floor_pct", "mode", "raw_verdict", "applied_verdict", "failing_rules",
        "sold_mw", "bought_mw", "charged_mw", "discharged_mw", "curtailed_mw", "unserved_mw",
        "cost", "revenue", "profit", "emissions_tonnes", "renewable_utilisation_pct",
    ]
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for row in report["per_tick"]:
        b1 = next((a for a in row["decision"]["battery_actions"] if a["battery_id"] == "battery_1"), {"action": "hold", "amount_mw": 0.0})
        b2 = next((a for a in row["decision"]["battery_actions"] if a["battery_id"] == "battery_2"), {"action": "hold", "amount_mw": 0.0})
        w.writerow({
            "tick": row["tick"], "seed": row["seed"], "objective": row["objective"],
            "solar_output_mw": row["inputs"]["solar_output_mw"], "wind_output_mw": row["inputs"]["wind_output_mw"],
            "total_demand_mw": row["inputs"]["total_demand_mw"], "electricity_price_per_mwh": row["inputs"]["electricity_price_per_mwh"],
            "battery_1_soc_pct_before": row["inputs"]["battery_soc_pct"].get("battery_1"), "battery_2_soc_pct_before": row["inputs"]["battery_soc_pct"].get("battery_2"),
            "battery_1_soc_pct_after": row["resulting_soc_pct"].get("battery_1"), "battery_2_soc_pct_after": row["resulting_soc_pct"].get("battery_2"),
            "market_action": row["decision"]["market_action"], "market_amount_mw": row["decision"]["market_amount_mw"],
            "battery_1_action": b1["action"], "battery_1_amount_mw": b1["amount_mw"], "battery_2_action": b2["action"], "battery_2_amount_mw": b2["amount_mw"],
            "curtail_solar_mw": row["decision"]["curtail_solar_mw"], "curtail_wind_mw": row["decision"]["curtail_wind_mw"],
            "applied_floor_pct": row["applied_floor_pct"], "mode": row["decision"]["mode"],
            "raw_verdict": row["verdict"]["raw"], "applied_verdict": row["verdict"]["applied"], "failing_rules": ";".join(row["verdict"]["failing_rules"]),
            "sold_mw": row["ledger"]["sold_mw"], "bought_mw": row["ledger"]["bought_mw"], "charged_mw": row["ledger"]["charged_mw"], "discharged_mw": row["ledger"]["discharged_mw"],
            "curtailed_mw": row["ledger"]["curtailed_mw"], "unserved_mw": row["ledger"]["unserved_mw"],
            "cost": row["ledger"]["cost"], "revenue": row["ledger"]["revenue"], "profit": row["ledger"]["profit"],
            "emissions_tonnes": row["ledger"]["emissions_tonnes"], "renewable_utilisation_pct": row["ledger"]["renewable_utilisation_pct"],
        })
    return buf.getvalue()
