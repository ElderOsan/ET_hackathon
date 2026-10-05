import { Fragment, useRef, useState } from "react";
import { api } from "../api";

export default function FileInputPanel() {
  const fileRef = useRef(null);
  const [fileName, setFileName] = useState("");
  const [mode, setMode] = useState("record");
  const [preview, setPreview] = useState(null); // {run_id, rows, ok_count, error_count}
  const [previewError, setPreviewError] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(null); // {done, total, completed, failed, skipped}
  const [resultsByRow, setResultsByRow] = useState({}); // row_index -> ScenarioRunResult | {error}
  const [expandedRow, setExpandedRow] = useState(null);

  async function onFileChosen(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setPreview(null);
    setPreviewError(null);
    setResultsByRow({});
    setProgress(null);
    setPreviewing(true);
    try {
      const result = await api.previewFileInput(file);
      setPreview(result);
    } catch (err) {
      setPreviewError(String(err));
    } finally {
      setPreviewing(false);
    }
  }

  async function runAll() {
    if (!preview) return;
    const okRows = preview.rows.filter((r) => r.status === "ok");
    setRunning(true);
    let completed = 0, failed = 0;
    const skipped = preview.error_count;
    setProgress({ done: 0, total: okRows.length, completed, failed, skipped });
    for (const row of okRows) {
      // Resume: a row already recorded under this run_id/row_index returns instantly from
      // the existing recording cache -- re-running the same file just fast-forwards through it.
      try {
        const result = await api.runFileInputRow(preview.run_id, row.row_index, mode);
        setResultsByRow((prev) => ({ ...prev, [row.row_index]: result }));
        completed += 1;
      } catch (err) {
        setResultsByRow((prev) => ({ ...prev, [row.row_index]: { error: String(err) } }));
        failed += 1;
      }
      setProgress({ done: completed + failed, total: okRows.length, completed, failed, skipped });
    }
    setRunning(false);
  }

  return (
    <div className="panel">
      <h2>File Input (bulk CSV/Excel)</h2>
      <p style={{ fontSize: 13, color: "#9aa4b2" }}>
        Each row is one complete, independent tick — its own battery state of charge, no carry-over from the previous row.
      </p>
      <div className="row">
        <button type="button" className="secondary" onClick={api.downloadFileInputTemplate}>Download template</button>
        <button type="button" className="secondary" onClick={api.downloadFileInputExample}>Download example (12-row day)</button>
        <button type="button" className="secondary" onClick={api.downloadFileInputExample96Row} title="A full 24h day at the simulator's own 15-minute tick, pre-recorded -- upload it, preview it, then pick Replay mode and it runs with no API key at all">
          Download example (96-row day, pre-recorded)
        </button>
        <label>
          Mode:{" "}
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="record">Live agent, recorded (default, resumable)</option>
            <option value="live">Live agent (not recorded)</option>
            <option value="replay">Recorded run (no key, no network)</option>
            <option value="safe">Safe mode (no live attempt)</option>
          </select>
        </label>
        <input ref={fileRef} type="file" accept=".csv,.xlsx" onChange={onFileChosen} />
      </div>

      {previewing && <p>Validating {fileName}…</p>}
      {previewError && <p className="error">{previewError}</p>}

      {preview && (
        <>
          <p style={{ fontSize: 13, margin: "8px 0" }}>
            <strong>{preview.ok_count}</strong> valid, <strong>{preview.error_count}</strong> error{preview.error_count === 1 ? "" : "s"} — run_id <code>{preview.run_id}</code>
          </p>
          <p style={{ fontSize: 13, margin: "0 0 8px", color: "#9aa4b2" }}>
            Estimated: <strong>{preview.estimated_calls}</strong> model call{preview.estimated_calls === 1 ? "" : "s"} (one per valid row), ~<strong>{preview.estimated_seconds}s</strong>{" "}
            <span style={{ fontSize: 11 }}>(measured mean latency per call, first-run / no-cache case — a resumed run with cached rows is much faster)</span>
          </p>
          <table style={{ marginBottom: 12 }}>
            <thead>
              <tr><th>Row</th><th>Tick</th><th>Status</th><th>Volatility (derived)</th><th>Expected floor band</th><th>Errors</th></tr>
            </thead>
            <tbody>
              {preview.rows.map((r) => (
                <tr key={r.row_index}>
                  <td>{r.row_index}</td>
                  <td>{r.tick ?? "—"}</td>
                  <td><span className={`badge ${r.status === "ok" ? "pass" : "fail"}`}>{r.status}</span></td>
                  <td style={{ fontSize: 12 }}>{r.volatility_class ? `${r.volatility_class} via ${r.volatility_method}` : "—"}</td>
                  <td style={{ fontSize: 12 }}>{r.expected_floor_band ?? "—"}</td>
                  <td style={{ fontSize: 12, color: "#ff8a8a" }}>{r.errors?.join("; ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <button onClick={runAll} disabled={running || preview.ok_count === 0}>
            {running ? "Running…" : Object.keys(resultsByRow).length > 0 ? "Resume / Re-run" : "Run"}
          </button>

          {progress && (
            <p style={{ fontSize: 13, margin: "8px 0" }}>
              row {progress.done}/{progress.total} — completed: <strong>{progress.completed}</strong>, failed: <strong>{progress.failed}</strong>, skipped (validation): <strong>{progress.skipped}</strong>
            </p>
          )}

          {Object.keys(resultsByRow).length > 0 && (
            <table style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Row</th><th>Tick</th><th>Objective</th><th>Mode</th><th>Raw</th><th>Applied</th><th>Repaired</th><th>Applied failed/flagged rules</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.filter((r) => r.status === "ok" && resultsByRow[r.row_index]).map((r) => {
                  const res = resultsByRow[r.row_index];
                  if (res.error) {
                    return (
                      <tr key={r.row_index}>
                        <td>{r.row_index}</td><td>{r.tick}</td><td colSpan={6} style={{ color: "#ff8a8a" }}>run failed: {res.error}</td>
                      </tr>
                    );
                  }
                  const rawStage = res.stages.find((s) => s.name === "raw");
                  const appliedStage = res.stages.find((s) => s.name === "applied");
                  const failedRules = appliedStage.evaluation.rules.filter((x) => !x.passed && x.applicable).map((x) => x.rule_id);
                  const isOpen = expandedRow === r.row_index;
                  const rowMode = appliedStage.decision.mode;
                  return (
                    <Fragment key={r.row_index}>
                      <tr style={{ cursor: "pointer" }} onClick={() => setExpandedRow(isOpen ? null : r.row_index)}>
                        <td>{r.row_index}</td>
                        <td>{res.scenario.tick}</td>
                        <td>{res.scenario.objective || "none"}</td>
                        <td>{rowMode !== "agent" && (
                          <span className="badge" style={{ background: rowMode === "safe_mode" ? "#3a2a1f" : "#4a1f23", color: rowMode === "safe_mode" ? "#f5a666" : "#ff8a8a" }}>
                            {rowMode}
                          </span>
                        )}</td>
                        <td><span className={`badge ${rawStage.evaluation.status}`}>{rawStage.evaluation.status}</span></td>
                        <td><span className={`badge ${appliedStage.evaluation.status}`}>{appliedStage.evaluation.status}</span></td>
                        <td>{res.repaired ? "yes" : "no"}</td>
                        <td style={{ fontSize: 12 }}>{failedRules.join(", ") || "—"}</td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={8}>
                            <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
                              <div style={{ flex: 1 }}>
                                <p style={{ fontSize: 11, color: "#9aa4b2" }}>Scenario (tick {res.scenario.tick})</p>
                                <pre style={{ maxHeight: 240 }}>{JSON.stringify(res.scenario, null, 2)}</pre>
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
          )}
        </>
      )}
    </div>
  );
}
