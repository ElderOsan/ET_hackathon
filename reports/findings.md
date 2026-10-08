# Findings

What we learned building and measuring this system. Written after the final benchmark (`evidence/round1_benchmark.json`, commit `6fa01ec`) and before the submission freeze.

Every number below names the file it came from. Four different datasets in this project happen to read 83.3%, which is exactly why.

---

## 1. The agent states the correct action and then submits a different one

Round1, tick 35. A surplus state, objective `max_profit`. The model's own reasoning text:

> "...under max_profit, sell to grid before charging battery... So we sell 1.6 MW to the grid and charge 0 MW."

The decision it then submitted: **charge 1.6 MW, market action hold.**

It names the rule. It states the correct action. It submits the opposite.

This is not an isolated parse error. We confirmed the same shape twice in round1:

| Where | What the reasoning said | What was submitted |
|---|---|---|
| Round1 tick 35 (`round1_benchmark.json`) | sell 1.6 MW, charge 0 | charge 1.6 MW, hold |
| Round1 tick 38 (`round1_benchmark.json`) | "Remaining shortfall (3.7 MW) handled via emergency reserve discharge." | battery_1 discharges 4.5 MW (its ordinary rate, not an emergency one) and buys 2.0 MW; nothing discharges below the floor; 3.7 MW stays unserved |

A third, differently-described case was in an earlier draft of this document (a "D.0 shortfall
sanity check" and "earlier smoke runs" row) but neither traced to a stored file when checked
against source for this version — cut rather than kept on memory alone. The two rows above
are the only instances this document claims.

Ticks 34 and 36 are a softer variant: they name the sell-first rule correctly, then rationalise charging anyway by treating `surplus_after_max_charge_mw` as permission to charge first rather than as a description of what remains after selling.

**Why this matters more than the pass rate.** A system that reasons wrongly can be corrected by better instructions. A system that reasons correctly and acts differently cannot — the instruction is already there and already understood. Every fix we considered for these rows was a fix to what the model is *told*, and tick 35 is evidence that telling it more may not be the lever.

It is also the reason we declined one of the two changes that would have improved our benchmark score. See section 5.

---

## 2. A model-information gap: the evaluator scores against powers the model is not told it has

**One confirmed instance: round1 tick 38** (`multi_failure_cascade`, `cost_efficiency`, seed 20291005). Reproduced identically in `round0_run2_benchmark.json` under a different `prompt_version`, which rules out sampling noise.

The arithmetic:

- Demand 134.7 MW. Generation 124.5 MW.
- Facts the model was given: `discharge_available_mw` 4.5 (battery 1) + 0.0 (battery 2, offline), `max_import_mw` 2.0.
- It proposed exactly that: discharge 4.5, buy 2.0. Total supply 131.0 MW. **3.7 MW unserved.**
- `rule_3`'s benchmark, `min_achievable_unserved_mw`, computes **0.0** — because battery 1's emergency ceiling, discharging to its minimum safe charge rather than to the reserve floor, is 10.0 MW. More than enough.

The model is told, in prose, that it may discharge below the floor in a genuine emergency. It is never given a *number* for how much that is. The capability fact it does receive is computed against `previous_floor_pct` — last tick's floor, not the one it is about to propose — so it can be stale relative to the model's own decision in the same interval.

**We chose not to fix this.** Section 5.

---

## 3. A balancer-repair gap: capped actions leave load standing with capacity unused

Distinct from section 2, with a different actor and a different fix. **Four independent confirmations.**

Round1 ticks 16 and 20 (`cloudy_afternoon`, `min_carbon` and `max_renewable_utilisation`) are the cleanest. Both:

- proposed a battery discharge above the hardware rate limit (7.9 and 8.9 MW against a 6.0 MW limit),
- were correctly capped by the balancer to 6.0 MW,
- left 1.9 and 2.9 MW of load unserved,
- **with 180 MW of transmission headroom entirely unused.**

The balancer caps an illegal action and never substitutes available grid import to cover the resulting gap. Neither row was an emergency; import alone would have closed both.

The same mechanism appears in the earlier `price_spike` and `multi_failure_cascade` smoke findings and in the 96-row day's row 40.

**Consequence for the benchmark:** both rows pass at the raw stage and fail at the applied stage. The repair creates the failure.

---

## 4. The agent does not outperform the deterministic dispatcher it was built alongside

Source: `evidence/dispatcher_vs_round1_head_to_head.json`. The dispatcher was run over round1's *identical* 72 scenarios and scored by the same evaluator, with no model calls.

| | Raw / first attempt | Applied (after repair) |
|---|---|---|
| Dispatcher | 59 pass / 13 flagged / 0 fail — 81.9% | identical; 0 of 72 needed repair |
| Agent (round1) | 61 pass — 84.7% | 59 pass / 9 flagged / 3 fail — 81.9% |

The agent leads before repair, ties after, and produces three hard failures the dispatcher never produces.

Two things make the result informative rather than merely negative.

**The composition differs.** The agent has *fewer* flags (9 against 13) and *more* fails (3 against 0). It trades minor cascade deviations for occasional hard failures — a real characterisation of LLM-versus-deterministic behaviour on this task, and more useful than either headline number.

**The entire deficit is two named defects.** The agent's three applied failures are exactly ticks 16, 20 and 38 — sections 2 and 3 above. Not general unreliability.

The dispatcher is also feasible by construction, which is why it needs no repairs. "Ties after repair" partly measures that the agent requires a repair stage the dispatcher does not.

We are publishing this because a judge can compute it from data we are already shipping. Finding it ourselves and stating it is the only defensible option.

---

## 5. What we declined to change, and why

Every item here would have improved a number. The gate criteria in `evidence/gate.json` and the tier definitions in `evidence/exit_tiers.json` were committed *before* the benchmark ran, which is what makes this list meaningful.

| Change | Why we declined it |
|---|---|
| Give the model its emergency-discharge headroom as a fact (section 2) | Roughly 2–3 hours and 72 live calls for a bounded 1.4-point gain on a metric already clearing its gate line. The one affected row sits outside the three-profile gate criterion, so it moves nothing that is actually gated. And section 1 is a specific reason to doubt that another number would change the behaviour. |
| Narrow `rule_3`'s benchmark to the facts the model was given | It would have made tick 38 pass — a row that genuinely left 3.7 MW of critical load unserved with 10.0 MW of permitted discharge unused. The rule is correct; the measurement would have become wrong in the lenient direction. |
| Move the 92% three-profile threshold | Pre-registered. That is the entire point of having committed it. |
| Re-run the single scenario lost to a rate-limit 429, completing the recording | Defensible in isolation: a rate-limited call is a missing observation, not a measurement. Declined because the decision would have been made *knowing* it was the one thing between us and Tier A. That contamination is what pre-registration exists to prevent. |
| Take the looser reading of the "replay matches 72/72" criterion | The criterion is genuinely ambiguous, and the looser reading — that replay reproduces every scenario's live verdict, which it does — would have reached Tier A. Declined: the tiers are our own framework, the label buys nothing externally, and arguing a second favourable interpretation would cost more credibility than the label is worth. |

**Outcome: neither Tier G nor Tier A reached.** Tier A clears every quantitative criterion and misses only on the replay item. Tier G misses that plus the three-profile line, by exactly one row — and 92% is not an attainable score on a 36-row denominator at all: 33/36 is 91.7%, 34/36 is 94.4%, and nothing lands between them. That is context for the miss, not grounds for treating it as met.

---

## 6. Things the measurement apparatus caught that review did not

Each of these was found by an automated check, not by reading code.

- **A replay path that silently reported the agent as failing.** The shipped 96-row recorded day missed its cache on all 96 rows after a prompt change, and the pipeline rendered this as "0 of 96 passed" — indistinguishable from catastrophic agent failure. A judge clicking the first door would have concluded the agent was broken. Now a cache miss is a distinct, named outcome.
- **An evaluator check that could never fire.** `_daily_high_threshold()` returned `price + 1` for any scenario not carrying the generator's `price_spike` tag — a threshold unreachable by construction, which made the price branch dead for every file-input row and left `rule_5` structurally inert on that whole class.
- **A day report that reused frozen verdicts.** `day_report_build.py` read each row's stored `evaluation` instead of re-scoring under current rules, so a "freshly built" report could carry verdicts from code that no longer existed. Found by accident, during a task whose only purpose was regenerating that file.
- **An unreachable branch in the balancer's shortfall unwind**, found while writing the test that was supposed to guard it.

Three of the four were found by tests or checks written for a different purpose.

---

## 7. Method notes

**Batching prompt changes cost us attribution.** Commit `678c109` bundled two new physics facts with the dispatch-ladder rewording, to invalidate the recordings only once instead of twice. That saved a re-record and destroyed the ability to credit either change: tick 60's clean before-and-after (charge 16.0/sell 34.9 becoming charge 0/sell 50.9 on an identical scenario) is attributable to the commit as a whole and to neither half individually. For a project whose purpose is measuring what changes behaviour, that was the wrong trade. One change per `prompt_version`.

**A single probe is not a measurement.** The ladder rewording showed 3 of 3 on one hand-built seed. Across round1's real surplus-state `max_profit` rows it moved 1 of 9 — against 0 of 9 before. Real and causal, and far more partial than the probe suggested.

**Pre-registration only works if the run count is fixed in advance.** We committed to running the final benchmark once and investigating by re-scoring stored decisions at zero cost. Every finding in sections 1 to 4 came out of zero-call re-scoring.

---

## 8. Known issues, not fixed

- `GENERATED_DIFFICULTY_COUNT = 6` is duplicated in `BatchRunPanel.jsx` and will drift from `GENERATED_DIFFICULTIES` if that list changes. Affects an estimate label only.
- The embedded evaluator panel inside batch rows keeps its own "3. Evaluator" heading, which reads oddly nested.
- The charge-unwind branch in the balancer's Phase A shortfall loop is unreachable under current surplus-cap logic. Read, documented, not fixed.
- `orchestrator_facts()` is computed against `previous_floor_pct`, so the discharge capability figure can be stale relative to the floor proposed in the same interval. Architectural, and the proximate cause of section 2.
- Re-recording under an existing `run_id` does not clear the previous files. Both 96-row directories briefly held 192 files each.
- **The objective cascade is specified as a three-level priority ordering but only the top priority is scored.** The design table (cost → carbon → renewable utilisation, etc.) names a second and third priority for every objective, but `rule_9` — the only rule that scores cascade adherence — checks the declared objective's top priority against a 5% tolerance band and nothing else. No rule evaluates, selects among, or enforces anything about the second or third priority. The lower levels are design intent, not implemented behaviour.

Metric boundaries are documented separately in `reports/metric_limitations.md` — in particular, the profit metric values stored energy at the *current* sell price, so it can never reward storing for a later higher price, and `max_profit` can therefore only ever prefer selling. The objective-cascade divergence we measured (30 of 31 constructed surplus states, `evidence/baseline_divergence_probe.json`) is bounded by the round-trip charge loss: 0.35 MWh × $24.04 = $8.41.
