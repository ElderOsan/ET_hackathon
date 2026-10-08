import { objectiveLabel } from "../outcome";

export default function ScenarioPanel({ scenario }) {
  if (!scenario) return null;
  return (
    <div className="panel">
      <h2>1. Scenario (tick {scenario.tick})</h2>
      <div className="row" style={{ marginBottom: 10 }}>
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
      <p style={{ fontSize: 13, color: "#c3cada" }}>
        <strong>Expected behavior (evaluator-only, hidden from orchestrator):</strong> {scenario.expected_behavior}
      </p>
      <pre>{JSON.stringify(scenario, null, 2)}</pre>
    </div>
  );
}
