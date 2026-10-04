import { useEffect, useState } from "react";
import { api } from "./api";
import ScenarioPanel from "./components/ScenarioPanel";
import DecisionPanel from "./components/DecisionPanel";
import EvaluatorPanel from "./components/EvaluatorPanel";
import BatchRunPanel from "./components/BatchRunPanel";
import ManualEntryForm from "./components/ManualEntryForm";

export default function App() {
  const [presets, setPresets] = useState({ difficulties: [], objectives: [] });
  const [mode, setMode] = useState("auto"); // scenario entry mode: auto / manual
  const [runMode, setRunMode] = useState("live"); // model-call mode: live / safe (Patch 3, Step 4)
  const [status, setStatus] = useState(null); // {key_configured, model, simulating_outage}
  const [difficulty, setDifficulty] = useState("");
  const [objective, setObjective] = useState("");
  const [generatedScenario, setGeneratedScenario] = useState(null);
  const [result, setResult] = useState(null); // full ScenarioRunResult: scenario/proposal/applied/repairs/repaired/evaluation
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .presets()
      .then((p) => {
        setPresets(p);
        setDifficulty(p.difficulties[0] || "");
      })
      .catch((e) => setError(String(e)));
    api
      .status()
      .then((s) => {
        setStatus(s);
        if (!s.key_configured) setRunMode("safe"); // no key -> default straight to Safe mode, no error shown
      })
      .catch(() => {});
  }, []);

  async function toggleSimulateOutage(e) {
    const enabled = e.target.checked;
    try {
      const s = await api.setSimulateOutage(enabled);
      setStatus((prev) => ({ ...prev, simulating_outage: s.simulating_outage }));
    } catch (err) {
      setError(String(err));
    }
  }

  function reset() {
    setGeneratedScenario(null);
    setResult(null);
    setError(null);
  }

  async function runAuto() {
    reset();
    setLoading(true);
    try {
      const r = await api.runSingle({ difficulty, objective: objective || null, mode: runMode });
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function generateScenario() {
    reset();
    setLoading(true);
    try {
      const s = await api.generateScenario({ difficulty, objective: objective || null });
      setGeneratedScenario(s);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function sendToOrchestrator(editedScenario) {
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const r = await api.runFromScenario(editedScenario, runMode);
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <h1>Renewable Energy Orchestrator</h1>
      <p className="subtitle">ET × Accenture AI Hackathon — Agentic Edition</p>

      <div className="panel">
        <h2>Controls</h2>
        <div className="row">
          <select value={mode} onChange={(e) => { setMode(e.target.value); reset(); }}>
            <option value="auto">Auto mode</option>
            <option value="manual">Manual mode</option>
          </select>
          <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
            {presets.difficulties.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <select value={objective} onChange={(e) => setObjective(e.target.value)}>
            <option value="">none (cost_efficiency applies)</option>
            {presets.objectives.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
          <select value={runMode} onChange={(e) => setRunMode(e.target.value)} title="Live calls the Orchestrator (auto-falls back to Safe mode on failure). Safe mode uses the deterministic dispatcher directly, no model call.">
            <option value="live">Live agent</option>
            <option value="safe">Safe mode</option>
          </select>

          {mode === "auto" ? (
            <button onClick={runAuto} disabled={loading}>{loading ? "Running…" : "Run Scenario (Auto)"}</button>
          ) : (
            <button onClick={generateScenario} disabled={loading}>{loading ? "Working…" : "Generate Scenario"}</button>
          )}
        </div>

        <div className="row" style={{ marginTop: 8, fontSize: 13 }}>
          {status && !status.key_configured && (
            <span className="badge" style={{ background: "#1f2b45", color: "#8fb4ff" }}>
              No API key configured — Recorded run and Safe mode are available
            </span>
          )}
          {status && (
            <label className="row" style={{ gap: 6 }}>
              <input type="checkbox" checked={!!status.simulating_outage} onChange={toggleSimulateOutage} />
              Simulate API outage (forces an instant fallback to Safe mode — for demoing the fallback path)
            </label>
          )}
        </div>

        {error && <p className="error">{error}</p>}
      </div>

      {mode === "manual" && generatedScenario && !result && (
        <ManualEntryForm original={generatedScenario} presets={presets} onSubmit={sendToOrchestrator} loading={loading} />
      )}

      {result && (
        <>
          <ScenarioPanel scenario={result.scenario} />
          <DecisionPanel
            scenario={result.scenario}
            rawStage={result.stages.find((s) => s.name === "raw")}
            appliedStage={result.stages.find((s) => s.name === "applied")}
            repairs={result.repairs}
            repaired={result.repaired}
            infeasible={result.infeasible}
            marginInfeasible={result.margin_infeasible}
          />
          <EvaluatorPanel evaluation={result.stages.find((s) => s.name === "applied").evaluation} />
        </>
      )}

      <BatchRunPanel />
    </div>
  );
}
