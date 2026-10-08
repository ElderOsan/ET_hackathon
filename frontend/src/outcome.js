// Shared outcome classification (Block B, B3): what ACTUALLY happened on a given run,
// derived from data the backend already returns -- never a UI-local guess, never a new
// backend field. Two things feed this: the `mode` the caller asked for (not a guess -- the
// literal instruction already sent to and acted on by the backend) and `decision.mode` /
// `decision.failure_detail` from the response (the backend's own ground truth about what
// actually happened, which can disagree with what was requested -- e.g. a "live" request
// that fell back to safe mode).

export const EVALUATOR_LINE = "The evaluator is always live. It never sees who decided.";

export const CACHE_MISS_NEEDLE = "no recording for this scenario";

export function isCacheMiss(decision) {
  return decision?.mode === "parse_failed" && (decision?.failure_detail || "").includes(CACHE_MISS_NEEDLE);
}

// requestedMode: the RunMode ("live" | "record" | "replay" | "safe") that was actually sent
// with this request.
export function classifyRunOutcome(decision, requestedMode) {
  if (!decision) return null;
  if (isCacheMiss(decision)) {
    return { kind: "no_recording", label: "No recording for this build", color: "#8fb4ff", background: "#1f2b45" };
  }
  if (decision.mode === "model_call_failed" || decision.mode === "parse_failed") {
    return { kind: "failed", label: "Failed", color: "#ff8a8a", background: "#4a1f23" };
  }
  if (decision.mode === "safe_mode") {
    return { kind: "safe", label: "Safe mode", color: "#f5a666", background: "#3a2a1f" };
  }
  // decision.mode === "agent" -- a real model decision. Whether it was a fresh live call or
  // a replayed one is NOT recoverable from the decision alone (both look identical); that's
  // exactly why this also takes requestedMode -- it's what was actually dispatched.
  if (requestedMode === "replay") {
    return { kind: "recorded", label: "Recorded", color: "#8fb4ff", background: "#1f2b45" };
  }
  return { kind: "live", label: "Live", color: "#7ee0a8", background: "#1f3a2a" };
}

// "none" (no objective declared) reads like missing data -- it isn't; the golden rules
// default it to cost_efficiency. objective is either a declared objective string, null/
// undefined (not yet serialized), or the literal "none" (day_report.py's own JSON encoding
// of "no objective was declared" -- see build_day_report's per_tick entries).
export function objectiveLabel(objective) {
  if (!objective || objective === "none") return "not declared (defaults to cost)";
  return objective;
}

// Label for the mode about to be used on the NEXT run in a panel -- the "armed" state,
// scoped to whichever panel renders it (never a single global guess).
export function armedModeLabel(requestedMode) {
  switch (requestedMode) {
    case "safe": return "Safe mode";
    case "replay": return "Recorded";
    case "live": return "Live";
    case "record": return "Live (and saved)";
    default: return requestedMode;
  }
}
