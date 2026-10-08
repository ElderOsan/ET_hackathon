// Shared outcome classification (Block B, B3): what ACTUALLY happened on a given run,
// derived from data the backend already returns -- never a UI-local guess, never a new
// backend field. Two things feed this: the `mode` the caller asked for (not a guess -- the
// literal instruction already sent to and acted on by the backend) and `decision.mode` /
// `decision.failure_detail` from the response (the backend's own ground truth about what
// actually happened, which can disagree with what was requested -- e.g. a "live" request
// that fell back to safe mode).

export const EVALUATOR_LINE = "The evaluator is always live. It never sees who decided.";

// Decision-level failures (Decision.failure_detail text) -- Patch 3, Step 4: "model errors
// are shown clearly with a next action." Pure function, no DOM/React -- directly testable
// (see scripts/test_outcome.mjs, run with plain `node`; this project has no JS test runner
// and none was added for this, per the no-new-dependencies constraint).
export function classifyError(detail) {
  if (!detail) return null;
  const d = detail.toLowerCase();
  if (d.includes("safe mode selected")) return null; // an intentional choice, not a failure -- no "next action" needed
  if (d.includes(CACHE_MISS_NEEDLE)) return { cause: "No recording matches this build", action: "The recorded day is being re-made — try again once it's updated, or use Safe mode / Live mode." };
  if (d.includes("gemini_api_key is not set")) return { cause: "No API key configured", action: "Add GEMINI_API_KEY to backend/.env, or keep using Safe mode / a Recorded run — neither needs one." };
  if (d.includes("simulated api outage")) return { cause: "Outage simulated manually", action: "Uncheck “Simulate API outage” in Controls to resume live calls." };
  if (d.includes("401") || d.includes("403") || d.includes("permission") || (d.includes("invalid") && d.includes("key"))) return { cause: "Invalid or rejected API key", action: "Check GEMINI_API_KEY in backend/.env against aistudio.google.com, or switch to Safe mode / a Recorded run — neither needs one." };
  // Order matters below: Gemini's own 429/503 messages often mention "model" ("model
  // overloaded"), so the narrower status-code checks must run before the catch-all
  // "model unavailable" one, or a transient 503 misreads as a permanent model-retirement.
  if (d.includes("429") || d.includes("resource_exhausted") || d.includes("quota")) return { cause: "Rate limited by Google (free-tier quota)", action: "Wait a minute and run again, or switch to Safe mode." };
  if (d.includes("503") || d.includes("unavailable") || d.includes("overload")) return { cause: "Gemini temporarily overloaded (503)", action: "Usually clears in under a minute — try again, or switch to Safe mode." };
  if (d.includes("timeout") || d.includes("connection")) return { cause: "Network or connection problem", action: "Check your internet connection and try again." };
  if (d.includes("404") || d.includes("not found") || (d.includes("model") && (d.includes("invalid") || d.includes("unknown") || d.includes("retire")))) return { cause: "Model unavailable or retired", action: "Check GEMINI_MODEL in backend/.env against the current model list." };
  if (d.includes("parse")) return { cause: "The model's response could not be parsed", action: "Usually transient — try again; if it persists, check the model/schema version." };
  return { cause: "Unexpected error", action: "See the detail below." };
}

// Request-level failures (api.js throws `Error("<status> <statusText>: <body>")` -- see
// request()/previewFileInput() in api.js) -- covers the paths classifyError can't reach
// because they never produce a Decision at all: an upload rejected before any scenario
// exists, or a run-row call against a run_id the backend no longer has.
export function classifyRequestError(message) {
  if (!message) return null;
  const m = String(message);
  const status = parseInt(m.match(/^(\d{3})/)?.[1] || "0", 10);
  const lower = m.toLowerCase();
  // These four match file_input.py's FileInputError messages exactly (backend/app/data/
  // file_input.py's parse_rows): "unsupported file type", "over the ...MB limit", "over the
  // ...-row limit", "no data rows". All four are 400s; the wording is what distinguishes them.
  if (status === 400 && lower.includes("unsupported file type")) {
    return { cause: "Not a spreadsheet the app recognizes", action: "Upload a .csv or .xlsx file — the template and example downloads above are both that format." };
  }
  if (status === 400 && lower.includes("no data rows")) {
    return { cause: "The file has no rows to run", action: "Add at least one data row below the header, then re-upload." };
  }
  if (status === 400 && lower.includes("over the")) {
    return { cause: "The file is too large", action: "Split it into smaller files, or reduce the row count — see the limit in the detail below." };
  }
  if (status === 400) {
    return { cause: "The uploaded file was rejected", action: "Check the error detail below, fix the file against the template's Data Dictionary sheet, and re-upload." };
  }
  if (status === 404) {
    return { cause: "This file's preview has expired or is unknown to the server", action: "The backend may have restarted since you last previewed this file. Upload it again before running." };
  }
  if (status === 429) return { cause: "Rate limited by Google (free-tier quota)", action: "Wait a minute and run again, or switch to Safe mode." };
  if (status === 503) return { cause: "Gemini temporarily overloaded (503)", action: "Usually clears in under a minute — try again, or switch to Safe mode." };
  if (status >= 500) return { cause: "The server had a problem completing this request", action: "Try again; if it persists, check the backend's own terminal output." };
  return { cause: "Request failed", action: "See the detail below." };
}

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
