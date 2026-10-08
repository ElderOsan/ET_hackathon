import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { classifyRequestError, objectiveLabel } from "../outcome";
import OutcomeBadge, { ArmedModeLabel } from "./OutcomeBadge";
import EvaluatorPanel from "./EvaluatorPanel";

// Matches GENERATED_DIFFICULTIES (backend/app/models/schemas.py: every Difficulty except
// FILE_INPUT) and Objective's 4 values -- the UI only exposes "full matrix" (all 4
// objectives) and "strip objective" (1, no objective), never a partial list, so the count is
// always one of these two shapes. ESTIMATED_SECONDS_PER_CALL matches file_input.py's own
// measured-mean-latency constant, reused here for consistency rather than inventing a second
// number -- this is client-side arithmetic, not a new backend call.
const GENERATED_DIFFICULTY_COUNT = 6;
const ESTIMATED_SECONDS_PER_CALL = 3.3;

export default function BatchRunPanel() {
  const [nPerCell, setNPerCell] = useState(1);
  const [seed, setSeed] = useState("");
  const [fullMatrix, setFullMatrix] = useState(true);
  const [stripObjective, setStripObjective] = useState(false);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedTick, setExpandedTick] = useState(null);

  // Mode selector (Patch 3, Step 2) -- "safe" is added in Step 4.
  const [mode, setMode] = useState("record");
  const [recordings, setRecordings] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [verifyResult, setVerifyResult] = useState(null);

  useEffect(() => {
    if (mode === "replay") {
      api.listRecordings().then(setRecordings).catch(() => setRecordings([]));
    }
  }, [mode]);

  const estimatedScenarios = mode === "replay" ? null : GENERATED_DIFFICULTY_COUNT * (stripObjective ? 1 : 4) * Math.max(1, Number(nPerCell) || 1);
  const estimatedSeconds = estimatedScenarios == null ? null : Math.round(estimatedScenarios * ESTIMATED_SECONDS_PER_CALL);

  async function runBatch() {
    setLoading(true);
    setError(null);
    setVerifyResult(null);
    try {
      const result = await api.runBatch({
        n_per_cell: Number(nPerCell),
        seed: seed === "" ? null : Number(seed),
        full_matrix: fullMatrix,
        strip_objective: stripObjective,
        mode,
        run_id: mode === "replay" ? selectedRunId : null,
      });
      setSummary(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runVerify() {
    if (!selectedRunId) return;
    const result = await api.verifyRecording(selectedRunId);
    setVerifyResult(result);
  }

  return (
    <div className="panel">
      <h2>Batch Run</h2>
      <p style={{ fontSize: 12, color: "#9aa4b2", margin: "-6px 0 10px" }}>
        Runs many scenarios at once across difficulties and objectives, for an aggregate pass
        rate rather than one decision at a time.
      </p>
      <div className="row" style={{ marginBottom: 8 }}>
        <label>
          Mode:{" "}
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="live">Live agent (not recorded)</option>
            <option value="record">Live agent, recorded (default)</option>
            <option value="replay">Recorded run (no key, no network)</option>
            <option value="safe">Safe mode (no live attempt)</option>
          </select>
        </label>
        {mode === "replay" && (
          <>
            <label>
              Run:{" "}
              <select value={selectedRunId} onChange={(e) => setSelectedRunId(e.target.value)}>
                <option value="">select a recorded run…</option>
                {recordings.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} {r.model ? `(${r.model}, seed ${r.seed}, ${r.scenario_count} scenarios)` : ""}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="secondary" onClick={runVerify} disabled={!selectedRunId}>
              Verify (SHA-256)
            </button>
          </>
        )}
      </div>
      {verifyResult && (
        <p style={{ fontSize: 13, color: verifyResult.ok ? "#6fe382" : "#ff8a8a" }}>
          {verifyResult.ok ? "✓ verified — no file in this run has been modified." : `✗ tampered: ${verifyResult.problems.join("; ")}`}
        </p>
      )}

      <div className="row">
        <label>
          Scenarios per cell:{" "}
          <input type="number" min="1" max="10" value={nPerCell} onChange={(e) => setNPerCell(e.target.value)} style={{ width: 60 }} disabled={mode === "replay"} />
        </label>
        <label>
          Seed (optional, reuse to reproduce):{" "}
          <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="random" style={{ width: 110 }} disabled={mode === "replay"} />
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={fullMatrix} onChange={(e) => setFullMatrix(e.target.checked)} disabled={stripObjective || mode === "replay"} />
          Full matrix (every difficulty × all 4 objectives)
        </label>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={stripObjective} onChange={(e) => setStripObjective(e.target.checked)} disabled={mode === "replay"} />
          Strip objective (test cost_efficiency fallback)
        </label>
        <ArmedModeLabel requestedMode={mode} />
        <button onClick={runBatch} disabled={loading || (mode === "replay" && !selectedRunId)}>
          {loading ? "Running…" : mode === "replay" ? "Replay" : "Run Batch"}
        </button>
      </div>

      {estimatedScenarios != null && !loading && !summary && (
        <p style={{ fontSize: 12, color: "#9aa4b2", margin: "4px 0 0" }}>
          Estimated: <strong>{estimatedScenarios}</strong> scenario{estimatedScenarios === 1 ? "" : "s"}
          {mode !== "safe" && <> (model calls), ~<strong>{estimatedSeconds}s</strong></>}
          {mode === "safe" && <> — no model calls, near-instant</>}
        </p>
      )}
      {loading && (
        <p style={{ fontSize: 13, color: "#9aa4b2", margin: "8px 0 0" }}>
          Running the batch{estimatedSeconds != null && mode !== "safe" ? ` — one request covers all ${estimatedScenarios} scenarios, expect roughly ${estimatedSeconds}s` : ""}.
          This is a single request; the page will update when it completes.
        </p>
      )}

      {error && (() => {
        const info = classifyRequestError(error);
        return (
          <p className="error">
            {info ? <><strong>{info.cause}.</strong> {info.action}<br /><span style={{ fontSize: 11, opacity: 0.7 }}>{error}</span></> : error}
          </p>
        );
      })()}

      {summary && (
        <>
          <div className="row" style={{ marginTop: 14, gap: 24 }}>
            <p style={{ fontSize: 20, margin: 0 }}>
              First-attempt pass rate: <strong>{summary.first_attempt_pass_rate_pct}%</strong>{" "}
              <span style={{ fontSize: 12, color: "#9aa4b2" }}>({summary.first_attempt_passed}/{summary.judged_count}) — the model's own score, before the balancer. Agent-only: excludes safe-mode/unresolved rows.</span>
            </p>
          </div>
          <div className="row" style={{ marginTop: 6, gap: 24 }}>
            <p style={{ fontSize: 16, margin: 0 }}>
              Applied pass rate: <strong>{summary.applied_pass_rate_pct}%</strong> ({summary.applied_passed}/{summary.judged_count} passed, {summary.applied_failed} failed, {summary.applied_flagged} flagged)
            </p>
            <p style={{ fontSize: 16, margin: 0 }}>
              Repair rate: <strong style={{ color: summary.repair_rate_pct > 20 ? "#f5a666" : "#9aa4b2" }}>{summary.repair_rate_pct}%</strong>{" "}
              <span style={{ fontSize: 12, color: "#9aa4b2" }}>({summary.repaired_count} needed repair above tolerance)</span>
            </p>
            <p style={{ fontSize: 13, margin: 0, color: summary.infeasible_count > 0 ? "#f5a666" : "#9aa4b2" }}>
              infeasible scenarios: {summary.infeasible_count}{summary.infeasible_count > 0 ? " (generator bug — should be 0)" : ""}
            </p>
            <p style={{ fontSize: 13, margin: 0, color: "#9aa4b2" }}>
              margin-infeasible: {summary.margin_infeasible_count} <span style={{ fontSize: 11 }}>(reserve-margin target unreachable — expected sometimes, not a bug)</span>
            </p>
            <p style={{ fontSize: 13, margin: 0, color: "#9aa4b2" }}>
              rule_9 N/A: {summary.na_counts_by_rule?.rule_9 || 0} <span style={{ fontSize: 11 }}>(the rule had nothing to judge — the scenario still counts in the pass rates via its other rules)</span>
            </p>
            <p style={{ fontSize: 13, margin: 0, color: summary.safe_mode_count > 0 ? "#f5a666" : "#9aa4b2" }}>
              safe mode: {summary.safe_mode_count} <span style={{ fontSize: 11 }}>({summary.safe_mode_passed} passed, {summary.safe_mode_pass_rate_pct}% — separate rate, never mixed into the agent's score)</span>
            </p>
            {summary.unresolved_count > 0 && (
              <p style={{ fontSize: 13, margin: 0, color: "#ff8a8a" }}>
                unresolved: {summary.unresolved_count} <span style={{ fontSize: 11 }}>(even Safe mode did not run — see the table below)</span>
              </p>
            )}
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
                <th title="tick">Interval</th>
                <th>Difficulty</th>
                <th>Objective</th>
                <th>Mode</th>
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
                      <td>{objectiveLabel(r.scenario.objective)}</td>
                      <td><OutcomeBadge decision={appliedStage.decision} requestedMode={mode} /></td>
                      <td><span className={`badge ${rawStage.evaluation.status}`}>{rawStage.evaluation.status}</span></td>
                      <td><span className={`badge ${appliedStage.evaluation.status}`}>{appliedStage.evaluation.status}</span></td>
                      <td>{r.repaired ? "yes" : "no"}</td>
                      <td style={{ fontSize: 12 }}>{failedRules.join(", ") || "—"}</td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={8}>
                          <EvaluatorPanel evaluation={appliedStage.evaluation} />
                          <div className="row" style={{ alignItems: "flex-start", gap: 16, marginTop: 8 }}>
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
