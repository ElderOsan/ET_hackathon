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
- The **Batch Run** panel adds cumulative pass rates and a per-rule failure breakdown.
  **File Input** runs (and the pre-recorded 96-row day via Door 1) can open a dedicated
  **day-report screen**: a per-tick ledger (cost, revenue, profit, emissions, renewable
  utilisation) plus a side-by-side comparison against **two** deterministic dispatcher
  baselines — one under the day's own declared objective per tick, one fixed to
  `cost_efficiency` throughout — so you can see both how the agent compares to the
  deterministic fallback and what declaring an objective changes on its own.
- `reports/` holds this project's own written-up findings as the build progressed —
  `reports/round0.md` is the main benchmark report against the project's exit tiers;
  `evidence/` holds the raw data (stored scenarios, recorded calls, rule-fire counts, secret
  scans) everything in `reports/` was computed from.

## Measured results

### Dispatcher vs agent head-to-head (identical 72 scenarios, same evaluator)

Source: `evidence/dispatcher_vs_round1_head_to_head.json` (zero model calls — the deterministic
dispatcher run on the exact same 72 scenarios as the round1 benchmark below, scored by the
same current evaluator).

| | raw / first-attempt | applied (after repair) |
|---|---|---|
| **Dispatcher** | 59 pass / 13 flagged / 0 fail — 81.9% | identical: 59/13/0 — 81.9%, 0/72 needed any repair |
| **Agent** (round1) | 61/72 = 84.7% | 59 pass / 9 flagged / 3 fail — 81.9% |

The agent leads before repair, ties after repair, and produces three hard failures the
dispatcher never produces. On this benchmark the LLM orchestrator does not demonstrate an
advantage over the deterministic dispatcher.

The composition difference is the informative part: the agent has fewer flags than the
dispatcher (9 vs 13) and more fails (3 vs 0) — it trades minor cascade deviations for
occasional hard failures, rather than simply failing less often overall.

The dispatcher is feasible by construction (0/72 repairs needed). Part of what "ties after
repair" measures is that the agent needs a repair stage the dispatcher structurally does not.

The agent's three applied fails are exactly **tick 38** (`evidence/round1_tier_report.json`'s
`fail_rows_raw` — the model isn't shown emergency discharge headroom) and **ticks 16 and 20**
(`reports/round1.md` Part 1B — the balancer caps an over-limit discharge and never substitutes
available grid import). The entire deficit is accounted for by two named, already-documented
defects, not general unreliability.

### Round1 benchmark (72 scenarios, live)

Source: `evidence/round1_benchmark.json` + `evidence/round1_tier_report.json`.

- First-attempt pass rate: **61/72 = 84.7%** (lead number — the one 429/safe-mode scenario
  stays in the denominator and never counts as a pass, per `exit_tiers.json`'s own
  "every scenario in the denominator, no exclusions"). Secondary: **61/71 = 85.9%**
  agent-only, with that one scenario excluded from both the numerator and denominator.
- Tier outcome: **neither Tier G nor Tier A reached.** Tier A clears every quantitative
  criterion (overall pass rate, per-objective minimums, avoidable-unserved %, non-fail rate)
  and misses only the qualitative "replay matches 72/72" item (71/72, strict reading — the
  one rate-limited call never produced a recording to replay). Tier G misses that same item
  plus the stable/surplus/shortfall criterion, by exactly one row (33/36 = 91.7% vs the
  34/36 = 92.0% required — 92% is not an attainable score on a 36-row denominator at all).
  Full breakdown in `reports/round1.md`.

### 96-row day (live run)

Source: `recordings/fileinput_0486961f6cc7/` (current as of D.3's paced re-recording).

- Applied: **80 pass / 15 flagged / 1 fail, out of 96 — 83.3%.**

## Known limitations

- **File input has no state carry-over.** Each uploaded row is an independent tick with its
  own battery state of charge — this is a per-tick decision tester, not a multi-tick
  simulation where one tick's outcome feeds the next.
- **The `max_profit` ladder reword (commit 678c109) has a real but very partial effect on the
  model's surplus (charge-vs-sell) decision, and the other three objectives remain
  indistinguishable from each other.**
  - **Real and causal:** the identical scenario (tick 60, surplus_day, seed 20301306) produced
    `charge 16.0 / sell 34.9` under the pre-678c109 prompt (`evidence/round0_run2_benchmark.json`)
    and `charge 0 / sell 50.9` under the current prompt (`evidence/round1_benchmark.json`) —
    same scenario, different prompt version, different decision.
  - **Very partial:** of round1's 9 max_profit rows that were actually in a surplus state,
    only 1 (tick 60) followed the reworded ladder cleanly; 8 still charged before or instead
    of fully selling. round0_run2's equivalent count on the same 9 rows was 0 (`reports/round1.md`).
  - **Attributable to commit 678c109 as a whole, not to the ladder reword specifically:** that
    commit bundled the reword with two new physics facts in the same change. Round1 ticks 34
    and 36 name the sell-first rule correctly in their own reasoning text, then rationalize
    charging anyway using `surplus_after_max_charge_mw` — one of the new facts — as license
    rather than as the post-sale remainder it actually is. Neither half of the commit can be
    credited individually.

  **Stronger evidence, at the dispatcher level, with no model involved:** `evidence/baseline_divergence_probe.json`
  found that on 30 of 31 constructed surplus states, the deterministic dispatcher's own output
  diverges sharply between `max_profit` and `cost_efficiency` — the declared objective
  genuinely reaches dispatch. But the size of that divergence is bounded: `reports/metric_limitations.md`
  shows it equals exactly the avoided round-trip charging loss (`0.35 MWh x $24.04 sell price
  = $8.41`), because the profit metric values stored energy at the *current* sell price, never
  at a future one. Under this definition, `max_profit` can only ever prefer selling — it has no
  way to reward charging for a later, higher price, which is the actual reason an operator
  charges during a spike. This is a boundary of the metric as defined, not of the dispatcher,
  balancer, or agent.
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

`backend/run_server.bat` / `frontend/run_dev.bat` wrap the two dev commands above.

**`frontend/dist/` is committed on purpose** so judges never need Node — but that means it
can drift from `frontend/src/`. After any frontend change, rebuild it before committing:
```bash
cd frontend
npm run build
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design rationale, and `reports/` /
`evidence/` for this project's own written-up findings and raw data as the build progressed.
