# Round 1 — tier report

Prompt frozen at `6cd573a`, `prompt_version()` = `114f4a55af8ba01b`, confirmed against
`evidence/prompt_freeze.json` and the three freeze guards before this run. 72 live scenarios,
same shape as `round0_run2` (`DEV_SEED_SET` base seed 20261004, 6 profiles × 4 objectives ×
3 reps), recorded to `recordings/round1/`, result in `evidence/round1_benchmark.json`. Full
per-criterion machine-readable detail in `evidence/round1_tier_report.json`.

**Tier reached: neither G nor A.**

---

## Part 1 — two zero-call analyses, reported before the tier call

### A. The price_spike collapse (45.5%, 5 pass / 6 flagged, against 100% on three other profiles)

| tick | objective | rules fired | charged |
|---|---|---|---|
| 27 | cost_efficiency | rule_5, rule_8b | 15.8 MW |
| 32 | max_renewable_utilisation | rule_8b only | 7.7 MW |
| 33 | max_renewable_utilisation | rule_8b only | 0 MW |
| 34 | max_profit | rule_5, rule_9 | 5.9 MW |
| 35 | max_profit | rule_5, rule_9 | 1.6 MW |
| 36 | max_profit | rule_5, rule_9 | 10.7 MW |

Four of the six are genuine `rule_5` fires (27, 34, 35, 36); 32/33 are `rule_8b` only
(`max_renewable_utilisation` is exempt from `rule_5`).

**Confirmed, with the numbers: these are correct `rule_5` fires.** Every one of the four shows
`value_actual` (the charged amount) exactly equal to the charge, against zero unsellable
surplus — the entire charged amount could have been sold instead, at $203–$298/MWh.

**A sharper finding than asked for: the reasoning/action mismatch in the model's own words.**
Tick 35's reasoning states the correct action and then submits the opposite:
> *"...under max_profit, sell to grid before charging battery... So we sell 1.6 MW to the grid
> and charge 0 MW."*
Submitted: `charge 1.6 MW`, `market hold`. Ticks 34 and 36 name the sell-first rule correctly
in text, then rationalize charging using `surplus_after_max_charge_mw` as license rather than
as the post-sale remainder it is.

**All 18 max_profit rows, surplus-state charge-before-sell:**

| tick | profile | net position | charge | sell |
|---|---|---|---|---|
| 10 | stable_day | +12.6 | 12.6 | 0 |
| 11 | stable_day | +14.6 | 14.6 | 0 |
| 12 | stable_day | +6.0 | 6.0 | 0 |
| 34 | price_spike | +5.9 | 5.9 | 0 |
| 35 | price_spike | +1.6 | 1.6 | 0 |
| 36 | price_spike | +10.7 | 10.7 | 0 |
| 58 | surplus_day | +47.6 | 16.0 | 31.6 |
| 59 | surplus_day | +41.8 | 16.0 | 25.8 |
| 60 | surplus_day | +50.9 | 0 | 50.9 |

9 of 18 max_profit rows were in a surplus state. **8 of 9 charged before or instead of fully
selling; only tick 60 followed the ladder cleanly.** Two (10, 11) charged the entire surplus
with zero selling on a plain `stable_day`, not even a price event. **The ladder reword works —
it was verified live on the probe's own seed (777001) — but it is a partial fix: roughly 11%
of real surplus-state max_profit rows in this run followed it correctly.**

### B. The two applied-stage fails (ticks 16, 20 — pass raw, fail applied)

**Tick 16** (cloudy_afternoon, min_carbon): raw proposed `battery_2 discharge 7.9 MW` against
its own 6.0 MW rate limit (not a floor issue — SoC 61%, floor 25%). One repair: capped to
6.0 MW. Zero other repairs — no sale, curtailment, or charge was proposed for Phase A to
unwind, so the 1.9 MW gap falls straight to "left standing." 180 MW of transmission headroom
went unused.

**Tick 20** (cloudy_afternoon, max_renewable_utilisation): identical shape — `battery_2
discharge 8.9 MW` proposed, capped to the same 6.0 MW rate limit, one repair, 2.9 MW left
unserved, 180 MW of headroom unused.

**Hypothesis checked: refuted, but adjacent.** C.4's unreachable branch is specifically Phase
A's *charge*-unwind loop, which only has anything to act on when the raw proposal contains a
`charge` action. Neither row proposed any charge — both were pure discharge. The unreachable
branch is not what would have handled these. What's actually missing is the same gap Gate 0.4
already found and the user deliberately chose not to fix (Option C): when the balancer caps an
illegal action, it never substitutes available grid import to cover the resulting gap. Not a
new branch — E.8-grade, as flagged, now confirmed on live data. **Report only, nothing
touched.**

---

## Part 2 — the tier call

### Denominator

**Lead number: 61/72 = 84.7%** — the one 429/safe-mode row (tick 31) stays in the
denominator and never counts as a pass, regardless of the dispatcher fallback's own verdict.
This matches `exit_tiers.json`'s own `run_spec.denominator_note`: *"every scenario in the
denominator — no exclusions."* A literal read of that row's own raw verdict (the dispatcher's
decision, evaluated, which happened to pass cleanly) would give 62/72 = 86.1% — that number is
not used anywhere in this report; crediting a fallback mechanism as the model's own first
attempt would be dishonest in the other direction.

**Secondary: 61/71 = 85.9%** — the agent-only convention (`BatchRunSummary`'s own
`first_attempt_pass_rate_pct` field), excluding the row from both numerator and denominator.

### Criterion by criterion

| Criterion | Tier G threshold | Tier A threshold | Actual | G | A |
|---|---|---|---|---|---|
| Overall first-attempt pass | ≥80.0% (≥58/72) | ≥80.0% (≥58/72) | 61/72 = 84.7% | ✅ | ✅ |
| stable/surplus/shortfall pass | ≥92.0% (≥34/36) | ≥86.0% (≥31/36) | 33/36 = 91.7% | ❌ | ✅ |
| Non-fail rate | ≥97.0% | ≥95.0% (≥69/72) | 70–71/72 = 97.2–98.6% | ✅ | ✅ |
| Per-objective min (/18) | ≥12 | ≥11 | min = 12 (max_profit) | ✅ | ✅ |
| Avoidable-unserved | ≤5.0% | ≤5.0% | 1/72 = 1.4% | ✅ | ✅ |
| Safe mode demonstrated | required | required | met (capability reading) | ✅ | ✅ |
| Replay matches 72/72 | required | required | **71/72 (strict reading)** | ❌ | ❌ |
| Deterministic suite green | required | required | pytest 156/156; step6 clean | ✅ | ✅ |
| Every non-pass classified | required | required | yes, every row below | ✅ | ✅ |
| Zero verdict inconsistencies | required | required | 0 in the full run log | ✅ | ✅ |

**stable/surplus/shortfall — identical to round0_run2 (33/36 = 91.7%), missed by exactly one
row again.** 92% is not an attainable score on a 36-row denominator: 33/36 = 91.7%,
34/36 = 94.4%, nothing lands between them. Stated as context for the miss, never as grounds
for treating 91.7% as having met it.

**Safe mode — full disclosure.** `gate.json`'s literal text:
> `"safe_mode": {"required": "demonstrated", "status_this_patch": "not met — safe mode is
> explicitly out of scope for Brief 2 Patch 2 (it belongs to Brief 3, which is on hold).
> Recording this honestly as unmet rather than marking it demonstrated."}`

The text is ambiguous between two readings: (a) the capability exists and works, demonstrable
by evidence outside any one benchmark run, or (b) the fallback was actually triggered during
the scored run. **Reading (a) is taken.** `"required: demonstrated"` is a capability word, not
an occurrence count, and the status note's own reasoning is about scope/existence at Patch 2
time (safe mode didn't exist yet) — not about trigger frequency. Evidence for the capability
reading, named specifically: `recording.SafeModeRecorder` (Patch 3 Step 4),
`test_safe_mode.py`'s 7 unit tests, the no-key auto-fallback and the invalid-key fallback both
verified live in the browser with the real Google rejection, and Door 2's path exercised
repeatedly through this session's UI work. **round1's own `safe_mode_count` is 1** — caused by
a 429 RESOURCE_EXHAUSTED on tick 31, **not a model failure**, stated plainly rather than
presented as the fallback being exercised by design. Four of the other five quantitative/
qualitative criteria are evaluated against round1's own 72 scenarios; this one is evaluated
against evidence from outside the benchmark, per the reading taken.

**Replay matches 72/72 — the criterion that actually decides this round, taken under the
strict reading, deliberately.**

The literal criterion text is `"replay matches 72/72"`, identical under both tiers. Two
readings produce opposite verdicts:
1. *"Replay reproduces every scenario's recorded verdict"* — **satisfied**. The 429 row's
   replay faithfully reproduces its own recorded failure; all 72 verdicts reproduce exactly.
2. *"Every scenario has a usable recorded model decision to replay"* — **not satisfied**,
   71/72.

**Reading (2), the strict one, is taken.** Under reading (1), Tier A would be reached — it is
the only failing Tier A criterion. We are not taking that reading, and this report is not
arguing for it.

Verified by actually replaying `round1` through the system's own `ReplayRecorder` — not
wrapped in `SafeModeRecorder`, by explicit design (`backend/app/api/routes.py`: *"a replay
miss is a real data-availability problem that should surface as one, not be quietly papered
over by the dispatcher"*). Result: `total=72, judged=71, unresolved=1` (tick 31, same
scenario, same 429).

**Process defect, named plainly.** round1's 72 live calls were made back-to-back with no
pacing, against a measured 15 requests/minute free-tier limit. This is a process/
instrumentation defect, not a model or system defect — the fix is pacing, not a code or
prompt change. D.3 (the 96-row recording) will be paced (~4s between calls) as a direct
result of this finding.

**Decision not to fill the gap.** The single failed scenario (tick 31) was **not** re-run to
complete its recording. A rate-limited call is arguably a missing observation rather than a
measurement, and there's a real argument for filling it — but that decision would be made
knowing it is the one thing standing between this run and Tier A, and avoiding exactly that
kind of contamination is what pre-registration exists to protect. This is a decision taken,
recorded here, not an oversight.

**Deterministic-suite side note.** Re-running `step6_evidence.py` this session initially
showed 2 "unexpected" co-triggers (`rule_5` now legitimately co-firing with injected `rule_11`
faults on `multi_failure_cascade`/`shortfall_day`) — a direct, correct consequence of
yesterday's `rule_8c`/`rule_5` state-based threshold fix: `rule_5`'s price-peak check is no
longer confined to the `price_spike` profile. This was the fault matrix's own expected-
cotrigger documentation being stale, not new behavior. `scripts/step6_evidence.py`'s
`_inject_rule_11` expected-cotrigger set was updated (added `rule_5`) to reflect this — the
only change made, confirmed scoped to that one set. Re-ran: 0 unexpected co-triggers, matching
the previously-known-good state. pytest: 156/156 green throughout.

### Rule-fire breakdown (raw)

`rule_9`: 6, `rule_5`: 4, `rule_8b`: 3, `rule_3`: 1

### Every raw FAIL row

| tick | profile | objective | rule | actual | reference | margin |
|---|---|---|---|---|---|---|
| 38 | multi_failure_cascade | cost_efficiency | rule_3 | 3.7 | 0.0 | 3.7 MW unserved |

### Applied-stage additional fails (beyond the raw fail above)

| tick | profile | objective | raw→applied | rule | unserved | mechanism |
|---|---|---|---|---|---|---|
| 16 | cloudy_afternoon | min_carbon | pass→fail | rule_3 | 1.9 MW | battery_2 rate-capped (6.0 MW limit), no import substitution |
| 20 | cloudy_afternoon | max_renewable_utilisation | pass→fail | rule_3 | 2.9 MW | same mechanism |

---

## Verdict

**Neither Tier G nor Tier A reached.**

- **Tier G**: two misses — stable/surplus/shortfall (33/36 = 91.7% vs 34/36 = 92.0% required)
  and replay-matches-72/72 (71/72, strict reading).
- **Tier A**: one miss — replay-matches-72/72 (71/72, strict reading). Every quantitative
  threshold for Tier A clears, several comfortably (overall 84.7% vs 80% required; sss 91.7%
  vs 86% required; every objective ≥11/18 with margin; avoidable-unserved 1.4% vs 5% ceiling).

Tier A is missed on a single qualitative criterion, taken under its stricter of two valid
readings, caused by a named process defect (no pacing against a known rate limit) rather than
a model or evaluator defect. No reframing of either near-miss into a pass.

No rule, balancer, dispatcher, evaluator, or prompt change. The one 429 scenario was not
re-run. `round0`/`round0_run2` untouched.
