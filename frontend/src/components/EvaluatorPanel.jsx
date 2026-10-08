import { useState } from "react";

function resultWord(r) {
  if (!r.applicable) return "N/A";
  if (r.passed) return "PASS";
  return r.severity === "fail" ? "FAIL" : "FLAG";
}

function resultClass(r) {
  if (!r.applicable) return "result-na";
  if (r.passed) return "result-pass";
  return r.severity === "fail" ? "result-fail" : "result-flag";
}

function RuleRow({ r }) {
  return (
    <li key={r.rule_id}>
      <span>
        <strong>{r.rule_id}</strong>{" "}
        <span style={{ fontSize: 10, color: "#6b7585" }}>({r.severity === "fail" ? "golden rule" : "advisory"})</span>
        {" "}— {r.description}
        <br />
        <span style={{ color: "#9aa4b2" }}>{r.detail}</span>
        {r.value_label && (
          <>
            <br />
            <span style={{ color: "#6b7585", fontSize: 12 }}>{r.value_label}: {r.value_actual} vs {r.value_reference}</span>
          </>
        )}
      </span>
      <span className={resultClass(r)}>{resultWord(r)}</span>
    </li>
  );
}

export default function EvaluatorPanel({ evaluation }) {
  const [showPassing, setShowPassing] = useState(false);
  if (!evaluation) return null;

  const notPassing = evaluation.rules.filter((r) => !r.passed && r.applicable);
  const naRules = evaluation.rules.filter((r) => !r.applicable);
  const passing = evaluation.rules.filter((r) => r.passed && r.applicable);

  return (
    <div className="panel">
      <h2>3. Evaluator</h2>
      <p style={{ fontSize: 12, color: "#9aa4b2", margin: "-6px 0 10px" }}>
        A deterministic checker, separate from the model, grading the decision against safety
        rules it never sees.
      </p>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className={`badge ${evaluation.status}`}>{evaluation.status}</span>
        <span style={{ fontSize: 13, color: "#9aa4b2" }}>{evaluation.notes}</span>
      </div>

      {notPassing.length > 0 ? (
        <>
          <h3 style={{ fontSize: 13, color: "#ff8a8a", margin: "10px 0 4px" }}>Violated or flagged ({notPassing.length})</h3>
          <ul className="rule-list">
            {notPassing.map((r) => <RuleRow key={r.rule_id} r={r} />)}
          </ul>
        </>
      ) : (
        <p style={{ fontSize: 13, color: "#6fe382" }}>No rules violated or flagged.</p>
      )}

      {naRules.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, color: "#6b7585", margin: "10px 0 4px" }}>Not applicable ({naRules.length}) — nothing for this rule to judge here, not a pass</h3>
          <ul className="rule-list">
            {naRules.map((r) => <RuleRow key={r.rule_id} r={r} />)}
          </ul>
        </>
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
