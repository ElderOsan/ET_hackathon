# Renewable Energy Orchestrator

A dual-agent grid-dispatch system (ET × Accenture AI Hackathon — Agentic Edition, Problem 4)
where a Gemini-backed Orchestrator decides battery, market, and curtailment actions each
tick, and a deterministic Evaluator checks every decision against golden rules, a declared
objective cascade, and a dispatcher-computed reference.

## Quick start (3 commands, no Node required)

```bash
git clone <this repo's URL>
cd <repo folder>
```

Then run the one script for your OS — it creates the Python virtual environment, installs
pinned dependencies, starts the server, and opens your browser automatically:

- **Windows:** double-click `run.bat`, or from a terminal: `run.bat`
- **macOS / Linux:** `./run.sh`

That's it — **no Node.js, no `npm`, no separate dev server.** The frontend is pre-built and
committed (`frontend/dist/`); the Python backend serves it directly. First run installs
dependencies and takes a little longer; later runs are fast.

If port 8000 is already taken, the app automatically starts on the next free port and opens
the browser there instead — watch the terminal output for the actual URL.

## The three run modes

Every panel in the UI (Auto, Manual, Batch Run, File Input) has a mode selector:

| Mode | Needs a key? | What it does |
|---|---|---|
| **Safe mode** | No | Runs the deterministic dispatcher (`backend/app/data/dispatcher.py`) directly — no model call, no network, fully reproducible. This is the default the moment no key is configured. |
| **Recorded / Replay** | No | Replays a previously-recorded Gemini response from `recordings/<run_id>/` — zero new model calls, zero network. Use this to explore results without spending any API quota. |
| **Live** | Yes | Calls Gemini for real. Falls back to Safe mode automatically on any infrastructure failure, parse failure, or simulated outage — it will never just crash or hang. |

**You do not need a Gemini API key to use this app.** Safe mode and Replay mode work
immediately, with no setup. A key only unlocks Live mode — get one free (no credit card) at
[aistudio.google.com](https://aistudio.google.com), then put it in `backend/.env`
(copy `backend/.env.example` first; see that file for the exact line to fill in).

## Where the example files are

The **File Input** panel (bulk CSV/Excel upload — each row is one complete, independent
tick) has three downloads:
- **Template** — blank, with a Data Dictionary sheet describing every column.
- **Example (12-row day)** — a hand-built day exercising surplus+curtailment, a
  cost-vs-carbon disagreement, a battery outage, and a storm alert.
- **Example (96-row day, pre-recorded)** — a full 24h day at the simulator's own 15-minute
  tick. Upload it, preview it, pick **Replay** mode, and it runs all 96 rows with **zero API
  key and zero network calls** — the fastest way to see the whole system working.

## How to read the results

- Each run shows a **Raw** verdict (the model's own proposal, before any repair) and an
  **Applied** verdict (after the deterministic balancer fixes anything infeasible) —
  `pass` / `flagged` / `fail`, plus which rule(s) fired and why (click a row to expand the
  full scenario/decision/verdict JSON).
- The **Batch Run** and **File Input** panels add cumulative pass rates, a per-rule failure
  breakdown, and (File Input) a per-tick ledger (cost, revenue, profit, emissions, renewable
  utilisation) with a side-by-side comparison against the dispatcher baseline.
- `reports/` holds this project's own written-up findings as the build progressed —
  `reports/round0.md` is the main benchmark report against the project's exit tiers;
  `evidence/` holds the raw data (stored scenarios, recorded calls, rule-fire counts, secret
  scans) everything in `reports/` was computed from.

## Measured results

*(Placeholders — filled in after the final run before submission.)*

- Round 0 benchmark (72 scenarios, dev seed): first-attempt pass rate **`<PLACEHOLDER>`**,
  tier reached **`<PLACEHOLDER>`** — full breakdown in `reports/round0.md`.
- Dispatcher-as-oracle (200 scenarios, no model calls): **`<PLACEHOLDER>`** clean pass,
  **`<PLACEHOLDER>`** golden-rule pass.
- 96-row day (live run): **`<PLACEHOLDER>`** pass / **`<PLACEHOLDER>`** flagged /
  **`<PLACEHOLDER>`** fail.

## Known limitations

- **File input has no state carry-over.** Each uploaded row is an independent tick with its
  own battery state of charge — this is a per-tick decision tester, not a multi-tick
  simulation where one tick's outcome feeds the next.
- **The declared objective does not reliably change the model's surplus (charge-vs-sell)
  decision.** Under `max_profit`, the ladder is defined to sell before charging; in observed
  runs the live model frequently charges first regardless of the declared objective.
- **The expected reserve-floor band and the dispatcher's own floor choice can legitimately
  disagree.** The *expected* band (what a scenario's volatility class implies) is mapped from
  the scenario's profile name; the *dispatcher's own* floor choice is derived from live state
  signals (storm alert, battery outage, price). These are two different, independent
  computations, and they don't always agree — most consistently on `shortfall_day` scenarios.
- **On cost and carbon, the live agent is often close to the deterministic dispatcher
  baseline**, not clearly ahead of it — the baseline is a strong reference, not a token one.

## Troubleshooting

**"Python was not found" / `run.bat` or `run.sh` exits immediately**
Install Python 3.10+ from [python.org](https://python.org) (Windows: check "Add python.exe
to PATH" during setup) or via your OS package manager, then re-run the script.

**PowerShell won't let me activate the virtual environment**
`run.bat` never runs `Activate.ps1` — it calls `.venv\Scripts\pip.exe` and
`.venv\Scripts\uvicorn.exe` directly by path, so PowerShell's script-execution policy never
comes into it. If you're trying to activate the venv manually for your own use, either run
`run.bat` instead (no activation needed) or use `cmd.exe` instead of PowerShell for that one
command.

**Port already in use**
The startup check detects this and automatically moves to the next free port (8001, 8002,
...) — read the terminal output for the actual URL it opened. To force a specific port
yourself, run `backend\.venv\Scripts\uvicorn.exe app.main:app --port <N>` from `backend/`
directly.

**`pip install` is blocked (managed/locked-down laptop)**
Try `pip install --user -r backend\requirements.txt`, or ask IT for permission to create a
virtual environment and install into it (this project never asks for admin/global install
rights — everything installs into `backend/.venv`, isolated from the system Python).

**Invalid API key**
Live mode will fail that one call and fall back to Safe mode automatically — you'll see
`mode: safe_mode` on the result instead of a crash. Double-check the key in `backend/.env`
(no quotes, no trailing spaces) against what [aistudio.google.com](https://aistudio.google.com)
shows, or just use Safe mode / Replay mode, which need no key at all.

**429 (rate limited) or 503 (overloaded) from the Gemini API**
Already handled: live calls retry automatically with backoff
(`backend/app/agents/orchestrator_agent.py`), and if retries are exhausted the run falls back
to Safe mode rather than failing the request. A `503` during a batch run is usually transient
free-tier overload — wait a minute and try again, or switch to Safe/Replay mode.

## Development (not needed to just run/judge the app)

```bash
# backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt     # macOS/Linux
.venv\Scripts\uvicorn app.main:app --reload --port 8000

# frontend (separate dev server, proxies /api to :8000)
cd frontend
npm install
npm run dev   # http://localhost:5173
```

`run_server.bat` / `run_dev.bat` wrap the two dev commands above.

**`frontend/dist/` is committed on purpose** so judges never need Node — but that means it
can drift from `frontend/src/`. After any frontend change, rebuild it before committing:
```bash
cd frontend
npm run build
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design rationale and
[NEXT_STEPS.md](NEXT_STEPS.md) for what's left to build.
