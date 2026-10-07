# Pre-flight audit

Read-only audit of the build as of commit `81ba71d` (current `master`, prompt/facts as of
`678c109`). No code changed as part of this audit. Where a claim below was spot-checked
against one or two examples rather than fully re-derived from first principles, it says so
inline — treat those as "best evidence available", not exhaustively proven.

---

## 1. Consistency — files describing a build that no longer exists

Two prompt-changing commits matter here: the **profit-formula fix** (`TICK_HOURS`, 2026-10-05)
and the **physics-facts + ladder-reword** commit `678c109` (2026-10-07). Both change
`prompt_version()`/`scenario_hash()` (678c109) and/or the scoring formula (the profit fix) —
either one makes a *live-model* number stale; neither affects deterministic, no-model-call
numbers (dispatcher-vs-dispatcher comparisons), which stay valid regardless.

| File | Status | What it would need |
|---|---|---|
| `evidence/round0_benchmark.json`, `reports/round0.md` | **Stale, doubly.** Recorded before the profit fix *and* before 678c109. Spot-checked: re-scoring its 72 stored raw decisions under today's code changes `rule_9`'s verdict on 3 rows (all `D4_SURPLUS_DAY`, profit-formula-sensitive) — confirms it reflects the old formula. | Re-run live under current prompt to mean anything about the current build. |
| `evidence/round0_run2_benchmark.json`, `evidence/round0_run2_tier_report.json` | **Stale re: the prompt, current re: scoring.** Recorded after the profit fix, before 678c109. Re-scoring its 72 raw decisions under today's balancer/rules/physics produces **zero** verdict changes (checked exhaustively this session) — the *scoring* is current. But the *decisions* were made by a model that never saw `min_required_curtailment_mw`/`surplus_after_max_charge_mw` or the reworded ladder, so the pass rate it reports is not what the current prompt would produce. | Re-run live under current prompt — this is the number the final submission needs, and it's the one genuinely missing right now. |
| `evidence/exit_tiers.json`'s tier call, any "Tier A reached" claim | **Stale**, same reason — it was evaluated against `round0_run2`. | Needs the fresh 72-scenario run above before any tier claim is reusable. |
| `evidence/audit_h_cross_objective_probe.json`, `reports/audit_h_deepdive.md` | **Stale, intentionally documented as the "before" side.** `reports/ladder_reword_probe.md` already uses it correctly, labeled as pre-reword. | Nothing — it's doing its job as a historical baseline. No action needed. |
| `recordings/probe_ladder_reword/`, `evidence/ladder_reword_probe.json`, `reports/ladder_reword_probe.md` | **Current.** Recorded under 678c109's prompt — per your addition (1), explicitly not stale, should not be re-run. | Nothing. |
| `evidence/day_report_example.json/.csv`, `evidence/day_report_example_agent_results.json` | **Mixed.** The *code* that builds the report (`day_report.py`, including this session's new `fixed_cost_baseline`) is current, and I rebuilt the JSON/CSV from it this session. But the underlying 12 *agent decisions* in `..._agent_results.json` were recorded pre-678c109 — same situation as `round0_run2`: current scoring, stale prompt-under-test. | Re-run the 12-row day live, then rebuild (same two-step process already used once this session). |
| `recordings/example_96row_day/` + `fileinput_0486961f6cc7` twin | **Stale**, pre-678c109 — this is the one the README calls the shipped "replays with no key" guarantee. Replaying it today (same prompt) still works (nothing about replay checks prompt currency, it just needs a cache-key match against whatever prompt recorded it) — but it does not reflect the current prompt/facts. | Re-record live, once, after any further prompt change — already on the checklist in the physics-facts plan. |
| `evidence/step6_evidence.json` | **Current** — re-ran it this session (Task 3); numbers unchanged from the version that predates 678c109 for everything except `prompt_audit.checked` (184→416, because more recording files accumulated on disk; same "no findings" result). This part of the suite never touches the model, so it was never actually at risk. | Nothing. |
| `evidence/addendumC_reeval.json`, `evidence/patch2_*`, `evidence/brief2_*`, `evidence/objective_audit.*`, `evidence/gate.json`, `reports/patch2.md`, `reports/patch3_step1.md`, `reports/objective_audit.md` | **Stale by construction, and correctly so** — these are dated snapshots of earlier project phases (Brief 2, Patch 2, Addendum C), already superseded by name. Not misleading as long as nobody reads them as current-state claims; none of them are referenced from `README.md` as current numbers. | Nothing — historical record, not a live claim. |
| `evidence/secret_scan*.json`, `evidence/secret_scan.md` | **Scope-limited, not wrong.** Each covers the repo state at the time it ran (round0 staging, post-audit-H staging). Nothing has been staged with secrets since the last scan that I can see, but a scan from two commits ago doesn't cover today's `git log` by definition. | A fresh scan before the final push is cheap insurance, not because anything specific is suspected. |
| `README.md`'s "Measured results" section | **Explicitly placeholder, not misleading** — the file says so itself ("filled in after the final run"). Still, right now it is literally unverifiable: nothing currently in the repo supports any specific number for any of its three placeholders. | The fresh 72-run + 96-row live re-run above, then fill in. |

**Bottom line for Task 3 of your earlier message:** the live-model-dependent evidence
(round0/round0_run2, the 96-row day, day_report_example's decisions) all needs one fresh run
after 678c109 before any pass-rate or tier claim in `reports/`/`README.md` is current. Nothing
deterministic (dispatcher-vs-dispatcher, fault injection, oracle/baselines) was ever at risk.

---

## 2. Dead code and drift

- **`physics.power_balance_residual()`** (`backend/app/data/physics.py:215`) — zero callers anywhere in `app/` or `tests/` (checked by grepping every call-shaped occurrence of the name, excluding its own `def` line). It duplicates almost exactly what `unserved_mw()` already computes via a differently-named `served_mw`-style calc, just returns a signed residual instead of a floored shortfall. Looks like a superseded first draft of `unserved_mw`/the balancer's own internal `served_mw` closure, never deleted.
- **`_shortfall_ladder`'s docstring** — already fixed (the Patch 3 addendum note is right there in the docstring, and the ladder order matches it). Flagging it only because you asked me to confirm the pattern had no siblings left — see next two items, which are the siblings.
- **`README.md`'s File Input description** (lines 60–62): claims the File Input panel shows "(File Input) a per-tick ledger ... with a side-by-side comparison against the dispatcher baseline." No such UI exists — `day_report.py` (which computes exactly that) has no API route and no frontend component (`grep`-confirmed: zero references to `day_report`/`build_day_report` anywhere under `frontend/src` or `app/api/routes.py`). This is documentation describing a feature that exists at the Python-function level but was never wired up — drift between what got built and what the README says got built, not a stale-number problem like section 1's.
- **`README.md`'s Known Limitations** ("the declared objective does not reliably change the model's surplus decision... under max_profit, the ladder is defined to sell before charging; in observed runs the live model frequently charges first regardless"): this was true pre-678c109 and is the exact limitation the ladder reword targeted. This session's own probe (`reports/ladder_reword_probe.md`) shows `max_profit` now sells 28.6 MW / charges 0 MW while the other three objectives still charge 16 MW / sell 12.6 MW on the same state, 3/3 samples — directly contradicting the limitation as currently worded for at least that one case. The weaker, still-true part of the claim ("cost_efficiency/min_carbon/max_renewable_utilisation remain indistinguishable from each other") was *not* fixed and is still accurate. The bullet needs to be split, not deleted.
- **`rule_11`'s docstring** calls grid-pre-charging "a documented limitation, not implemented" — still accurate, no drift, confirmed by reading `balancer.py`'s charge-cap logic (capped to `renewable_surplus_mw`, never to `renewable_surplus_mw + purchase`).
- **Fault-injection matrix docstring vs. code**: `step6_evidence.py`'s module docstring and your own Task 3 message both say "12 fault types × 5 scenarios" (= 60 cases). The actual `PROFILES` list has grown to 6 difficulties (stable/cloudy/price_spike/multi_failure_cascade/surplus/shortfall) since that docstring was written, and `run_fault_matrix()` iterates all of them — 12×6 = **72** cases, confirmed by this session's re-run ("70/72 intended-rule detections"). The docstring is stale; the code is what actually runs. I ran the current 72-case version (see Task 3 report); I did not go back and make it artificially 60 to match the comment.
- **`run_server.bat` / `run_dev.bat`**, referenced unqualified in `README.md`'s Development section — they exist, just not at repo root (`backend/run_server.bat`, `frontend/run_dev.bat`). Not wrong, just a location a first-time reader would have to find by directory listing rather than the README saying where.

I did not find a second case of "comment says the opposite of the code" as clean as `_shortfall_ladder`'s original bug — the two README items above are the closest analogues, but they're prose-vs-implementation drift rather than a comment directly contradicting the function beneath it.

---

## 3. Rules

All 18 rules, from `run_rules()` in `backend/app/data/rules.py` (plus one pipeline-only rule not in that list):

| Rule | Severity | Compares | Objective-gated? |
|---|---|---|---|
| `rule_1` no-curtail-while-buying | fail | curtailment beyond `min_required_curtailment_mw` vs. simultaneous grid purchase | No |
| `rule_2a` absolute floor | fail | resulting SoC after discharge vs. `min_safe_soc_pct` | No |
| `rule_2b` applied floor | flagged | resulting SoC after discharge vs. `applied_floor_pct`, exempt if `is_emergency` | No |
| `rule_3` unserved load | fail | `unserved_mw` vs. `min_achievable_unserved_mw` | No |
| `rule_3b` reserve margin | flagged | reserve-margin headroom vs. target %, N/A if load already unserved | No |
| `rule_4` no-sell-while-unmet | fail | selling vs. `unserved_mw > 0` | No |
| `rule_5` no-charge-at-peak | flagged | avoidable charge vs. unsellable surplus, at a price peak, outside emergency | **Yes — N/A for `MIN_CARBON`/`MAX_RENEWABLE_UTILISATION`** |
| `rule_6` curtailment amount | fail | curtailed MW vs. `min_required_curtailment_mw` | No |
| `rule_7` transmission/frequency | fail | net transmission flow vs. headroom; grid frequency vs. band | No |
| `rule_8a` floor hard bounds | fail | `applied_floor_pct` vs. `[FLOOR_MIN, FLOOR_MAX]` | No |
| `rule_8b` floor band match | flagged | `proposed_floor_pct` vs. `expected_floor_min/max_pct` | No |
| `rule_8c` floor raised w/o signal | flagged | `proposed_floor_pct` vs. calm-band ceiling, needs a volatility signal | No |
| `rule_8d` floor justification present | flagged | `floor_justification` non-empty | No |
| `rule_8e` floor clamp/ramp consistency | flagged | `proposed_floor_pct == applied_floor_pct` | No |
| `rule_9` cascade deviation | flagged | actual cost/emissions/utilisation/profit vs. dispatcher-computed best, N/A if best≈worst | **Yes — branches on `_CASCADE_PRIORITY[scenario.objective]`, one of 4 metrics + a `None`→cost default** |
| `rule_10` repair magnitude | flagged | total `\|delta_mw\|` across balancer repairs vs. `REPAIR_TOLERANCE_MW` | No (raw stage excludes it entirely, not gated by objective) |
| `rule_11` no-grid-charging | flagged | proposed charge vs. `renewable_surplus_mw` | No |
| `rule_model_call` (pipeline-only, not in `run_rules()`) | fail | whether a decision was produced at all | No |

**Can never fire:** none found that are structurally unreachable. The closest candidate,
`rule_9`, has a built-in escape (`_rule9_na`) that returns `passed=True, applicable=False`
whenever best≈worst — by design, not a bug, and it does still fire (fail) on real cases (the
fault-injection matrix and this session's smoke runs both show it failing). I did not find
a rule whose `passed=False` branch is dead for every input — this would need a targeted
proof per rule (e.g. SMT-style), which is more than a spot-check audit can certify; treat
"none found" as "none found by inspection," not a proof.

**Rules that can contradict each other:** none found that disagree on the *same* decision in
a way that can't both legitimately hold — `rule_1`/`rule_6` (both curtailment-amount checks)
and `rule_3`/`rule_4` (both keyed off the same `unserved_mw`) are *coupled*, not contradictory
— they're expected to co-fire, which `step6_evidence.py`'s fault matrix explicitly documents
and checks for (the "expected co-triggers" sets in each `_inject_rule_*` function). The one
structurally interesting case: `rule_2b` (flagged, exempts a floor breach during a genuine
emergency) and `rule_9` (flagged, scores against the dispatcher's own floor-respecting
reference) could in principle pull in different directions on the same emergency tick — I
did not find a concrete case of this in the fault matrix or the smoke runs, so this is a
*possible* tension by reading the code, not a demonstrated one. Flagging it as spot-checked,
not proven.

**Depends on a value nothing computes any more:** none found. Every `scenario.*`/`decision.*`
field every rule reads is still populated by `scenario_agent.py`/the schema — I checked this by
reading each rule's inputs against `EnvironmentState`/`Decision`'s current field lists, not by
exhaustively tracing every write site, so a narrow miss (a field that's still declared but
whose only writer was deleted) is possible but none turned up.

---

## 4. Facts — `orchestrator_facts()` (`backend/app/data/physics.py:320`+)

| Key | Source |
|---|---|
| `sellable_surplus_mw` | `physics.sellable_surplus_mw()` |
| `max_import_mw` | `physics.max_import_mw()` |
| `min_required_curtailment_mw` | `physics.min_required_curtailment_mw()` |
| `surplus_after_max_charge_mw` | `physics.surplus_after_max_charge_mw()` |
| per-battery `discharge_available_mw` / `charge_headroom_mw` | `physics.battery_headroom_facts()` → `max_discharge_mw`/`max_charge_mw` per battery, at `floor_pct` |

All five are named explicitly in `SYSTEM_PROMPT`'s "Physics facts" paragraph
(`orchestrator_agent.py`), confirmed by this session's `prompt_audit_live.py` run (Task 3) —
every one of these keys is present in all 300 freshly-built requests checked.

**Anything a rule checks that isn't in the facts the model sees:** two gaps, both pre-existing
and both already named in `README.md`'s Known Limitations (so not new findings, just
confirming they're still real):
- `expected_floor_min_pct`/`expected_floor_max_pct` (`rule_8b`) are in `_HIDDEN_FIELDS` —
  deliberately withheld (the model isn't supposed to know the expected answer). This is
  correct by design, not a gap.
- `min_achievable_unserved_mw` (`rule_3`'s own benchmark, which assumes full
  *emergency*-level discharge is available) is **not** in `orchestrator_facts()` — the model
  only sees non-emergency `discharge_available_mw`. This is the same root cause behind the
  `price_spike`/`multi_failure_cascade` smoke-set failures reported earlier this session: the
  model has no fact telling it how much *import* headroom alone would cover a shortfall
  without touching any floor, so it sometimes proposes a floor-breaching or rate-exceeding
  discharge instead of the available import. Not acted on here — report only.

---

## 5. The judge's path

**README vs. code, claim by claim** (only the ones that don't already match 1:1):
- "File Input panel... with a side-by-side comparison against the dispatcher baseline" —
  **wrong**, no such UI exists (section 2, dead/drift).
- Known Limitations' max_profit bullet — **half-stale** post-678c109 (section 2).
- "Measured results" placeholders — **unverifiable right now**, by the README's own admission.
- Everything else I checked against the actual code matched: the 3-run-modes table against
  `recording.py`'s `LiveRecorder`/`SafeModeRecorder`/`ReplayRecorder`; the "no Node required"
  claim against `main.py`'s `StaticFiles` mount + the committed `frontend/dist/`; the
  PowerShell/port/pip troubleshooting entries against `run.bat`/`startup_check.py`; the
  429/503 retry claim against `orchestrator_agent.py`'s `_is_transient` retry logic — all
  spot-checked by reading the referenced code, not run end-to-end in a browser as part of
  this audit.

**Repo root**, every file, first-time-reader lens:
| File | Helps or confuses a first-time reader |
|---|---|
| `README.md` | Helps — the entry point, as intended. |
| `ARCHITECTURE.md` | Helps — design rationale, correctly linked from the README. |
| `run.bat` / `run.sh` | Helps — exactly what the README tells you to run. |
| `.gitattributes` / `.gitignore` | Neutral — invisible to a judge unless they go looking. |
| `backend/`, `frontend/`, `docs/`, `evidence/`, `reports/`, `recordings/` | Helps — self-explanatory top-level structure, matches what the README describes. |
| `.claude/` | **Neutral-to-confusing** — this assistant's own plan-mode scratch directory; not project content, harmless but has no reason to be at the repo root from a judge's perspective. Not something I'll touch without being asked. |

No leftover `brief2_*.json`, `start.bat`, or `NEXT_STEPS.md` at the root — your addition (3)
asked me to check specifically; all three are confirmed gone (the B3 repo-tidy from earlier
this session already handled them) and nothing has reappeared since.

`docs/`'s two PDFs (`...Architecture & Features.pdf`, `...Next Steps.pdf`) are your own stated
task ("I will take care of the file part") — not assessed here beyond confirming they're still
present and that `NEXT_STEPS.md` (the markdown version) is gone, which may have been the PDF's
source of truth at some point; I didn't open the PDFs to check their own currency.

---

## 6. Tests — what the 128 cover, and what they don't

By file (128 total, all passing): `test_acceptance.py` (22, golden-rule/pipeline behavior),
`test_calibration.py` (45, physics/rule numeric calibration, includes this session's 3 new
tests), `test_dispatcher.py` (28, dispatcher ladders/floor logic), `test_file_input.py` (10,
parsing/validation/hashing), `test_recording.py` (9, cache-key/scrub/resume), `test_resilience.py`
(7, retry/transient-error handling), `test_safe_mode.py` (7, fallback behavior).

**Zero coverage, confirmed by import-grep (nothing in `tests/` references these at all):**
- **`day_report.py`** — the entire per-tick/cumulative/baseline-comparison module, including
  this session's new `fixed_cost_baseline`, has no test at all. Every number in it is
  currently verified only by the manual arithmetic spot-checks done earlier this session, not
  by an assertion anywhere in the suite.
- **HTTP/API layer** (`app/api/routes.py`) — no test uses FastAPI's `TestClient` (confirmed:
  zero matches for `TestClient`/`httpx` anywhere in `tests/`). Three test files import
  `_summarize` directly from `routes.py` as a plain function, bypassing FastAPI entirely —
  request validation, the 404 paths (e.g. `file_input_run_row`'s unknown-`run_id` case),
  multipart upload parsing, and the static-file mount are all untested at the HTTP level.
- **Frontend** — no test runner configured at all (`frontend/package.json` has only
  `dev`/`build`/`preview` scripts); zero JS/JSX test files exist.
- **`balancer.py`'s Phase A/B unwind order** (sale→curtailment→charging unwind when load is
  unmet; surplus absorption via extra sale then forced curtailment) is exercised *indirectly*
  by `test_acceptance.py`/`test_calibration.py` fixtures that happen to trigger it, but I found
  no test naming "unwind order" or asserting the specific sequence — a future change to that
  order could pass the existing suite while changing behavior.
- **`recording.py`'s `verify()`** (manifest-mismatch detection) has no direct test — `scrub()`
  and the cache-key/resume behavior do (`test_recording.py`), `verify()` doesn't.

---

## 7. What would embarrass us if a judge found it first

Ranked by how bad it'd look, not by how big the fix is:

1. **The README claims a UI feature (File Input's baseline comparison) that doesn't exist.**
   A judge who reads the README and then tries to find that panel will not find it. This is
   the single most concrete "the docs oversold the build" finding in this audit.
2. **Every live-model number currently in `reports/`/`evidence/` (round0, round0_run2, the
   96-row day) describes a build from before the last prompt change.** Nothing dishonest about
   it — it's clearly dated by file/commit — but if the final submission ships without a fresh
   run, the headline pass-rate number would be measuring a system that no longer exists.
3. **The Known Limitations bullet about max_profit is now half-wrong**, in the *optimistic*
   direction this time (it understates what the current build does) — less embarrassing than
   overselling, but still inaccurate, and an inaccuracy a judge could independently reproduce
   (it's literally the scenario this session's probe used) and then wonder what else in that
   section is out of date.
4. **Zero HTTP-level tests and zero frontend tests.** Not visible to a judge who doesn't read
   the test suite, but visible to one who does (`pytest -q` output says "128 passed" with no
   indication of what layer that covers) — "128 tests, 0 of them touch the API or the UI" is
   an uncomfortable fact to have surface in a Q&A.
5. **`power_balance_residual()`** sitting unused in `physics.py` — minor, but it's the kind of
   thing a code-reading judge notices and asks "why is this here."

Nothing that looks like a secret, a credential, or a safety issue turned up in this pass
(`step6_evidence.py`'s recordings-based prompt audit re-ran clean at 416 files checked; the
live-build `prompt_audit_live.py` written this session ran clean at 300 fresh requests) —
the list above is entirely about documentation/evidence currency and test-layer gaps, not
leaks.
