import { classifyRunOutcome, EVALUATOR_LINE } from "../outcome";

// B3's "what actually happened" badge -- a fact about one run, shown on the result itself,
// never on a global strip. showEvaluatorLine prints the verbatim line once, where "who
// decided" is actually in question (next to the badge, not repeated on every row).
export default function OutcomeBadge({ decision, requestedMode, showEvaluatorLine = false }) {
  const outcome = classifyRunOutcome(decision, requestedMode);
  if (!outcome) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className="badge" style={{ background: outcome.background, color: outcome.color, fontWeight: 600 }}>
        {outcome.label}
      </span>
      {showEvaluatorLine && <span style={{ fontSize: 11, color: "#6b7585" }}>{EVALUATOR_LINE}</span>}
    </span>
  );
}

// The "armed" indicator -- what the NEXT run in this panel will do, scoped to that panel's
// own already-selected mode state. A plain inline label, not a separate fetch.
export function ArmedModeLabel({ requestedMode }) {
  const text = { safe: "Safe mode", replay: "Recorded", live: "Live", record: "Live (and saved)" }[requestedMode] || requestedMode;
  return (
    <span style={{ fontSize: 12, color: "#9aa4b2" }}>
      Armed: <strong style={{ color: "#c7ccd4" }}>{text}</strong>
    </span>
  );
}
