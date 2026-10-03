# Architecture — Renewable Energy Orchestrator

Carried over from the team's working notes (`Hackathon_Renewable_Energy_Orchestrator.docx`).

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

## Dual-agent design

The core decision: separate the agent that makes energy decisions from the agent that
generates the test environment. Every test scenario then has a known, heuristic-grounded
expected outcome to check against — this is what makes results checkable without deep
domain expertise.

### Scenario Agent (Environment Generator) — `backend/app/agents/scenario_agent.py`

- Generates full environment state per tick: solar/wind output, demand, prices, battery
  status, injected events.
- Difficulty profiles: `stable_day` (D1) → `cloudy_afternoon` / `price_spike` (D2) →
  `multi_failure_cascade` (D3).
- Each scenario carries a declared **Primary Objective** as an explicit input
  (`cost_efficiency`, `min_carbon`, `max_reliability`, `max_profit`) — not inferred by the
  orchestrator.
- Each scenario is tagged with an `expected_behavior`, derived from the Learning Guide
  heuristics — hidden from the orchestrator, used only by the Evaluator.
- Two modes: **Auto** (scenario sent directly to orchestrator) and **Manual** (generated
  scenario reviewable/editable before sending).

### Orchestrator Agent (Decision-Maker) — `backend/app/agents/orchestrator_agent.py`

- Receives environment state + declared objective each tick.
- Reasons and acts within the stated objective, rather than guessing at unstated
  priorities.
- Falls back to a hardcoded **Default Priority** (reliability first, cost-efficiency
  second) if no objective is received — explicit, defensible, industry-standard fallback,
  not undefined behavior.
- Logs reasoning per decision via the `reasoning` field on `Decision` — needed for the
  evaluator and the demo narrative.

### Evaluator (Comparison Layer) — `backend/app/agents/evaluator.py` + `backend/app/data/rules.py`

- Runs a universal hard-fail checklist on every decision regardless of objective (the 6
  rules from the Learning Guide, Step 2).
- Compares the decision against the scenario's objective-specific expected behavior.
- Produces pass / fail / flagged per scenario, aggregated into a pass-rate summary — this
  is the evidence for the claimed D-level and F-level position in the final submission.

## Why objective varies per scenario set, not globally

Rather than picking one fixed objective for the whole system (which would require
inventing weights across cost/carbon/reliability/profit without domain grounding), the
objective is declared per scenario as an explicit input. The same environment conditions
can correctly produce different decisions depending on the stated goal — this directly
demonstrates the hackathon's **F2** requirement: "determine optimal cluster of options
after determining optimality criteria given a specific situation."

## Demo narrative

1. **Auto mode, bulk run** — "tested against N generated scenarios, X% pass rate" — proves
   robustness at scale. (`BatchRunPanel` in the frontend.)
2. **Manual mode, live edit** — hand-craft an edge case live in front of judges — proves
   genuine interactivity, not cherry-picked scenarios.
3. **Default fallback** — strip the objective out entirely, show the system falls back
   safely rather than breaking — proves Responsible AI handling. (The "strip objective"
   checkbox in Batch Run does this across many scenarios at once.)

## Mapping to the 9-blocker grid

| | F1 (≥1 action cluster) | F2 (objective-aware optimal set + uncertainty) | F3 (time-series simulation) |
|---|---|---|---|
| **D1** (structured input, acceptable output) | Implemented: scenario → decision → evaluate | Implemented: objective changes the decision for the same state | Not yet — see NEXT_STEPS.md |
| **D2** (structured input, high reliability) | Batch run across `cloudy_afternoon` / `price_spike` | Batch run with mixed objectives + pass-rate | Not yet |
| **D3** (multimodal input, high reliability) | `multi_failure_cascade` profile exists; multimodal input (e.g. weather imagery, PDF maintenance schedules) not yet implemented | Same | Not yet |

Declare your actual self-estimated grid position only once the demo evidence backs it up —
the hackathon penalizes both over- and under-estimation.
