import { Fragment, useState } from "react";
import { api } from "../api";

export default function BatchRunPanel() {
  const [nPerCell, setNPerCell] = useState(1);
  const [seed, setSeed] = useState("");
  const [fullMatrix, setFullMatrix] = useState(true);
  const [stripObjective, setStripObjective] = useState(false);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedTick, setExpandedTick] = useState(null);

  async function runBatch() {
    setLoading(true);
    setError(null);
    try {
      const result = await api.runBatch({
        n_per_cell: Number(nPerCell),
        seed: seed === "" ? null : Number(seed),
        full_matrix: fullMatrix,
        strip_objective: stripObjective,
      });
      setSummary(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h2>Batch Run</h2>
      <div className="row">
        <label>
          Scenarios per cell:{" "}
          <input type="number" min="1" max="10" value={nPerCell} onChange={(e) => setNPerCell(e.target.value)} style={{ width: 60 }} />
        </label>
        <label>
          Seed (optional, reuse to reproduce):{" "}
          <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="random" style={{ width: 110 }} />
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={fullMatrix} onChange={(e) => setFullMatrix(e.target.checked)} disabled={stripObjective} />
          Full matrix (every difficulty × all 4 objectives)
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={stripObjective} onChange={(e) => setStripObjective(e.target.checked)} />
          Strip objective (test cost_efficiency fallback)
        </label>
        <button onClick={runBatch} disabled={loading}>
          {loading ? "Running…" : "Run Batch"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {summary && (
        <>
          <div className="row" style={{ marginTop: 14, gap: 24 }}>
            <p style={{ fontSize: 20, margin: 0 }}>
              First-attempt pass rate: <strong>{summary.first_attempt_pass_rate_pct}%</strong>{" "}
              <span style={{ fontSize: 12, color: "#9aa4b2" }}>({summary.first_attempt_passed}/{summary.total}) — the model's own score, before the balancer</span>
            </p>
          </div>
          <div className="row" style={{ marginTop: 6, gap: 24 }}>
            <p style={{ fontSize: 16, margin: 0 }}>
              Applied pass rate: <strong>{summary.applied_pass_rate_pct}%</strong> ({summary.applied_passed}/{summary.total} passed, {summary.applied_failed} failed, {summary.applied_flagged} flagged)
            </p>
            <p style={{ fontSize: 16, margin: 0 }}>
              Repair rate: <strong style={{ color: summary.repair_rate_pct > 20 ? "#f5a666" : "#9aa4b2" }}>{summary.repair_rate_pct}%</strong>{" "}
              <span style={{ fontSize: 12, color: "#9aa4b2" }}>({summary.repaired_count} needed repair above tolerance)</span>
            </p>
            <p style={{ fontSize: 13, margin: 0, color: summary.infeasible_count > 0 ? "#f5a666" : "#9aa4b2" }}>
              infeasible scenarios: {summary.infeasible_count}{summary.infeasible_count > 0 ? " (generator bug — should be 0)" : ""}
            </p>
            <p style={{ fontSize: 13, margin: 0, color: "#9aa4b2" }}>seed: {summary.seed}{summary.seed_set ? ` (${summary.seed_set})` : ""}</p>
          </div>

          <table style={{ marginTop: 12 }}>
            <thead>
              <tr><th>Category (raw-stage failures)</th><th>Count</th></tr>
            </thead>
            <tbody>
              {summary.raw_category_breakdown.map((c) => (
                <tr key={c.category}><td>{c.category}</td><td>{c.failed_or_flagged}</td></tr>
              ))}
            </tbody>
          </table>

          <table style={{ marginTop: 12 }}>
            <thead>
              <tr><th>Objective</th><th>Total</th><th>Passed</th><th>Flagged</th><th>Failed</th></tr>
            </thead>
            <tbody>
              {summary.by_objective.map((o) => (
                <tr key={o.objective}>
                  <td>{o.objective}</td>
                  <td>{o.total}</td>
                  <td>{o.passed}</td>
                  <td>{o.flagged}</td>
                  <td>{o.failed}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Tick</th>
                <th>Difficulty</th>
                <th>Objective</th>
                <th>Raw</th>
                <th>Applied</th>
                <th>Repaired</th>
                <th>Applied failed/flagged rules</th>
              </tr>
            </thead>
            <tbody>
              {summary.results.map((r) => {
                const rawStage = r.stages.find((s) => s.name === "raw");
                const appliedStage = r.stages.find((s) => s.name === "applied");
                const failedRules = appliedStage.evaluation.rules.filter((x) => !x.passed && x.applicable).map((x) => x.rule_id);
                const isOpen = expandedTick === r.scenario.tick;
                return (
                  <Fragment key={r.scenario.tick}>
                    <tr style={{ cursor: "pointer" }} onClick={() => setExpandedTick(isOpen ? null : r.scenario.tick)}>
                      <td>{r.scenario.tick}</td>
                      <td>{r.scenario.difficulty}</td>
                      <td>{r.scenario.objective || "none"}</td>
                      <td><span className={`badge ${rawStage.evaluation.status}`}>{rawStage.evaluation.status}</span></td>
                      <td><span className={`badge ${appliedStage.evaluation.status}`}>{appliedStage.evaluation.status}</span></td>
                      <td>{r.repaired ? "yes" : "no"}</td>
                      <td style={{ fontSize: 12 }}>{failedRules.join(", ") || "—"}</td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={7}>
                          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
                            <div style={{ flex: 1 }}>
                              <p style={{ fontSize: 11, color: "#9aa4b2" }}>Scenario (seed {r.scenario.seed})</p>
                              <pre style={{ maxHeight: 240 }}>{JSON.stringify(r.scenario, null, 2)}</pre>
                            </div>
                            <div style={{ flex: 1 }}>
                              <p style={{ fontSize: 11, color: "#9aa4b2" }}>Raw proposal + verdict</p>
                              <pre style={{ maxHeight: 240 }}>{JSON.stringify(rawStage, null, 2)}</pre>
                            </div>
                            <div style={{ flex: 1 }}>
                              <p style={{ fontSize: 11, color: "#9aa4b2" }}>Applied decision + verdict</p>
                              <pre style={{ maxHeight: 240 }}>{JSON.stringify(appliedStage, null, 2)}</pre>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
