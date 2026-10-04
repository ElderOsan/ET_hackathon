# Round 0 — Tier Report

Dev seed set, base seed `20261004`, 6 difficulties × 4 objectives × 3 reps = **72 scenarios, live Gemini calls, every scenario in the denominator** (no judged_count/agent-only exclusion — that exclusion exists in the stored `BatchRunSummary` schema but was overridden here per explicit instruction). Tiers pre-registered in [`evidence/exit_tiers.json`](../evidence/exit_tiers.json) before this run, same discipline as `evidence/gate.json`. Raw data: [`evidence/round0_benchmark.json`](../evidence/round0_benchmark.json), tier arithmetic: [`evidence/round0_tier_report.json`](../evidence/round0_tier_report.json).

**Tier reached: neither.** Tier A is the closer miss. Nothing was tuned to try to reach a tier — this is the first and only run against these thresholds.

## Each line, number and interval

| # | Item | Tier G needs | Tier A needs | Actual | G | A |
|---|---|---|---|---|---|---|
| 1 | Overall first-attempt pass | ≥80% (58/72) | ≥80% (58/72) | **58/72 = 80.6%** | PASS | PASS |
| 2 | stable+surplus+shortfall first-attempt pass | ≥92% (34/36) | ≥86% (31/36) | **29/36 = 80.6%** | FAIL | FAIL |
| 3 | Non-fail rate (applied) | ≥97% | ≥95% (69/72) | **71/72 = 98.6%** | PASS | PASS |
| 4 | Each objective, all 18 rows, applied passes | ≥12 | ≥11 | cost_efficiency 16, min_carbon 16, max_renewable_utilisation 17, **max_profit 9** | FAIL | FAIL |
| 5 | Avoidable-unserved | <5% | <5% | **1/72 = 1.4%** | PASS | PASS |
| 6a | Safe mode demonstrated | yes | yes | 2 safe-mode rows (tick 49/seed 20301004, tick 66/seed 20311106) | PASS | PASS |
| 6b | Replay matches 72/72 | yes | yes | **70/72** (see below) | FAIL | FAIL |
| 6c | Deterministic suite green | yes | yes | 114/114 pytest + Step 6 suite all green | PASS | PASS |
| 6d | Every non-pass classified | yes | yes | all 14 listed below | PASS | PASS |
| 6e | Zero verdict inconsistencies | yes | yes | **0** (checked over all 72, empty-repair rows) | PASS | PASS |

Line 1 lands exactly on the minimum (58 is the floor, not a cushion). Lines 2, 4, and 6b are genuine misses under both tiers, not boundary rounding.

### Line 6b — why replay is 70/72, not 72/72

The two safe-mode rows (tick 49, tick 66) are where the *original* live call failed and the recorder's `SafeModeRecorder` fell back to the dispatcher. `mode="replay"` deliberately is **not** wrapped in `SafeModeRecorder` (by design — "a replay miss is a real data-availability problem that should surface as one, not be quietly papered over," per `app/api/routes.py:_make_recorder`): there is no successful call to replay for those two scenarios, so replay correctly reports them as `model_call_failed` instead of silently reproducing `safe_mode`. This is the recorder behaving exactly as documented, not a bug — but it does mean the literal "72/72" bar is not met by the current replay design when the original run itself used safe mode. Every other scenario (70/72) replays byte-identical with zero new model calls.

## Per-objective counts

**All 18 rows per objective (applied-stage PASS count):**

| Objective | Passes / 18 |
|---|---|
| cost_efficiency | 16 |
| min_carbon | 16 |
| max_renewable_utilisation | 17 |
| max_profit | **9** |

**Active rule_9 rows only** (rule_9 applicable, i.e. not N/A — cascade deviation has a real reference to compare against):

| Objective | Passes / active rows |
|---|---|
| cost_efficiency | 9/9 |
| min_carbon | 5/6 |
| max_renewable_utilisation | 7/7 |
| max_profit | 9/18 |

max_profit is the only objective with every one of its 18 rows rule_9-active (cost/carbon/renewable objectives have several rows where rule_9 is N/A — a vacuous 0-vs-0 case or similar — leaving fewer "live" comparisons).

## Top two failure classes (14 non-pass rows total)

| Rule | Rows | Share of non-pass |
|---|---|---|
| **rule_9** (cascade deviation) | **9** | 64% |
| rule_5 / rule_8b (tied) | 4 each | 29% each |
| rule_3 (unserved, the one true FAIL) | 1 | 7% |
| rule_8c | 1 (co-occurs with rule_8b on tick 66) | 7% |

**#1 — rule_9, 9/9 under `max_profit`, all `agent` mode.** Every single rule_9 failure in this run is a `max_profit` scenario where the model's net profit (including the new Addendum C stored-energy value term) falls well short of the dispatcher's own reference profit — e.g. tick 10 (stable_day): actual $119 vs reference $520; tick 58 (surplus_day): actual $1206 vs reference $1628. This is the first live test of the new profit formula and prompt sentence; the model is not yet reliably exploiting it. This single pattern also explains most of line 2's shortfall: 6 of the 7 non-pass rows inside the stable+surplus+shortfall subset are these same max_profit/rule_9 rows (3 stable_day + 3 surplus_day).

**#2 (tied) — rule_5, 4 rows, all `price_spike`, all `agent` mode.** The live model charges the battery at a price peak using fully *sellable* surplus instead of selling it (e.g. tick 27: charging 15.8MW when all of it was sellable at $246/MWh) — the same mistake pattern Step 6 found in the **dispatcher's own** reference logic for price-spike days (see `evidence/step6_evidence.json` and the Step 6 commit). Worth noting as a pre-existing, now twice-confirmed gap, not something introduced by the live run.

**#2 (tied) — rule_8b, 4 rows.** Two different root causes bundled under one rule: 3 rows (ticks 28, 31, 34, all `agent` mode) are the model proposing a floor outside the scenario's expected volatility band — a genuine model floor-calibration miss. 1 row (tick 66, `safe_mode`) is the **dispatcher's** own state-vs-profile volatility mismatch, the same pre-existing gap Step 6 identified for `shortfall_day` (33/200 in the oracle run) — here it surfaced live because that scenario fell back to safe mode.

**The one true FAIL:** tick 38 (multi_failure_cascade, cost_efficiency) — rule_3, 3.7MW unserved that was achievable. A genuine model reliability mistake, not a rule or infrastructure issue.

## Full non-pass list (all 14)

| Tick | Seed | Profile | Objective | Status | Mode | Failing rule(s) |
|---|---|---|---|---|---|---|
| 10 | 20261304 | stable_day | max_profit | flagged | agent | rule_9 |
| 11 | 20261305 | stable_day | max_profit | flagged | agent | rule_9 |
| 12 | 20261306 | stable_day | max_profit | flagged | agent | rule_9 |
| 27 | 20281006 | price_spike | cost_efficiency | flagged | agent | rule_5 |
| 28 | 20281104 | price_spike | min_carbon | flagged | agent | rule_8b |
| 31 | 20281204 | price_spike | max_renewable_utilisation | flagged | agent | rule_8b |
| 34 | 20281304 | price_spike | max_profit | flagged | agent | rule_5, rule_8b, rule_9 |
| 35 | 20281305 | price_spike | max_profit | flagged | agent | rule_5, rule_9 |
| 36 | 20281306 | price_spike | max_profit | flagged | agent | rule_5, rule_9 |
| 38 | 20291005 | multi_failure_cascade | cost_efficiency | **FAIL** | agent | rule_3 |
| 58 | 20301304 | surplus_day | max_profit | flagged | agent | rule_9 |
| 59 | 20301305 | surplus_day | max_profit | flagged | agent | rule_9 |
| 60 | 20301306 | surplus_day | max_profit | flagged | agent | rule_9 |
| 66 | 20311106 | shortfall_day | min_carbon | flagged | safe_mode | rule_8b, rule_8c |

## Bottom line

Neither Tier G nor Tier A is met. The gap is concentrated, not diffuse: `max_profit` alone accounts for 9 of 14 non-pass rows (all rule_9), which is also the sole reason line 4 fails and the dominant reason line 2 falls short. rule_5 and rule_8b (4 rows each) are smaller, already-known patterns (both independently confirmed by Step 6's deterministic suite against the dispatcher, not new to this run). The single hard FAIL (rule_3, tick 38) is an isolated model mistake, not a systemic issue. No rule, threshold, or prompt was changed to influence this outcome.
