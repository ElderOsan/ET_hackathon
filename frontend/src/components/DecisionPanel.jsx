export default function DecisionPanel({ proposal, applied, repairs, repaired }) {
  if (!applied) return null;
  const floorAdjusted = applied.proposed_floor_pct !== applied.applied_floor_pct;

  return (
    <div className="panel">
      <h2>2. Orchestrator Decision</h2>
      <p style={{ fontSize: 13, color: "#c3cada" }}>
        <strong>Objective used:</strong> {applied.objective_used}
      </p>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }}>
          proposed floor: {applied.proposed_floor_pct}%
        </span>
        <span className="badge" style={{ background: floorAdjusted ? "#3a2a1f" : "#1f2b45", color: floorAdjusted ? "#f5a666" : "#8fb4ff" }}>
          applied floor: {applied.applied_floor_pct}%{floorAdjusted ? " (adjusted)" : ""}
        </span>
        {repaired && (
          <span className="badge" style={{ background: "#3a2a1f", color: "#f5a666" }}>repaired by balancer</span>
        )}
      </div>
      <p style={{ fontSize: 13, color: "#9aa4b2" }}>
        <strong>Floor justification:</strong> {applied.floor_justification}
      </p>

      <h3 style={{ fontSize: 13, color: "#9aa4b2", margin: "12px 0 4px" }}>Applied actions (plain words)</h3>
      <ul style={{ fontSize: 13, margin: 0, paddingLeft: 18 }}>
        {applied.battery_actions.filter((a) => a.action !== "hold").map((a) => (
          <li key={a.battery_id}>{a.action === "charge" ? "Charge" : "Discharge"} {a.battery_id} at {a.amount_mw} MW</li>
        ))}
        {applied.market_action === "buy" && <li>Buy {applied.market_amount_mw} MW from the grid</li>}
        {applied.market_action === "sell" && <li>Sell {applied.market_amount_mw} MW to the grid</li>}
        {(applied.curtail_solar_mw > 0 || applied.curtail_wind_mw > 0) && (
          <li>Curtail {applied.curtail_solar_mw} MW solar + {applied.curtail_wind_mw} MW wind</li>
        )}
        {applied.demand_response_triggered && <li>Trigger demand response</li>}
      </ul>

      {repairs && repairs.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, color: "#9aa4b2", margin: "12px 0 4px" }}>Balancer repairs — what changed from the model's proposal</h3>
          <ul className="rule-list">
            {repairs.map((r, i) => (
              <li key={i}>
                <span>
                  <strong>{r.field}</strong>: {r.proposed} → {r.applied} ({r.delta_mw > 0 ? "+" : ""}{r.delta_mw.toFixed(1)} MW)
                  <br />
                  <span style={{ color: "#9aa4b2" }}>{r.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <p style={{ fontSize: 13, whiteSpace: "pre-wrap", marginTop: 10 }}>{applied.reasoning}</p>

      <details style={{ marginTop: 8 }}>
        <summary style={{ cursor: "pointer", fontSize: 12, color: "#9aa4b2" }}>Raw proposal vs applied (JSON)</summary>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 11, color: "#9aa4b2" }}>Proposal (before balancer)</p>
            <pre>{JSON.stringify(proposal, null, 2)}</pre>
          </div>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 11, color: "#9aa4b2" }}>Applied (after balancer)</p>
            <pre>{JSON.stringify(applied, null, 2)}</pre>
          </div>
        </div>
      </details>
    </div>
  );
}
