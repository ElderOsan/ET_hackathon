# Step Report: Brief 2 Patch 2 (rule calibration, profit prices, verdict consistency, gate)

## A. Identity

- **Step name:** Brief 2 Patch 2 (checklist Step 1)
- **Git commit hash:** `9674460`
- **Working tree:** clean at time of this report
- **Date/time:** 2026-10-04 09:31 IST
- **Model:** `gemini-3.5-flash-lite` (`backend/app/core/config.py`, env `GEMINI_MODEL`)
- **Temperature:** not explicitly set — `GenerateContentConfig` in `orchestrator_agent.py::decide()` passes no `temperature`, so Gemini's API default applies. Not pinned anywhere in this codebase; flagged in H below.

## B. What changed

**Files touched** (full list, `git diff --stat 15c8ba8..9674460`):
`evidence/gate.json` (new), `brief2_patch2_benchmark.json` (new), `evidence/patch2_runs.jsonl` (new), `evidence/patch2_summary.csv` (new), `reports/patch2.md` (new, this file), `backend/app/data/physics.py`, `backend/app/data/rules.py`, `backend/app/data/balancer.py`, `backend/app/data/tuning.py`, `backend/app/agents/pipeline.py`, `backend/app/agents/orchestrator_agent.py`, `backend/app/agents/scenario_agent.py`, `backend/app/api/routes.py`, `backend/app/models/schemas.py`, `backend/tests/test_acceptance.py`, `backend/tests/test_calibration.py` (new), `frontend/src/App.jsx`, `frontend/src/components/{DecisionPanel,BatchRunPanel,ManualEntryForm}.jsx`.

**New functions:** `physics.max_achievable_headroom_mw`, `physics.buy_price_per_mwh`, `physics.sell_price_per_mwh`, `physics.decision_profit`, `rules._rule9_na`, `routes._excluded_as_vacuous_na`.

**Config values added or changed** (`backend/app/data/tuning.py`):
| Constant | Old | New |
|---|---|---|
| `PRICE_SPREAD_PCT` | (did not exist) | `5.0` |

No existing threshold (`RESERVE_MARGIN_PCT`, `OBJECTIVE_TOLERANCE_PCT`, `BALANCE_TOLERANCE_MW`, `REPAIR_TOLERANCE_MW`, `CURTAIL_TOLERANCE_MW`, the floor bands) changed value. This patch changed *formulas* (what a rule compares against), not the numeric tolerances themselves — `rule_9`'s N/A check reuses `OBJECTIVE_TOLERANCE_PCT` rather than introducing a new tolerance.

Two literal `>0.05` logging-magnitude gates in `balancer.py` (Phase B) were removed — they were dead code under this codebase's 1-decimal rounding discipline (any nonzero delta there is always ≥0.1), not functioning thresholds.

## C. Tests

| Group | Run | Passed | Failed |
|---|---|---|---|
| `tests/test_acceptance.py` | 22 | 22 | 0 |
| `tests/test_calibration.py` (new this step) | 31 | 31 | 0 |
| **Total** | **53** | **53** | **0** |

No failures to list.

## D. Runs

| Run | Seed(s) | n | Passes | Stage measured | Breakdown |
|---|---|---|---|---|---|
| Step 5 diagnostics | 727504630 (base) | 24 | 1 | raw + applied | 6 profiles × 4 objectives × 1 |
| Step 5 tick-1/tick-60 spot checks | 472264643, 1039876167 | 2 | 1 | raw + applied | single runs |
| **Step 6 gate benchmark (this report's headline)** | **20261004 (dev base)** | **72** | **3, pooled** | **raw + applied** | **6 profiles × 4 objectives × 3 reps** |

## E. Results (Step 6, 72 scenarios, dev seed set, 3 passes pooled)

Stage/count totals: 0 infeasible, 10 margin-infeasible (all `multi_failure_cascade`), 3 repaired, **33/72 (45.8%) excluded as vacuous rule_9 N/A** (both stages clean PASS and rule_9 inapplicable) — judged n = 39.

| Metric | Rate | n | 95% CI (Wilson) |
|---|---|---|---|
| First-attempt pass rate | 53.8% | 21/39 | (38.6%, 68.4%) |
| Applied pass rate | 53.8% | 21/39 | (38.6%, 68.4%) |
| Non-fail rate (pass+flag) | 94.9% | 37/39 | (83.1%, 98.6%) |
| stable+surplus+shortfall first-attempt | 47.6% | 10/21 | (28.3%, 67.6%) |

Applied: 21 pass, 16 flagged, 2 fail. Repair rate 4.2% (3/72).

Per-profile (judged, applied pass rate):
| Profile | Rate | n | 95% CI |
|---|---|---|---|
| stable_day | 50.0% | 3/6 | (18.8%, 81.2%) |
| cloudy_afternoon | 85.7% | 6/7 | (48.7%, 97.4%) |
| price_spike | 16.7% | 1/6 | (3.0%, 56.4%) |
| multi_failure_cascade | 80.0% | 4/5 | (37.6%, 96.4%) |
| surplus_day | 33.3% | 2/6 | (9.7%, 70.0%) |
| shortfall_day | 55.6% | 5/9 | (26.7%, 81.1%) |

Per-objective (all 72 rows, NA included in their actual pass/flag/fail bucket — not judged-only):
| Objective | Total | Passed | Flagged | Failed |
|---|---|---|---|---|
| cost_efficiency | 18 | 15 | 2 | 1 |
| min_carbon | 18 | 17 | 1 | 0 |
| max_renewable_utilisation | 18 | 16 | 1 | 1 |
| max_profit | 18 | 6 | 12 | 0 |

Category breakdown (raw-stage, all 72): arithmetic 1, strategy 24, outcome 1.

**All CIs here are wide** — per-profile judged n ranges 5–9. A ±10-point difference between two 72-scenario runs is noise per the checklist's own guidance; these numbers should not be read at single-point precision.

## F. Non-pass catalogue (all 18 non-passing rows out of 72, applied stage)

| tick | seed | profile | objective | verdict | category | rules + root cause |
|---|---|---|---|---|---|---|
| 10 | 20261304 | stable_day | max_profit | flagged | strategy | rule_9: revenue $0, cost $0, net $0 vs nonzero reference — model made no market move where the reference dispatch would have |
| 11 | 20261305 | stable_day | max_profit | flagged | strategy | rule_9: same pattern as tick 10 |
| 12 | 20261306 | stable_day | max_profit | flagged | strategy | rule_9: same pattern as tick 10 |
| 24 | 20271306 | cloudy_afternoon | max_profit | flagged | strategy | rule_9: bought 0.9MW instead of selling — net $-49 vs a better reference |
| 27 | 20281006 | price_spike | cost_efficiency | flagged | strategy | rule_5: charged 15.8MW, all of it sellable surplus (0MW unsellable) — fully avoidable |
| 32 | 20281205 | price_spike | max_renewable_utilisation | flagged | strategy | rule_8b: proposed floor 25% below the expected 30–45% band |
| 34 | 20281304 | price_spike | max_profit | flagged | strategy | rule_5 (5.9MW avoidable charge) + rule_9 (no sale despite $265/MWh price) |
| 35 | 20281305 | price_spike | max_profit | flagged | strategy | rule_5 (1.6MW avoidable) + rule_9 (no sale) |
| 36 | 20281306 | price_spike | max_profit | flagged | strategy | rule_5 (10.7MW avoidable) + rule_9 (no sale) |
| **38** | 20291005 | multi_failure_cascade | cost_efficiency | **fail** | arithmetic+strategy | rule_3: 3.7MW unserved — proposed importing 5.7MW against a 2.0MW `transmission_at_capacity` headroom; balancer capped it, shortfall left standing |
| **55** | 20301204 | surplus_day | max_renewable_utilisation | **fail** | arithmetic+strategy | rule_6/rule_9: curtailed 17.7MW with 180MW of unused transmission headroom available — unforced curtailment, same pattern as Step 5's tick-19 finding |
| 58 | 20301304 | surplus_day | max_profit | flagged | strategy | rule_9: sold 31.6MW for $1081, below the reference optimum (tolerance) |
| 59 | 20301305 | surplus_day | max_profit | flagged | strategy | rule_9: same pattern, $613 vs reference |
| 60 | 20301306 | surplus_day | max_profit | flagged | strategy | rule_9: same pattern, $792 vs reference |
| 63 | 20311006 | shortfall_day | cost_efficiency | flagged | strategy | rule_2b (discharged to exactly its own applied floor) + rule_9 ($4897 import cost vs $4326 reference) |
| 64 | 20311104 | shortfall_day | min_carbon | flagged | strategy | rule_9: 21.8MW grid import vs 13.8MW reference minimum |
| 70 | 20311304 | shortfall_day | max_profit | flagged | strategy | rule_2b + rule_9 (bought 10.8MW, net $-2783, no better option attempted) |
| 71 | 20311305 | shortfall_day | max_profit | flagged | strategy | rule_9: bought 28.8MW, net $-5123, no better option attempted |

**Pattern:** `max_profit` accounts for 11 of 18 non-pass rows (61%) — consistent with the brief's own original note that profit is where the model is weakest, now visible with real numbers instead of the old `$0` netting bug. The two FAILs are both one-off arithmetic/strategy mistakes, not a repeated pattern across the 72-row sample.

## G. Deviations and assumptions

1. **`rule_9` "worst feasible" formula is my own construction**, not given verbatim in the brief. Defined per branch as: cost/carbon — grid import with zero battery help; renewable — the entire surplus curtailed instead of sold; profit — the combination of both. Documented in `balancer.py::reference_dispatch` with reasoning; flagged for your review in the earlier chat turn (Step 2 completion) and not revised since.
2. **`rule_3b`'s tolerance** reuses `BALANCE_TOLERANCE_MW` (0.1MW) rather than a new constant — the brief said "the tolerance" without a value; reusing an existing named constant rather than inventing a number.
3. **Tick numbers don't match your original report's tick 38/43/44/46/47/48/49/50/55/56.** `tick` is a process-global counter, not derived from the seed — confirmed by `test_13`'s own reproducibility check, which explicitly excludes `tick` from the equality comparison. This step's own 72-row run has ticks 1–72; row numbers in section F and the Step 5 report are from *this* run, indexed consistently within itself, not literally matching your earlier session's numbering.
4. **The row-49 root cause was re-diagnosed mid-step.** My first hypothesis (a sub-0.05MW balancer logging gate) turned out to be structurally unreachable given this codebase's pervasive 1-decimal rounding. The real, demonstrated cause: `ScenarioRunResult.repaired` was gated on `REPAIR_TOLERANCE_MW` (0.5MW), five times coarser than `rule_3`'s own `BALANCE_TOLERANCE_MW` (0.1MW) — a repair as small as 0.2MW can flip `rule_3` while reading "Repaired: no." Fixed: `repaired = len(repairs) > 0`.
5. **A second bug was found and fixed while building this report**, not anticipated in the brief: the `rule_9` N/A exclusion was applied-stage-only, which silently dropped a genuine `rule_3` FAIL (tick 38) from the fail count because that scenario's unrelated `rule_9` happened to be N/A. Fixed to require both stages be a clean PASS before excluding (section H has the before/after numbers).
6. **"Replay the original 24 pre-patch raw proposals under old vs. new rules"** (your Step 1 checklist item) was not done — see H.

## H. Known issues (not fixed)

1. **No record/replay infrastructure exists yet.** The pre-patch batch (58.3% pass rate, seed 727504630) was never stored as raw proposals — it reached me as prose in a prior chat session, not as data. There is nothing to replay. This is squarely what your checklist's Step 2 ("single dispatcher, record and replay") would build; it doesn't exist in this codebase as of this commit.
2. **The Gemini retry logic doesn't catch 429 rate-limit errors.** `orchestrator_agent._is_transient` checks `isinstance(exc, genai_errors.ServerError)`, but a 429 from the free tier raises `ClientError`, which doesn't match — so `tenacity`'s retry/backoff never engages on a rate limit; the call fails immediately instead of backing off. Discovered because it crashed the first Step 5 run outright. Not fixed (out of scope for this brief; I worked around it operationally with sleep/retry in my own scripts, not in production code).
3. **The rule_9 N/A rate is high: 33/72 (45.8%).** This is the direct, intended consequence of the Step 2 design (no shortfall → cost/carbon N/A; no surplus → renewable N/A) across a 6-profile matrix where several profiles never have a shortfall or never have a surplus. Not a bug, but it shrinks the judged sample a lot (72→39) and widens every CI in section E. Worth your judgment on whether the N/A scope is right.
4. **The unforced-curtailment pattern (tick 55 this run, tick 19 in the Step 5 diagnostics) has now shown up twice independently.** Looks systemic, not a one-off — no fix attempted, flagged for your prioritization.
5. **Per-profile judged n is small (5–9)**, so the per-profile table in section E should be read as "noisy, directionally suggestive" rather than precise — `price_spike`'s 16.7% in particular rests on a single judged scenario out of 6.
6. **Temperature is unset** (see A) — not reproducible call-to-call even at a fixed seed, as already observed with the tick-60 floor (30% originally, 50% on my re-run).

## I. Raw data

- **JSONL** (one row per scenario, full nested stage/rule detail): [evidence/patch2_runs.jsonl](../evidence/patch2_runs.jsonl)
- **summary.csv** (tick, seed, profile, objective, raw/applied verdict, rules fired, repaired, unserved_mw, applied_floor_pct, volatility_class, na_rule9, margin_infeasible): [evidence/patch2_summary.csv](../evidence/patch2_summary.csv)
- **Full BatchRunSummary** (aggregate, same source as E/F above): [brief2_patch2_benchmark.json](../brief2_patch2_benchmark.json)
- **Gate file:** [evidence/gate.json](../evidence/gate.json)

## Code references

- **3b target:** `backend/app/data/rules.py::rule_3b_reserve_margin` (target = `min(required, achievable)`); achievable from `backend/app/data/physics.py::max_achievable_headroom_mw`.
- **Profit calculation:** `backend/app/data/physics.py::decision_profit`.
- **Avoidable-charge calculation:** `backend/app/data/rules.py::rule_5_no_charge_at_price_peak` (`avoidable_charge_mw = max(0, charge - unsellable_surplus_mw)`).
- **rule_9 N/A condition:** `backend/app/data/rules.py::_rule9_na` (per-branch best/worst from `balancer.py::reference_dispatch`).
- **Consistency check:** `backend/app/agents/pipeline.py::run_decision_pipeline` (the `INCONSISTENT_VERDICT` log) and `backend/tests/test_calibration.py::test_consistency_over_real_72_row_benchmark` (checked against this step's actual 72-row data, not only synthetic fixtures).
