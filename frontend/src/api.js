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

async function downloadFile(path, filename) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
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

  // File input (bulk CSV/Excel upload, Patch 3 Step 5)
  downloadFileInputTemplate: () => downloadFile("/file-input/template", "scenario_template.xlsx"),
  downloadFileInputExample: () => downloadFile("/file-input/example", "example_day.xlsx"),
  previewFileInput: async (file) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/file-input/preview`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
    return res.json();
  },
  runFileInputRow: (runId, rowIndex, mode) => request("/file-input/run-row", { method: "POST", body: JSON.stringify({ run_id: runId, row_index: rowIndex, mode }) }),
};
