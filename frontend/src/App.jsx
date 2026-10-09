import { useEffect, useState } from "react";
import { api } from "./api";
import ScenarioPanel from "./components/ScenarioPanel";
import DecisionPanel from "./components/DecisionPanel";
import EvaluatorPanel from "./components/EvaluatorPanel";
import BatchRunPanel from "./components/BatchRunPanel";
import ManualEntryForm from "./components/ManualEntryForm";
import FileInputPanel from "./components/FileInputPanel";
import FirstRunScreen from "./components/FirstRunScreen";
import DayReportPanel from "./components/DayReportPanel";
import { ArmedModeLabel } from "./components/OutcomeBadge";

const INTRO_DISMISSED_KEY = "orchestrator_intro_dismissed";

export default function App() {
  const [presets, setPresets] = useState({ difficulties: [], objectives: [] });
  const [mode, setMode] = useState("auto"); // scenario entry mode: auto / manual
  const [runMode, setRunMode] = useState("live"); // model-call mode: live / safe / replay (Patch 3, Step 4)
  const [status, setStatus] = useState(null); // {key_configured, model, simulating_outage}
  const [difficulty, setDifficulty] = useState("");
  const [objective, setObjective] = useState("");
  const [generatedScenario, setGeneratedScenario] = useState(null);
  const [result, setResult] = useState(null); // full ScenarioRunResult: scenario/proposal/applied/repairs/repaired/evaluation
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // B1: "intro" (first-run screen) | "main" (today's existing layout) | "dayReport" (Door 1).
  const [view, setView] = useState("intro");
  const [dayReportSource, setDayReportSource] = useState(null); // {label} -- which door opened it, for DayReportPanel's own fetch
  const [presetHint, setPresetHint] = useState(null); // B8: demo-preset guidance text, shown until the user acts manually

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
        if (!s.key_configured) {
          setRunMode("safe"); // no key -> default straight to Safe mode, no error shown
        }
        // The doors show on first visit regardless of key state -- Door 1 (recorded day,
        // no key needed) and Door 2 (safe mode) are worth seeing even by a judge who already
        // set up a key, and Door 3 itself already adapts its own copy to key_configured.
        // Only a remembered dismissal (not key state) skips straight to the main view.
        if (localStorage.getItem(INTRO_DISMISSED_KEY)) {
          setView("main");
        }
      })
      .catch(() => {});
  }, []);

  function dismissIntro() {
    try {
      localStorage.setItem(INTRO_DISMISSED_KEY, "1");
    } catch {
      /* private window / blocked storage -- the tour just reshows next time, harmless */
    }
    setView("main");
  }

  function openIntro() {
    setView("intro");
  }

  // Door 2: safe mode, main view, mode already selected.
  function chooseDoorSafeMode() {
    setMode("auto");
    setRunMode("safe");
    dismissIntro();
  }

  // Door 3: key is reported as configured or not (boolean only -- never the value), handled
  // entirely by the door's own copy; "go straight to the main view in live mode" when one is.
  function chooseDoorLiveAgent() {
    setMode("auto");
    setRunMode("live");
    dismissIntro();
  }

  // Door 1: the recorded 96-row day. Opens the day-report screen; DayReportPanel itself runs
  // the mode="replay" sequence (never live -- see DayReportPanel/api.runFileInputRow).
  function chooseDoorRecordedDay() {
    setDayReportSource({ label: "96-row recorded day" });
    setView("dayReport");
  }

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
    setPresetHint(null);
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

  // B8: demo presets -- load a known-shape scenario into Manual mode so a judge can see and
  // edit the values before running. Never fires a run directly.
  async function loadPreset(presetDifficulty, seed, hint) {
    reset();
    setMode("manual");
    setDifficulty(presetDifficulty);
    setObjective("");
    setPresetHint(hint || null);
    setLoading(true);
    try {
      const s = await api.generateScenario({ difficulty: presetDifficulty, objective: null, seed });
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

  if (view === "intro") {
    return (
      <div className="app">
        <h1>Renewable Energy Orchestrator</h1>
        <p className="subtitle">ET × Accenture AI Hackathon — Agentic Edition</p>
        <FirstRunScreen
          status={status}
          onChooseRecordedDay={chooseDoorRecordedDay}
          onChooseSafeMode={chooseDoorSafeMode}
          onChooseLiveAgent={chooseDoorLiveAgent}
          onSkip={dismissIntro}
        />
      </div>
    );
  }

  if (view === "dayReport") {
    return (
      <div className="app">
        <h1>Renewable Energy Orchestrator</h1>
        <p className="subtitle">ET × Accenture AI Hackathon — Agentic Edition</p>
        <div className="row" style={{ marginBottom: 8 }}>
          <button onClick={() => setView("main")}>← Back to full controls</button>
          <button onClick={openIntro}>Take the tour</button>
        </div>
        <DayReportPanel source={dayReportSource} />
      </div>
    );
  }

  return (
    <div className="app">
      <h1>Renewable Energy Orchestrator</h1>
      <p className="subtitle">
        ET × Accenture AI Hackathon — Agentic Edition
        {" — "}
        <button className="link-button" onClick={openIntro} style={{ font: "inherit", color: "#8fb4ff", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
          Take the tour
        </button>
      </p>

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
          <ArmedModeLabel requestedMode={runMode} />

          {mode === "auto" ? (
            <button onClick={runAuto} disabled={loading}>{loading ? "Running…" : "Run Scenario (Auto)"}</button>
          ) : (
            <button onClick={generateScenario} disabled={loading}>{loading ? "Working…" : "Generate Scenario"}</button>
          )}
        </div>

        <div className="row" style={{ marginTop: 10, alignItems: "baseline" }}>
          <span style={{ fontSize: 12, color: "#9aa4b2" }}>Demo presets — load into the form below, edit anything, then run:</span>
          <button className="secondary" disabled={loading} onClick={() => loadPreset(
            "surplus_day", 777001,
            "Loaded the same surplus state under every objective (D4_SURPLUS_DAY, seed 777001) matches what the ladder reword was for: now change the Objective field below and run — max_profit should sell before charging; every other objective should charge first. Re-load this preset and switch Objective to compare."
          )}>
            Compare objectives on one state
          </button>
          <button className="secondary" disabled={loading} onClick={() => loadPreset("stable_day", 200001)}>A calm day</button>
          <button className="secondary" disabled={loading} onClick={() => loadPreset("price_spike", 400001)}>A price spike</button>
          <button className="secondary" disabled={loading} onClick={() => loadPreset("multi_failure_cascade", 300002)}>A multi-failure cascade</button>
        </div>
        {presetHint && (
          <p style={{ fontSize: 12, color: "#8fb4ff", background: "#1f2b45", padding: 8, borderRadius: 6, marginTop: 8 }}>
            ⓘ {presetHint}
          </p>
        )}

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
            requestedMode={runMode}
          />
          <EvaluatorPanel evaluation={result.stages.find((s) => s.name === "applied").evaluation} />
        </>
      )}

      <BatchRunPanel />
      <FileInputPanel onOpenDayReport={(results) => { setDayReportSource({ label: "File Input run", results }); setView("dayReport"); }} />
    </div>
  );
}
