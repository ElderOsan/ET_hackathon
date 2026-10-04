function plainActions(decision) {
  const lines = [];
  for (const a of decision.battery_actions.filter((a) => a.action !== "hold")) {
    lines.push(`${a.action === "charge" ? "Charge" : "Discharge"} ${a.battery_id} at ${a.amount_mw} MW`);
  }
  if (decision.market_action === "buy") lines.push(`Buy ${decision.market_amount_mw} MW from the grid`);
  if (decision.market_action === "sell") lines.push(`Sell ${decision.market_amount_mw} MW to the grid`);
  if (decision.curtail_solar_mw > 0 || decision.curtail_wind_mw > 0) {
    lines.push(`Curtail ${decision.curtail_solar_mw} MW solar + ${decision.curtail_wind_mw} MW wind`);
  }
  if (decision.demand_response_triggered) lines.push("Trigger demand response");
  if (lines.length === 0) lines.push("Hold — no action");
  return lines;
}

// Mirrors physics.decision_profit exactly — must stay in sync with backend/app/data/physics.py.
function decisionProfit(scenario, decision) {
  const saleMw = decision.market_action === "sell" ? decision.market_amount_mw : 0;
  const purchaseMw = decision.market_action === "buy" ? decision.market_amount_mw : 0;
  const revenue = Math.round(saleMw * scenario.sell_price_per_mwh * 10) / 10;
  const cost = Math.round(purchaseMw * scenario.buy_price_per_mwh * 10) / 10;
  return { saleMw, purchaseMw, revenue, cost, netProfit: Math.round((revenue - cost) * 10) / 10 };
}

export default function DecisionPanel({ scenario, rawStage, appliedStage, repairs, repaired, infeasible, marginInfeasible }) {
  if (!appliedStage) return null;
  const applied = appliedStage.decision;
  const floorAdjusted = applied.proposed_floor_pct !== applied.applied_floor_pct;
  const profit = decisionProfit(scenario, applied);

  return (
    <div className="panel">
      <h2>2. Orchestrator Decision</h2>
      {infeasible && (
        <p style={{ fontSize: 13, color: "#f5a666", background: "#3a2a1f", padding: 8, borderRadius: 6 }}>
          This scenario is physically infeasible — no decision could serve full demand. A generator bug, not a model error.
        </p>
      )}
      {!infeasible && marginInfeasible && (
        <p style={{ fontSize: 13, color: "#f5a666", background: "#3a2a1f", padding: 8, borderRadius: 6 }}>
          Load is served, but the reserve-margin requirement is unreachable this tick (margin infeasible) — rule_3b judges against the best achievable headroom, not the unmet requirement.
        </p>
      )}
      <div className="row" style={{ marginBottom: 8 }}>
        <span className={`badge ${rawStage.evaluation.status}`} title="First-attempt (raw) score">first attempt: {rawStage.evaluation.status}</span>
        <span className={`badge ${appliedStage.evaluation.status}`} title="After the balancer">applied: {appliedStage.evaluation.status}</span>
        {repaired && <span className="badge" style={{ background: "#3a2a1f", color: "#f5a666" }}>repaired by balancer</span>}
      </div>

      <p style={{ fontSize: 13, color: "#c3cada" }}>
        <strong>Objective used:</strong> {applied.objective_used}
      </p>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }}>proposed floor: {applied.proposed_floor_pct}%</span>
        <span className="badge" style={{ background: floorAdjusted ? "#3a2a1f" : "#1f2b45", color: floorAdjusted ? "#f5a666" : "#8fb4ff" }}>
          applied floor: {applied.applied_floor_pct}%{floorAdjusted ? " (adjusted)" : ""}
        </span>
      </div>
      <p style={{ fontSize: 13, color: "#9aa4b2" }}><strong>Floor justification:</strong> {applied.floor_justification}</p>
      {(profit.saleMw > 0 || profit.purchaseMw > 0) && (
        <p style={{ fontSize: 13, color: profit.netProfit >= 0 ? "#6fe382" : "#ff8a8a" }}>
          <strong>Net profit this tick:</strong> ${profit.netProfit.toFixed(1)}{" "}
          <span style={{ color: "#9aa4b2" }}>
            (revenue ${profit.revenue.toFixed(1)} from selling {profit.saleMw}MW @ ${scenario.sell_price_per_mwh}/MWh
            {" − "}cost ${profit.cost.toFixed(1)} from buying {profit.purchaseMw}MW @ ${scenario.buy_price_per_mwh}/MWh)
          </span>
        </p>
      )}

      <h3 style={{ fontSize: 13, color: "#9aa4b2", margin: "12px 0 4px" }}>Applied actions (plain words)</h3>
      <ul style={{ fontSize: 13, margin: 0, paddingLeft: 18 }}>
        {plainActions(applied).map((line, i) => <li key={i}>{line}</li>)}
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
        <summary style={{ cursor: "pointer", fontSize: 12, color: "#9aa4b2" }}>Raw proposal (first attempt, before the balancer)</summary>
        <p style={{ fontSize: 13, whiteSpace: "pre-wrap", marginTop: 6 }}>{rawStage.decision.reasoning}</p>
        <ul style={{ fontSize: 13, margin: "6px 0", paddingLeft: 18 }}>
          {plainActions(rawStage.decision).map((line, i) => <li key={i}>{line}</li>)}
        </ul>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 11, color: "#9aa4b2" }}>Raw proposal (JSON)</p>
            <pre>{JSON.stringify(rawStage.decision, null, 2)}</pre>
          </div>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 11, color: "#9aa4b2" }}>Applied (JSON)</p>
            <pre>{JSON.stringify(applied, null, 2)}</pre>
          </div>
        </div>
      </details>
    </div>
  );
}
