import { useState } from "react";
import { objectiveLabel } from "../outcome";

function Figure({ label, field, value, sub }) {
  return (
    <div style={{ minWidth: 130 }} title={field}>
      <div style={{ fontSize: 11, color: "#9aa4b2" }}>
        {label} <span style={{ color: "#6b7585" }}>({field})</span>
      </div>
      <div style={{ fontSize: 17, fontWeight: 600 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#6b7585" }}>{sub}</div>}
    </div>
  );
}

export default function ScenarioPanel({ scenario }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!scenario) return null;

  const generation = scenario.solar_output_mw + scenario.wind_output_mw;
  const netPosition = generation - scenario.total_demand_mw;
  const positionLabel = netPosition > 0.05 ? "surplus" : netPosition < -0.05 ? "shortfall" : "balanced";

  return (
    <div className="panel">
      <h2>
        1. Scenario <span style={{ textTransform: "none", fontWeight: 400, color: "#6b7585" }}>(15-minute interval — tick {scenario.tick})</span>
      </h2>
      <p style={{ fontSize: 12, color: "#9aa4b2", margin: "-6px 0 10px" }}>
        The grid, weather and market state the Orchestrator decides against this interval.
      </p>
      <div className="row" style={{ marginBottom: 14 }}>
        <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }}>
          {scenario.difficulty}
        </span>
        <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }}>
          objective: {objectiveLabel(scenario.objective)}
        </span>
        <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }} title="Reuse this seed to reproduce this exact scenario">
          seed: {scenario.seed}
        </span>
        {scenario.events.map((e) => (
          <span key={e} className="badge" style={{ background: "#3a2a1f", color: "#f5a666" }}>
            {e}
          </span>
        ))}
      </div>

      <div className="row" style={{ gap: 28, flexWrap: "wrap", marginBottom: 14 }}>
        <Figure
          label="Generation" field="solar_output_mw + wind_output_mw"
          value={`${generation.toFixed(1)} MW`}
          sub={`solar ${scenario.solar_output_mw.toFixed(1)} + wind ${scenario.wind_output_mw.toFixed(1)}`}
        />
        <Figure label="Demand" field="total_demand_mw" value={`${scenario.total_demand_mw.toFixed(1)} MW`} />
        <Figure
          label="Net position" field="net_position_mw"
          value={`${netPosition >= 0 ? "+" : ""}${netPosition.toFixed(1)} MW`}
          sub={positionLabel}
        />
        <Figure
          label="Price" field="electricity_price_per_mwh"
          value={`$${scenario.electricity_price_per_mwh.toFixed(0)}/MWh`}
          sub={`buy $${scenario.buy_price_per_mwh.toFixed(0)} / sell $${scenario.sell_price_per_mwh.toFixed(0)}`}
        />
        <Figure
          label="Grid headroom" field="transmission_headroom_mw"
          value={`${scenario.transmission_headroom_mw.toFixed(1)} MW`}
          sub="max buy/sell this interval"
        />
      </div>

      <div style={{ fontSize: 11, color: "#9aa4b2", marginBottom: 4 }}>Battery state <span style={{ color: "#6b7585" }}>(batteries[].state_of_charge_pct)</span></div>
      <div className="row" style={{ gap: 16, flexWrap: "wrap", marginBottom: 14 }}>
        {scenario.batteries.map((b) => (
          <div key={b.id} title="state_of_charge_pct">
            <span className="badge" style={{ background: b.available ? "#1f252d" : "#3a2a1f", color: b.available ? "#e6e9ef" : "#f5a666" }}>
              {b.id}: {b.state_of_charge_pct.toFixed(1)}%{!b.available ? " (offline)" : ""}
            </span>
          </div>
        ))}
        <div style={{ fontSize: 12, color: "#9aa4b2" }} title="previous_floor_pct">
          reserve held back last interval: {scenario.previous_floor_pct}%
        </div>
      </div>

      <p style={{ fontSize: 13, color: "#c3cada" }}>
        <strong>Expected behavior (evaluator-only, hidden from orchestrator):</strong> {scenario.expected_behavior}
      </p>

      <button className="secondary" onClick={() => setShowRaw((v) => !v)}>
        {showRaw ? "Hide" : "Show"} raw scenario JSON
      </button>
      {showRaw && <pre style={{ marginTop: 8 }}>{JSON.stringify(scenario, null, 2)}</pre>}
    </div>
  );
}
