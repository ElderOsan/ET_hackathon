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
            <p style={{ fontSize: 18, margin: 0 }}>
              Pass rate: <strong>{summary.pass_rate_pct}%</strong> ({summary.passed}/{summary.total} passed, {summary.failed} failed, {summary.flagged} flagged)
            </p>
            <p style={{ fontSize: 18, margin: 0 }}>
              Repair rate: <strong style={{ color: summary.repair_rate_pct > 20 ? "#f5a666" : "#9aa4b2" }}>{summary.repair_rate_pct}%</strong>{" "}
              <span style={{ fontSize: 12, color: "#9aa4b2" }}>({summary.repaired_count} needed balancer repair above tolerance)</span>
            </p>
            <p style={{ fontSize: 13, margin: 0, color: "#9aa4b2" }}>seed: {summary.seed}</p>
          </div>

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
                <th>Status</th>
                <th>Repaired</th>
                <th>Failed/flagged rules</th>
              </tr>
            </thead>
            <tbody>
              {summary.results.map((r) => {
                const failedRules = r.evaluation.rules.filter((x) => !x.passed).map((x) => x.rule_id);
                const isOpen = expandedTick === r.scenario.tick;
                return (
                  <Fragment key={r.scenario.tick}>
                    <tr style={{ cursor: "pointer" }} onClick={() => setExpandedTick(isOpen ? null : r.scenario.tick)}>
                      <td>{r.scenario.tick}</td>
                      <td>{r.scenario.difficulty}</td>
                      <td>{r.scenario.objective || "none"}</td>
                      <td><span className={`badge ${r.evaluation.status}`}>{r.evaluation.status}</span></td>
                      <td>{r.repaired ? "yes" : "no"}</td>
                      <td style={{ fontSize: 12 }}>{failedRules.join(", ") || "—"}</td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={6}>
                          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
                            <div style={{ flex: 1 }}>
                              <p style={{ fontSize: 11, color: "#9aa4b2" }}>Scenario (seed {r.scenario.seed})</p>
                              <pre style={{ maxHeight: 240 }}>{JSON.stringify(r.scenario, null, 2)}</pre>
                            </div>
                            <div style={{ flex: 1 }}>
                              <p style={{ fontSize: 11, color: "#9aa4b2" }}>Applied decision</p>
                              <pre style={{ maxHeight: 240 }}>{JSON.stringify(r.applied, null, 2)}</pre>
                            </div>
                            <div style={{ flex: 1 }}>
                              <p style={{ fontSize: 11, color: "#9aa4b2" }}>Evaluator rules</p>
                              <pre style={{ maxHeight: 240 }}>{JSON.stringify(r.evaluation.rules, null, 2)}</pre>
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
