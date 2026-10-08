// Unit tests for outcome.js's error classifiers, run with plain `node` -- this project has
// no JS test runner (package.json has only dev/build/preview scripts) and none was added for
// this, per the no-new-dependencies constraint for Block B. Covers every failure state B7
// asks for, using synthetic failures rather than spending any API quota to force them live.
//
// Usage: node frontend/scripts/test_outcome.mjs

import assert from "node:assert/strict";
import { classifyError, classifyRequestError } from "../src/outcome.js";

let passed = 0;
function check(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (e) {
    console.error(`FAIL: ${name}`);
    throw e;
  }
}

// --- classifyError (Decision.failure_detail text) -----------------------------------------

check("no key configured", () => {
  const r = classifyError("GEMINI_API_KEY is not set");
  assert.equal(r.cause, "No API key configured");
  assert.match(r.action, /backend\/\.env/);
});

check("invalid/rejected key (401)", () => {
  const r = classifyError("401 PERMISSION_DENIED: API key not valid");
  assert.equal(r.cause, "Invalid or rejected API key");
});

check("invalid/rejected key (403)", () => {
  const r = classifyError("403 Forbidden");
  assert.equal(r.cause, "Invalid or rejected API key");
});

check("rate limited (429)", () => {
  const r = classifyError("429 RESOURCE_EXHAUSTED: quota exceeded");
  assert.equal(r.cause, "Rate limited by Google (free-tier quota)");
  assert.match(r.action, /Safe mode/);
});

check("service unavailable (503)", () => {
  const r = classifyError("503 UNAVAILABLE: model overloaded");
  assert.equal(r.cause, "Gemini temporarily overloaded (503)");
});

check("no recording matches this build (cache miss)", () => {
  const r = classifyError("no recording for this scenario in run 'example_96row_day' (key abc123)");
  assert.equal(r.cause, "No recording matches this build");
  assert.match(r.action, /re-made/);
});

check("safe mode selected -- not a failure, no next action", () => {
  assert.equal(classifyError("Safe mode selected — no live attempt made"), null);
});

check("simulated outage", () => {
  const r = classifyError("Simulated API outage");
  assert.equal(r.cause, "Outage simulated manually");
});

check("unparseable model response", () => {
  const r = classifyError("could not parse model response");
  assert.equal(r.cause, "The model's response could not be parsed");
});

check("no detail -- null", () => {
  assert.equal(classifyError(""), null);
  assert.equal(classifyError(null), null);
});

check("unrecognized detail still gets a cause/action, never a raw dump", () => {
  const r = classifyError("something truly novel went wrong");
  assert.ok(r.cause && r.action);
});

// --- classifyRequestError (api.js's "<status> <statusText>: <body>" errors) ---------------

// These four match file_input.py's actual FileInputError messages (parse_rows) verbatim.
check("wrong file type (400, matches file_input.py's parse_rows exactly)", () => {
  const r = classifyRequestError('400 Bad Request: {"detail": "Unsupported file type \'photo.jpg\' -- upload a .csv or .xlsx file."}');
  assert.equal(r.cause, "Not a spreadsheet the app recognizes");
});

check("empty file (400, no data rows)", () => {
  const r = classifyRequestError('400 Bad Request: {"detail": "File has no data rows."}');
  assert.equal(r.cause, "The file has no rows to run");
});

check("file too large (400, over the MB limit)", () => {
  const r = classifyRequestError('400 Bad Request: {"detail": "File is 8.0MB, over the 5MB limit."}');
  assert.equal(r.cause, "The file is too large");
});

check("generic 400 fallback", () => {
  const r = classifyRequestError('400 Bad Request: {"detail": "something else entirely"}');
  assert.equal(r.cause, "The uploaded file was rejected");
});

check("file-input preview expired / unknown run_id (404)", () => {
  const r = classifyRequestError('404 Not Found: {"detail": "No validated row 3 for run_id \'abc\' -- preview the file again before running it."}');
  assert.equal(r.cause, "This file's preview has expired or is unknown to the server");
  assert.match(r.action, /Upload it again/);
});

check("rate limited via request path (429)", () => {
  const r = classifyRequestError("429 Too Many Requests: quota exceeded");
  assert.equal(r.cause, "Rate limited by Google (free-tier quota)");
});

check("service unavailable via request path (503)", () => {
  const r = classifyRequestError("503 Service Unavailable: overloaded");
  assert.equal(r.cause, "Gemini temporarily overloaded (503)");
});

check("generic 5xx", () => {
  const r = classifyRequestError("500 Internal Server Error: boom");
  assert.equal(r.cause, "The server had a problem completing this request");
});

check("no message -- null", () => {
  assert.equal(classifyRequestError(""), null);
  assert.equal(classifyRequestError(null), null);
});

console.log(`${passed}/${passed} outcome.js classifier tests passed`);
