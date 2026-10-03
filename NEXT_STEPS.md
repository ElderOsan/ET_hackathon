# Next Steps

## 0. Unblock the machine (done 2026-10-03)

Python, Node, and Git are installed. Follow the setup steps in [README.md](README.md). Get
your free Gemini API key (from [aistudio.google.com](https://aistudio.google.com)) into
`backend/.env` before the backend will start — it calls Gemini directly and refuses to boot
without a key.

## 1. Domain grounding (Learning Guide Steps 1–5 — do this in parallel with setup)

The team's `Renewable_Energy_Learning_Guide.docx` lays out a 2–3 hour path to ground the
Evaluator's rules in real grid-operator principles, not guesses:

- **Step 1** (2–3 hrs): research merit order dispatch, battery arbitrage, curtailment
  causes, grid frequency/reliability basics. Links are in the original doc.
- **Step 2**: refine the 6 hard-fail rules already coded in `backend/app/data/rules.py`
  against what you learn — especially Rule 3 (reliability hard-fail) and Rule 5 (the
  `daily_high_threshold` is currently a crude placeholder, not a real daily-high
  calculation).
- **Step 3**: paste the refined checklist + objective logic into a fresh LLM conversation
  and ask it to sanity-check as a grid-ops expert. One-time design review, not a runtime
  component.
- **Step 4**: already encoded as the 4 `Objective` enum values + Default Priority fallback
  in `orchestrator_agent.py` — revisit the per-objective "optimal" definitions once Step 1
  is done.
- **Step 5** (optional, 15 min): show 3–4 real decisions from the running system to anyone
  with adjacent energy/trading experience.

## 2. Verify the MVP actually works end-to-end

Once installs are done:

1. `POST /api/scenario/generate` with each difficulty — confirm reasonable values.
2. `POST /api/run/single` — confirm Gemini returns a valid tool call and the reasoning is
   sane for a `cost_efficiency` scenario vs `min_carbon`.
3. Run the Batch Run panel with ~2–3 scenarios per difficulty, read the failures — they're
   likely your first real signal on whether the heuristics in the system prompt
   (`orchestrator_agent.py::SYSTEM_PROMPT`) need sharpening.
4. Try "strip objective" batch run — confirm the orchestrator visibly falls back to
   Default Priority rather than erroring or guessing.

## 3. Known gaps / stubs to close before submission

- **Gemini free-tier `503 UNAVAILABLE` ("model experiencing high demand")** — happened
  repeatedly on `gemini-3.8-flash` (the newest model, getting hammered by free-tier
  traffic) on 2026-10-03. Fixed two ways: (1) `orchestrator_agent.py` now retries
  automatically up to 5 times with backoff before giving up, and (2) the default model was
  switched to `gemini-3.5-flash-lite`, which wasn't overloaded and gave equally good
  reasoning in testing. If `gemini-3.5-flash-lite` ever gets overloaded too (e.g. right
  before a demo), swap `GEMINI_MODEL` in `backend/.env` to another free-tier model —
  `gemini-3.1-flash-lite` or `gemini-3.6-flash` are other options — and restart the
  backend window. Do **not** switch to `gemini-2.5-flash` — it's been retired for new API
  keys (confirmed via a live 404 from the API).
- **`rule_5` daily-high threshold** (`backend/app/data/rules.py`) is a placeholder
  (`price * 0.95` or `price + 1`) — there's no real daily price series yet. Needs either a
  rolling price history per scenario run, or a fixed realistic daily curve.
- **`max_profit` objective check** (`backend/app/agents/evaluator.py`) currently always
  passes — no real check implemented yet.
- **No time-series simulation (F3)** — current scenarios are single independent ticks.
  F3 requires simulating a scenario over multiple ticks with evolving conditions
  (battery state of charge carrying forward, price trajectories, etc.) — needed if you
  want to claim F3 on the 9-blocker grid.
- **No multimodal input (D3)** — inputs are structured JSON only. The problem statement's
  D3 tier wants "highly heterogeneous multimodal input" (e.g. a maintenance-schedule PDF,
  a weather map image). Decide whether you're claiming D3 before investing here — D1/D2
  with strong reliability evidence may be the better scoped target given hackathon time.
- **`BatteryAction` validity isn't cross-checked against `battery.available`** — the
  orchestrator could technically still issue an action against the offline battery in
  `multi_failure_cascade`; add a 7th evaluator rule for this once Step 1/2 research is
  done.
- **No persistence** — every run is stateless/in-memory. Fine for a demo; add a results
  log (even just appending JSON lines to a file) if you want to show historical pass-rate
  trends in the final demo.
- **No auth/rate-limiting** — irrelevant for a local hackathon demo, skip it.

## 4. Before the final submission (per the PDF problem statement)

1. **Working demo** covering every area you claim — script the 3-beat demo narrative from
   ARCHITECTURE.md (bulk auto run → live manual edge case → stripped-objective fallback).
2. **Detailed structural architecture** — ARCHITECTURE.md is the starting draft; update
   the 9-blocker table once you know your actual F/D coverage.
3. **Self-declare your 9-blocker grid position** and make sure the demo evidence backs it
   up exactly — the hackathon explicitly penalizes over- and under-estimation.
