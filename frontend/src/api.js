const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const api = {
  presets: () => request("/scenario/presets"),
  generateScenario: (body) => request("/scenario/generate", { method: "POST", body: JSON.stringify(body) }),
  normalizeScenario: (scenario) => request("/scenario/normalize", { method: "POST", body: JSON.stringify({ scenario }) }),
  runSingle: (body) => request("/run/single", { method: "POST", body: JSON.stringify(body) }),
  runFromScenario: (scenario, mode) => request("/run/from-scenario", { method: "POST", body: JSON.stringify({ scenario, mode }) }),
  runBatch: (body) => request("/run/batch", { method: "POST", body: JSON.stringify(body) }),
  listRecordings: () => request("/recordings"),
  verifyRecording: (runId) => request(`/recordings/${encodeURIComponent(runId)}/verify`, { method: "POST" }),
  status: () => request("/status"),
  setSimulateOutage: (enabled) => request("/safe-mode/simulate-outage", { method: "POST", body: JSON.stringify({ enabled }) }),
};
