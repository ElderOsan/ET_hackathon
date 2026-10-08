import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { isCacheMiss, objectiveLabel } from "../outcome";
import OutcomeBadge from "./OutcomeBadge";

function appliedOf(result) {
  return result.stages.find((s) => s.name === "applied");
}

// Door 1: fetch the pre-recorded 96-row example and replay it row by row. mode is hardcoded
// to "replay" -- ReplayRecorder (backend/app/data/recording.py) has no live fallback at all,
// so this can never spend a model call regardless of whether a key is configured.
async function runRecordedDay(onProgress) {
  const file = await api.fetchExample96RowFile();
  const preview = await api.previewFileInput(file);
  const okRows = preview.rows.filter((r) => r.status === "ok");
  const results = [];
  for (let i = 0; i < okRows.length; i++) {
    const row = okRows[i];
    const result = await api.runFileInputRow(preview.run_id, row.row_index, "replay");
    results.push(result);
    onProgress({ done: i + 1, total: okRows.length });
  }
  return results;
}

function downloadJson(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function Stat({ label, value }) {
  return (
    <div style={{ minWidth: 140 }}>
      <div style={{ fontSize: 11, color: "#9aa4b2" }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

const COMPARISON_ROWS = [
  { key: "cost", label: "Purchase cost ($)" },
  { key: "profit", label: "Net profit ($)" },
  { key: "emissions_tonnes", label: "Emissions (t)" },
  { key: "curtailed_mwh", label: "Curtailed (MWh)" },
  { key: "unserved_mwh", label: "Unserved (MWh)" },
];

export default function DayReportPanel({ source }) {
  const [results, setResults] = useState(source?.results || null);
  const [progress, setProgress] = useState(null);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sortChronological, setSortChronological] = useState(false);

  useEffect(() => {
    setReport(null);
    setError(null);
    if (source?.results) {
      setResults(source.results);
      return;
    }
    // Door 1: run the recorded-day sequence ourselves.
    setResults(null);
    setLoading(true);
    setProgress({ done: 0, total: 96 });
    runRecordedDay(setProgress)
      .then((r) => setResults(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [source]);

  useEffect(() => {
    if (!results || results.length === 0) return;
    setLoading(true);
    api
      .dayReport(results)
      .then((r) => setReport(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [results]);

  const cacheMissStats = useMemo(() => {
    if (!results) return { count: 0, total: 0 };
    const count = results.filter((r) => isCacheMiss(appliedOf(r).decision)).length;
    return { count, total: results.length };
  }, [results]);
  const allMiss = cacheMissStats.total > 0 && cacheMissStats.count === cacheMissStats.total;
  const anyMiss = cacheMissStats.count > 0;

  const sortedPerTick = useMemo(() => {
    if (!report) return [];
    const rows = [...report.per_tick];
    if (sortChronological) return rows.sort((a, b) => a.tick - b.tick);
    return rows.sort((a, b) => {
      const aViol = a.verdict.applied !== "pass" ? 0 : 1;
      const bViol = b.verdict.applied !== "pass" ? 0 : 1;
      if (aViol !== bViol) return aViol - bViol;
      return a.tick - b.tick;
    });
  }, [report, sortChronological]);

  if (error) return <div className="panel"><p className="error">{error}</p></div>;

  if (loading && !report) {
    return (
      <div className="panel">
        <h2>Day report</h2>
        {progress ? (
          <p>Replaying the recorded day — {progress.done}/{progress.total} intervals…</p>
        ) : (
          <p>Loading…</p>
        )}
      </div>
    );
  }

  if (!report) return null;

  // Exact, not "most or all": a single genuinely all-miss day replaces the headline entirely
  // rather than rendering a meaningless 0%-everything report.
  if (allMiss) {
    return (
      <div className="panel">
        <h2>Day report — {source?.label}</h2>
        <p style={{ fontSize: 14, color: "#8fb4ff", background: "#1f2b45", padding: 12, borderRadius: 6, fontWeight: 600 }}>
          ⓘ No recording matches this build — all {cacheMissStats.total} intervals missed their
          replay cache. This is not the agent failing; the recorded day is being re-made for
          the current build. Try again once it's updated, or run this file in Safe mode / Live
          mode instead.
        </p>
      </div>
    );
  }

  const distinctObjectives = [...new Set(report.per_tick.map((r) => r.objective))];
  const headerObjectiveLabel = distinctObjectives.length === 1
    ? objectiveLabel(distinctObjectives[0])
    : `mixed (${distinctObjectives.map(objectiveLabel).join(", ")})`;

  return (
    <div className="panel">
      <h2>Day report — {source?.label}</h2>
      <p style={{ fontSize: 13, color: "#9aa4b2" }}>
        {report.row_count} intervals · declared objective: <strong>{headerObjectiveLabel}</strong>
      </p>

      {anyMiss && (
        <p style={{ fontSize: 13, color: "#8fb4ff", background: "#1f2b45", padding: 8, borderRadius: 6, fontWeight: 600 }}>
          ⓘ {cacheMissStats.count} of {cacheMissStats.total} intervals have no recording matching
          this build — not an agent failure. The verdict counts below include those rows as
          failed because no decision exists for them; they are not a reflection of the agent's
          performance.
        </p>
      )}

      <h3 style={{ fontSize: 14, marginTop: 16 }}>Verdict counts — agent's own first attempt, before repair</h3>
      <div className="row" style={{ gap: 24, flexWrap: "wrap" }}>
        <Stat label="Passed" value={report.verdict_summary.counts_first_attempt_raw.pass} />
        <Stat label="Flagged" value={report.verdict_summary.counts_first_attempt_raw.flagged} />
        <Stat label="Failed" value={report.verdict_summary.counts_first_attempt_raw.fail} />
        <Stat label="First-attempt pass rate" value={`${report.verdict_summary.first_attempt_pass_rate_pct}%`} />
      </div>
      <p style={{ fontSize: 11, color: "#6b7585" }}>
        After balancer repair: {report.verdict_summary.counts_applied_after_repair.pass} passed,{" "}
        {report.verdict_summary.counts_applied_after_repair.flagged} flagged,{" "}
        {report.verdict_summary.counts_applied_after_repair.fail} failed ({report.verdict_summary.applied_pass_rate_pct}%).
      </p>

      <h3 style={{ fontSize: 14, marginTop: 16 }}>Cumulative</h3>
      <div className="row" style={{ gap: 24, flexWrap: "wrap" }}>
        <Stat label="Purchase cost ($)" value={report.cumulative.agent.cost.toFixed(1)} />
        <Stat label="Emissions (t)" value={report.cumulative.agent.emissions_tonnes.toFixed(2)} />
        <Stat label="Curtailed (MWh)" value={report.cumulative.agent.curtailed_mwh.toFixed(1)} />
        <Stat label="Unserved (MWh)" value={report.cumulative.agent.unserved_mwh.toFixed(1)} />
        <Stat label="Renewable utilisation" value={`${report.cumulative.mean_renewable_utilisation_pct}%`} />
      </div>

      <h3 style={{ fontSize: 14, marginTop: 16 }}>Agent vs. two deterministic baselines</h3>
      <p style={{ fontSize: 12, color: "#9aa4b2" }}>
        <strong>Same-objective dispatcher</strong> — does the agent match the deterministic
        fallback for the objective it was actually given?{" "}
        <strong>Fixed-cost dispatcher</strong> — what does declaring an objective change at
        all, isolated from the agent (both baselines are the same dispatcher)?
      </p>
      <table>
        <thead>
          <tr><th>Metric</th><th>Agent</th><th>Same-objective dispatcher</th><th>Fixed-cost dispatcher</th></tr>
        </thead>
        <tbody>
          {COMPARISON_ROWS.map(({ key, label }) => {
            const c = report.comparison[key];
            return (
              <tr key={key}>
                <td>{label}</td>
                <td>{c.agent}</td>
                <td>{c.same_objective_baseline} <span style={{ fontSize: 11, color: "#9aa4b2" }}>(diff {c.diff_agent_vs_same_objective})</span></td>
                <td>{c.fixed_cost_baseline} <span style={{ fontSize: 11, color: "#9aa4b2" }}>(diff {c.diff_same_objective_vs_fixed_cost})</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", marginTop: 16 }}>
        <h3 style={{ fontSize: 14 }}>Per-tick</h3>
        <label style={{ fontSize: 12, color: "#9aa4b2" }}>
          <input type="checkbox" checked={sortChronological} onChange={(e) => setSortChronological(e.target.checked)} /> Chronological (default: violations first)
        </label>
      </div>
      <table>
        <thead>
          <tr><th>Tick</th><th>Objective</th><th>Decision</th><th>Floor</th><th>Raw</th><th>Applied</th><th>Failing rules</th></tr>
        </thead>
        <tbody>
          {sortedPerTick.map((row) => (
            <tr key={row.tick}>
              <td>{row.tick}</td>
              <td>{objectiveLabel(row.objective)}</td>
              <td style={{ fontSize: 12 }}>
                {row.decision.market_action !== "hold" && `${row.decision.market_action} ${row.decision.market_amount_mw}MW`}
                {row.decision.battery_actions.filter((a) => a.action !== "hold").map((a) => ` ${a.action} ${a.battery_id} ${a.amount_mw}MW`)}
              </td>
              <td>{row.applied_floor_pct}%</td>
              <td><span className={`badge ${row.verdict.raw}`}>{row.verdict.raw}</span></td>
              <td><span className={`badge ${row.verdict.applied}`}>{row.verdict.applied}</span></td>
              <td style={{ fontSize: 12 }}>{row.verdict.failing_rules.join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row" style={{ marginTop: 16 }}>
        <button className="secondary" onClick={() => downloadJson(report, "day_report.json")}>Export JSON</button>
        <button className="secondary" onClick={() => api.dayReportCsv(results, "day_report.csv")}>Export CSV</button>
      </div>
    </div>
  );
}
