import { useState } from "react";

function RuleRow({ r }) {
  return (
    <li key={r.rule_id}>
      <span>
        <strong>{r.rule_id}</strong>{" "}
        <span className={`badge ${r.severity === "fail" ? "fail" : "flagged"}`} style={{ fontSize: 10, padding: "1px 6px" }}>
          {r.severity}
        </span>{" "}
        — {r.description}
        <br />
        <span style={{ color: "#9aa4b2" }}>{r.detail}</span>
      </span>
      <span className={r.passed ? "rule-ok" : "rule-bad"}>{r.passed ? "OK" : "VIOLATION"}</span>
    </li>
  );
}

export default function EvaluatorPanel({ evaluation }) {
  const [showPassing, setShowPassing] = useState(false);
  if (!evaluation) return null;

  const violated = evaluation.rules.filter((r) => !r.passed);
  const passing = evaluation.rules.filter((r) => r.passed);

  return (
    <div className="panel">
      <h2>3. Evaluator</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className={`badge ${evaluation.status}`}>{evaluation.status}</span>
        <span style={{ fontSize: 13, color: "#9aa4b2" }}>{evaluation.notes}</span>
      </div>

      {violated.length > 0 ? (
        <>
          <h3 style={{ fontSize: 13, color: "#ff8a8a", margin: "10px 0 4px" }}>Violated or flagged ({violated.length})</h3>
          <ul className="rule-list">
            {violated.map((r) => <RuleRow key={r.rule_id} r={r} />)}
          </ul>
        </>
      ) : (
        <p style={{ fontSize: 13, color: "#6fe382" }}>No rules violated or flagged.</p>
      )}

      {passing.length > 0 && (
        <>
          <button className="secondary" style={{ marginTop: 10 }} onClick={() => setShowPassing((v) => !v)}>
            {showPassing ? "Collapse" : "Show"} all other checks passed ({passing.length})
          </button>
          {showPassing && (
            <ul className="rule-list" style={{ marginTop: 8 }}>
              {passing.map((r) => <RuleRow key={r.rule_id} r={r} />)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
