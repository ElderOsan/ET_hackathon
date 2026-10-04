# Next Steps

*Last updated 2026-10-04, after Brief 2 (physical layer) + the Brief 2 Patch (calibration,
balancer unwind-order fix, raw+applied scoreboard). See git log for the full history —
every step has its own commit with a detailed message.*

## 0. Setup (done)

Python, Node, and Git are installed. The project is now a git repo (`git init` done as
Brief 2 Patch Step 0) — `backend/.env` is gitignored, never commit it. Follow the setup
steps in [README.md](README.md). Get your free Gemini API key (from
[aistudio.google.com](https://aistudio.google.com)) into `backend/.env` before the backend
will start.

## 1. Domain grounding (Learning Guide Steps 1–5)

Still the right background reading before touching the rule thresholds further — the
physical layer fixes (Brief 2) made the rules internally *consistent*, not necessarily
*correctly calibrated* against real grid-operator judgment. `backend/app/data/tuning.py`
collects every tunable number in one place for exactly this kind of revisit.

## 2. Current benchmark (dev seed set, 2026-10-04)

Partial run (free-tier quota cut it off at 16/24 scenarios — `surplus_day`/`shortfall_day`
still need a full pass): **0 failures, 0 infeasible scenarios, 25% clean pass rate, 12/16
flagged**. This is a dramatic change from the pre-patch baseline (13/16 failed on `rule_3`
alone) — the Evaluator is now catching real issues without the false positives that came
from inconsistent demand/transmission definitions. Artifacts: `brief2_after_run.json` (old
baseline), `brief2_patch_benchmark.json` + `brief2_patch_gapfill.json` (current).

**To reproduce:** `POST /api/benchmark/run` (dev set) from the running backend, or call
`app.agents.scenario_agent.generate_scenario` / `app.agents.pipeline.run_decision_pipeline`
directly in a script — see `backend/tests/test_acceptance.py` for patterns.

## 3. Known gaps / stubs to close before submission

- **Free-tier rate limiting makes a full 24-scenario benchmark hard in one sitting.**
  15 req/min means a full-matrix run needs either patience (wait between batches) or a
  paid key for the final demo/evidence pack.
- **`rule_5` daily-high threshold** (`backend/app/data/rules.py::_daily_high_threshold`) is
  still a placeholder (`price * 0.95` or `price + 1`) — flagged 3/4 `price_spike` scenarios
  in the last run. Worth a proper look alongside the Learning Guide research.
- **`rule_9` under `max_profit`** flagged both scenarios that ran in the last benchmark —
  a genuine minor decision-quality gap (the model isn't always selling optimally for
  profit), not a calibration bug as far as the evidence shows so far.
- **No time-series simulation (F3)** — scenarios are still single independent ticks.
  `app/agents/scenario_agent.py`'s forecast horizon is a single next-tick snapshot, not a
  rolling simulation.
- **No multimodal input (D3)** — inputs are structured JSON only.
- **No persistence** — every run is stateless/in-memory; the two JSON benchmark artifacts
  in the repo root are the only durable record right now.
- **No auth/rate-limiting on the API itself** — irrelevant for a local hackathon demo.

### Resolved since the last version of this doc

Demand ambiguity, transmission definition, the balancer not existing, rule_3/rule_4
disagreeing, rule_9 not checking curtailment, `expected_emergency` from a hardcoded
profile, the evaluator's severity-pill-reads-as-fail display bug, no raw-vs-applied
scoring, random (non-reproducible) scenarios, a randomly-varying fleet, and the
`cloudy_afternoon` floor-band miscalibration are all fixed — see git log for Brief 2 and
the Brief 2 Patch commits.

## 4. Brief 3 (on hold — do not start without explicit approval)

Demand response as a quantified amount (not yes/no), a forecast horizon with uncertainty,
a preflight tool-use loop (`simulate_decision`) so the Orchestrator can check its own
arithmetic before committing, safe mode for API outages, and a repeatability runner for
consistency evidence. This was explicitly paused mid-Brief-2-Patch and hasn't resumed.

## 5. Before the final submission (per the PDF problem statement)

1. **Working demo** covering every area you claim — the architecture doc's 3-beat demo
   narrative (bulk auto run → live manual edge case → stripped-objective fallback) still
   applies; consider adding "first-attempt vs. applied pass rate" as a 4th beat now that
   it exists.
2. **Detailed structural architecture** — [ARCHITECTURE.md](ARCHITECTURE.md) needs a
   refresh for the physics module, balancer, and raw+applied scoring (not yet done as of
   this note).
3. **Self-declare your 9-blocker grid position** and make sure the demo evidence backs it
   up exactly.
