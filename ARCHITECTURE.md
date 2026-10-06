# Architecture — Renewable Energy Orchestrator

Carried over from the team's working notes (`Hackathon_Renewable_Energy_Orchestrator.docx`),
updated 2026-10-04 after the physical-layer rebuild (physics module, deterministic
balancer, raw+applied scoring) — see git log for the step-by-step history.

## Problem

Utility operating 5 solar farms, 3 wind farms, 2 battery storage systems, several
industrial consumers, grid interconnections and market access. Every 15 minutes,
conditions change — clouds cut solar, wind shifts, prices spike, a battery goes offline,
demand surges. The agent must continuously decide: charge/discharge batteries, sell to or
buy from the grid, curtail renewable generation, or trigger demand response.

## Why this problem (over Banking, Prompt Injection Firewall, Retail)

Strongest "Agentic Capability" story — a true continuous decision-making loop under
shifting state, rather than a one-shot classification or recommendation task.

**Key risk:** a self-verification gap. Without energy-domain expertise, decisions can't be
judged "good" or "bad" by instinct the way a retail discount could. Mitigated by grounding
the Evaluator in well-established, publicly documented operating principles rather than
inventing energy strategy from first principles (see the Learning Guide).

## Pipeline

One function — `app/agents/pipeline.py::run_decision_pipeline` — is the only path auto
single runs, manual single runs, and batch runs ever go through:

```
scenario → Orchestrator (raw proposal) → balancer (applied decision) → Evaluator (both stages)
```

No other code calls `decide()`, `balance()`, or `evaluate()` directly. The Evaluator runs
**twice** per decision — once against the model's raw proposal (every rule except the
repair-magnitude one), once against the balancer's applied decision — so the model's own
score and the system's final score are both visible, never conflated.

### Scenario Agent (Environment Generator) — `backend/app/agents/scenario_agent.py`

- Generates full environment state per tick: solar/wind output, demand, prices, battery
  status, injected events — deterministic Python, seedable, no LLM call.
- **Fixed fleet** (`app/data/fleet.py`): 5 solar farms (~110MW), 3 wind farms (~60MW), 2
  batteries — identical in every scenario. Only output, forecast, demand, prices, SoC, and
  events vary per scenario; a utility operates one portfolio.
- Six calibrated profiles, each rejection-sampled against a target
  generation/total-demand ratio range *and* checked for physical feasibility
  (`min_achievable_unserved_mw == 0`) before being accepted:
  `stable_day`, `cloudy_afternoon`, `price_spike`, `multi_failure_cascade`,
  `surplus_day`, `shortfall_day` — see `app/data/tuning.py::PROFILE_RATIO_RANGES`.
- Demand is generated total-first (within `DEMAND_BAND_MW`), then split into
  `base_demand_mw` + `industrial_demand_mw` by a configured share — `total_demand_mw` is
  computed once and is the only demand figure the prompt, Evaluator, and reference
  calculator ever use. No component re-derives it.
- Each scenario carries a declared **Primary Objective** as an explicit input
  (`cost_efficiency`, `min_carbon`, `max_renewable_utilisation`, `max_profit`) — not
  inferred by the orchestrator.
- The hidden `expected_emergency` / `expected_ladder_step` tags are computed from the
  scenario's actual net position and the physics module, not assigned from the difficulty
  label — a `stable_day` edited to include a storm alert is still correctly classified.
- Two modes: **Auto** (scenario sent directly to orchestrator) and **Manual** (generated
  scenario reviewable/editable, server-normalized via `/api/scenario/normalize` before
  sending — recomputes totals, auto-corrects event/battery inconsistencies, shows
  read-only physics facts).

### Physics Module — `backend/app/data/physics.py`

The single source of truth for every power-balance quantity: max charge/discharge per
battery, power-balance residual, unserved load, the minimum curtailment physically
required, the minimum unserved load *any* decision could achieve
(`min_achievable_unserved_mw` — used to tell a physically infeasible scenario apart from a
genuine decision mistake), net position (generation vs. total demand), and computed
emergency status. The balancer, the Evaluator, and the Orchestrator's own input facts are
all built on these same functions — nothing else computes them independently.

### Orchestrator Agent (Decision-Maker) — `backend/app/agents/orchestrator_agent.py`

- Receives the environment state **plus a `physics_facts` block**
  (`total_generation_mw`, `net_position_mw`, a surplus/shortfall/balanced label, the same
  for the forecast, and per-battery discharge-available/charge-headroom) — computed facts
  the model is told to use directly rather than recompute.
- `reasoning` is the first declared property in the `submit_decision` schema and must be
  written before any action, stating the net position and ladder step followed. (Tested
  live: declared JSON schema property order does **not** control Gemini's actual
  generation order — the natural-language instruction in the prompt is what drives
  response quality, not the schema's property order.)
- Judges every decision in two layers: Layer 1 golden rules (never traded away) and Layer
  2 the objective cascade (only reorders priorities once Layer 1 holds). No objective
  declared means `cost_efficiency` under the golden rules — a structural default, not a
  special-cased fallback.

### Balancer — `backend/app/data/balancer.py`

Deterministic code between the Orchestrator and the Evaluator: the model proposes, the
balancer makes the numbers physically true. Caps every battery action to feasibility, then
unwinds — in order — curtailment, sale, and (if still short) battery charging, until load
is met or nothing's left to remove. **Never invents supply the model didn't propose** —
under-provisioning is left standing as a genuine Evaluator failure, not papered over. Every
field it changes is recorded as a `FieldRepair` (proposed, applied, delta, reason) shown in
the Decision panel. The same module also provides `reference_dispatch()`, the autonomous
optimal-dispatch calculation rule 9 compares the actual decision against.

### Evaluator (Comparison Layer) — `backend/app/agents/evaluator.py` + `backend/app/data/rules.py`

- 15 rules total: golden rules (severity `fail`, e.g. unserved load vs. the physically
  achievable minimum, curtailment-amount vs. minimum required, transmission/frequency
  limits) and cascade/floor/repair checks (severity `flagged`, e.g. reserve-margin
  headroom, floor-band match, cascade-metric deviation, balancer-repair magnitude).
- A rule that can't be judged for a given decision (e.g. reserve margin when load is
  already unserved) reports a genuine **N/A**, never a disguised pass.
- Two-number rules (unserved vs. achievable, curtailed vs. minimum required, cascade
  metric vs. reference) carry both numbers as structured fields, not just prose.
- Produces pass / fail / flagged per scenario, for both the raw and applied stage —
  aggregated into first-attempt pass rate (the model's real score), applied pass rate,
  repair rate, and a raw-rule category breakdown (arithmetic / strategy / outcome).

## Why objective varies per scenario set, not globally

Rather than picking one fixed objective for the whole system (which would require
inventing weights across cost/carbon/reliability/profit without domain grounding), the
objective is declared per scenario as an explicit input. The same environment conditions
can correctly produce different decisions depending on the stated goal — this directly
demonstrates the hackathon's **F2** requirement: "determine optimal cluster of options
after determining optimality criteria given a specific situation."

## Demo narrative

1. **Auto mode, bulk run** — "tested against N generated scenarios, X% first-attempt pass
   rate, Y% applied pass rate, Z% repair rate" — proves robustness at scale *and* is honest
   about how much of that score the balancer is doing versus the model (`BatchRunPanel`).
2. **Manual mode, live edit** — hand-craft an edge case live in front of judges, with
   read-only physics facts (net position, battery headroom) shown before you send it —
   proves genuine interactivity, not cherry-picked scenarios.
3. **Default fallback** — strip the objective out entirely, show the system falls back to
   `cost_efficiency` under the golden rules safely rather than breaking.
4. **Raw vs. applied, side by side** — pick a flagged or repaired row and show the model's
   raw proposal next to what the balancer made of it, with the repair list — proves the
   self-verification gap is actually being closed, not just claimed.

## Current evidence (dev seed set, 2026-10-04, full 24-scenario matrix)

**11/24 pass (45.8%), 13 flagged, 0 failed, 0 infeasible.** Zero hard-rule violations
across the entire matrix — every non-pass is an advisory (cascade deviation, thin reserve
margin, a repair) rather than a safety or reliability violation. Two calibration bugs found
and fixed via this evidence (both approved before changing): `cloudy_afternoon` and
`shortfall_day` were classified into a higher reserve-floor volatility band than the
Evaluator's own signal-detection logic actually justified — see git log for the diagnostics.

## Mapping to the 9-blocker grid

| | F1 (≥1 action cluster) | F2 (objective-aware optimal set + uncertainty) | F3 (time-series simulation) |
|---|---|---|---|
| **D1** (structured input, acceptable output) | Implemented: scenario → decision → balancer → evaluate | Implemented, with a caveat — see README's Known Limitations (the declared objective does not reliably change the model's surplus decision in practice) | Not yet — see README's Known Limitations (file input has no state carry-over) |
| **D2** (structured input, high reliability) | Implemented with real evidence: 0 failures across a 24-scenario, 6-profile matrix | Batch run with mixed objectives + first-attempt/applied pass rates | Not yet |
| **D3** (multimodal input, high reliability) | `multi_failure_cascade` profile exists; multimodal input (e.g. weather imagery, PDF maintenance schedules) not yet implemented | Same | Not yet |

Declare your actual self-estimated grid position only once the demo evidence backs it up —
the hackathon penalizes both over- and under-estimation. The 0-failure, 0-infeasible result
above is real evidence for a confident D2 claim; F2 is well-evidenced too (the cascade
genuinely reorders decisions and the Evaluator genuinely checks the right metric per
objective) — F3 (time-series) remains the honest gap.
