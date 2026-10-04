# Step Report: Patch 3, Step 1 (reporting fix + diagnosis)

## A. Identity

- **Step name:** Patch 3, Step 1
- **Git commit hash:** `0b725fd`
- **Working tree:** clean
- **Date/time:** 2026-10-04
- **Model:** `gemini-3.5-flash-lite`, temperature unset (SDK default) — this benchmark data is unchanged from the original Step 6 run (no new API calls this step).

## B. What changed

**Files:** `backend/app/api/routes.py`, `backend/app/agents/pipeline.py`, `backend/app/agents/orchestrator_agent.py`, `backend/app/data/tuning.py`, `backend/app/models/schemas.py`, `backend/tests/test_acceptance.py`, `backend/tests/test_resilience.py` (new), plus regenerated `brief2_patch2_benchmark.json` / `evidence/patch2_runs.jsonl` / `evidence/patch2_summary.csv`.

**Config added** (`tuning.py`): `GEMINI_RETRY_ATTEMPTS = 5`, `GEMINI_RETRY_MAX_WAIT_S = 20.0` (previously hardcoded in the `tenacity` decorator, now named CONFIG).

**Schema changes:** `Decision.mode` (`"agent"` default / `"model_call_failed"` / `"parse_failed"`) + `failure_detail`; `BatchRunSummary.na_count` removed, replaced by `na_counts_by_rule: dict[str,int]` (informational) and `judged_count`; added `unresolved`/`unresolved_count`.

## C. Tests

| Group | Run | Passed | Failed |
|---|---|---|---|
| `test_acceptance.py` | 22 | 22 | 0 |
| `test_calibration.py` | 31 | 31 | 0 |
| `test_resilience.py` (new) | 7 | 7 | 0 |
| **Total** | **60** | **60** | **0** |

## D. Runs

No new API calls this step. The Step 6 benchmark (72 scenarios, dev seed 20261004, 3 passes pooled, raw+applied) was re-summarized from its stored per-row results under the corrected denominator logic.

## E. Results — corrected gate table (all 72 scenarios, 95% Wilson CI)

| Gate item | Threshold | Was reported (broken) | **Corrected** | Met? |
|---|---|---|---|---|
| Overall first-attempt pass | ≥80% | 53.8% (21/39) | **75.0% (54/72), CI (63.9%, 83.6%)** | No — but CI overlaps the threshold (amber, not clean red) |
| Stable/surplus/shortfall pass | ≥92% | 47.6% (10/21) | **69.4% (25/36), CI (53.1%, 82.0%)** | No — CI doesn't reach 92% |
| Avoidable-unserved | <5% | 1.4% (1/72) | 1.4% (1/72), unchanged | Yes |
| Safe mode | demonstrated | not built | not built | No (Step 4 of this patch, not done yet) |
| Unexplained failures | none | — | none — 18/18 non-pass rows classified below | Yes |

**Non-fail rate:** 97.2% (70/72), CI (90.4%, 99.2%).

Per-profile (applied, all 12 judged each):
| Profile | Rate | CI |
|---|---|---|
| stable_day | 75.0% (9/12) | (46.8%, 91.1%) |
| cloudy_afternoon | 91.7% (11/12) | (64.6%, 98.5%) |
| price_spike | 58.3% (7/12) | (32.0%, 80.7%) |
| multi_failure_cascade | 91.7% (11/12) | (64.6%, 98.5%) |
| surplus_day | 66.7% (8/12) | (39.1%, 86.2%) |
| shortfall_day | 66.7% (8/12) | (39.1%, 86.2%) |

Per-objective:
| Objective | Rate | CI |
|---|---|---|
| cost_efficiency | 83.3% (15/18) | (60.8%, 94.2%) |
| min_carbon | 94.4% (17/18) | (74.2%, 99.0%) |
| max_renewable_utilisation | 88.9% (16/18) | (67.2%, 96.9%) |
| **max_profit** | **33.3% (6/18)** | (16.3%, 56.3%) |

Per-rule N/A counts (applied stage, informational, no longer subtracted from anything): `rule_9` 35, `rule_5` 36, `rule_3b` 1.

**Checklist items:**
- Consistency violations (empty repair log, raw≠applied status): **0**.
- Vacuous-PASS count (all rules N/A): **0**.
- Tick 1 / tick 60 margin: both reproduce `max_achievable_headroom_mw` = 0.2MW / 1.6MW exactly (verified in Patch 2 Step 1 acceptance tests, unaffected by this step).
- Row 49 root cause (plain words): the batch's "Repaired" column was computed from total repair *magnitude* above a 0.5MW tolerance, not from whether a repair happened at all. A repair as small as 0.2MW — easily enough to tip `rule_3` from pass to fail — showed as "Repaired: no," making the verdict change look unexplained when it wasn't. Fixed in Patch 2 Step 4 (`repaired = len(repairs) > 0`).

## The 35 scenarios, explained

All 35 scenarios originally excluded share **one reason code**: `rule_9 N/A was used to exclude the whole scenario` (Patch 2's since-reversed logic). **Zero** were model-call or parse failures — no such failures occurred in this historical run. Recovering their true verdicts (from their non-N/A rules, which `evaluate()` always computed correctly — only the batch *summary* ignored them): **all 33 of the scenarios still excluded as of my last report were genuine PASSes** (2 had already been fixed back in by the interim vacuous-pass fix, bringing 35→33 before this step's full fix brought it to 0 excluded). This exactly matches your own back-of-envelope estimate: stable+surplus+shortfall lands at precisely 25/36 = 69.4%, the same number you calculated as the "if all 35 had passed" upper bound.

## F. Non-pass catalogue (18 of 72, applied stage) — category counts

**strategy: 18, arithmetic: 2** (a row can carry both). Zero rows are uncategorized or unexplained.

| tick | seed | profile | objective | verdict | category |
|---|---|---|---|---|---|
| 10,11,12 | 2026130x | stable_day | max_profit | flagged | strategy (rule_9) |
| 24 | 20271306 | cloudy_afternoon | max_profit | flagged | strategy (rule_9) |
| 27 | 20281006 | price_spike | cost_efficiency | flagged | strategy (rule_5) |
| 32 | 20281205 | price_spike | max_renewable_utilisation | flagged | strategy (rule_8b) |
| 34,35,36 | 2028130x | price_spike | max_profit | flagged | strategy (rule_5+rule_9) |
| **38** | 20291005 | multi_failure_cascade | cost_efficiency | **fail** | arithmetic+strategy (rule_3, over-imported past transmission headroom) |
| **55** | 20301204 | surplus_day | max_renewable_utilisation | **fail** | arithmetic+strategy (rule_6, unforced curtailment with 180MW free headroom) |
| 58,59,60 | 2030130x | surplus_day | max_profit | flagged | strategy (rule_9) |
| 63 | 20311006 | shortfall_day | cost_efficiency | flagged | strategy (rule_2b+rule_9) |
| 64 | 20311104 | shortfall_day | min_carbon | flagged | strategy (rule_9) |
| 70,71 | 2031130x | shortfall_day | max_profit | flagged | strategy (rule_2b+rule_9) |

## Regression diagnosis (report only — per Step 1, waiting before any A/B)

Within stable/surplus/shortfall specifically: rule frequency among non-passes is `rule_9` ×11, `rule_2b` ×2, `rule_6` ×1, `rule_10` ×1. **Yes — it's overwhelmingly `rule_9`, and within that, overwhelmingly `max_profit`:** 8 of the 11 `rule_9` hits in these three profiles are `max_profit` scenarios (the other 3 split across `cost_efficiency`, `min_carbon`, `max_renewable_utilisation`, one each). Combined with the per-objective table above (`max_profit` 33.3% vs. 83–94% for every other objective), this is a real, consistent pattern, not noise — and it's the same objective whose scoring mechanism Patch 2 Step 2 changed (buy/sell prices, real profit netting).

This points at the buy/sell price change as specified in your conditional. **Proposing, not running:** an A/B of `PRICE_SPREAD_PCT` 0% vs. 5% on the 12 stable/surplus/shortfall scenarios, 3 passes (~72 live calls). Waiting for your approval before spending that quota.

## G. Deviations and assumptions

- "Vacuous-PASS" (not explicitly defined in the brief) was operationalized as: a PASS where *every* rule on the row is N/A — a stricter, more defensible bar than "rule_9 alone is N/A," since a PASS driven by other rules genuinely passing isn't vacuous. Count: 0.
- The retry-transient check now also catches bare `TimeoutError`/`ConnectionError` in addition to the brief's named 503/429 — a reasonable reading of "timeout, network," not separately itemized in the brief.

## H. Known issues (not fixed this step)

- Gate items 1 and 2 are still not met — 75.0% and 69.4% against 80%/92%. Item 1's confidence interval overlaps the threshold; item 2's does not.
- Safe mode (gate item) isn't built — that's this patch's Step 4.
- No record/replay infrastructure yet — that's Step 2. This step's "replay" was really "re-summarize already-evaluated stored results," not a replay of model calls (there's nothing to replay against yet).
- The regression's root cause (rule_9 on max_profit) is diagnosed but not fixed — waiting on your A/B approval before touching `PRICE_SPREAD_PCT` or anything else.

## I. Raw data

- [evidence/patch2_runs.jsonl](../evidence/patch2_runs.jsonl), [evidence/patch2_summary.csv](../evidence/patch2_summary.csv), [brief2_patch2_benchmark.json](../brief2_patch2_benchmark.json) — all regenerated this step, same 72 underlying scenario runs.
