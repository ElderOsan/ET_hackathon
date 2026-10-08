# Evidence and reports index

One row per artifact in `evidence/` and `reports/`. `prompt_version` is `orchestrator_agent.prompt_version()`
at the time the underlying model calls were made (hashes `SYSTEM_PROMPT` + the tool schema) --
`N/A` means the artifact involves no live model call (deterministic re-score, pre-registration
spec, or a scan). Current prompt_version as of commit `50256d0` is `114f4a55af8ba01b`
(`evidence/prompt_freeze.json`); anything below it is stale for live-model purposes. This file
replaces guessing from filenames -- see the two different 12-row datasets below (the live-agent
one and the dispatcher/safe-mode one) that caused this morning's confusion.

## Pre-registration (not run output -- current by definition, nothing to supersede)

| File | What it is | Commit | prompt_version | Status |
|---|---|---|---|---|
| `evidence/gate.json` | Brief 2 Patch 2's pre-registered pass-rate thresholds, frozen before any benchmark run | `dacdff2` | N/A (spec) | Current |
| `evidence/exit_tiers.json` | Round 0's pre-registered tier definitions (Tier G / Tier A), frozen before the run | `e1c464e` | N/A (spec) | Current |
| `evidence/prompt_freeze.json` | The prompt freeze record itself (SHA, timestamp, prompt_version, reference scenario_hashes) | `cad104a` | `114f4a55af8ba01b` | Current -- this IS the freeze |

## Round 0 benchmark (72 scenarios) -- pre-registered, history kept intact per instruction

| File | What it is | Commit | prompt_version | Status |
|---|---|---|---|---|
| `evidence/round0_benchmark.json` | First Round 0 pass, full 72-row dump | `b5c751b` | `8088e95c1e20b0c7` | **Stale** -- pre profit-fix AND pre-678c109. 3 rows' `rule_9` verdicts don't match current code (profit formula). Kept as history, not a current-build claim. |
| `evidence/round0_tier_report.json` | Tier evaluation against `round0_benchmark.json` | `b5c751b` | `8088e95c1e20b0c7` | **Stale**, same reason as above |
| `reports/round0.md` | Written-up Round 0 report | `b5c751b` | `8088e95c1e20b0c7` | **Stale** -- describes the pre-profit-fix run |
| `evidence/round0_profit_fix_reeval.json` | `round0_benchmark.json`'s raw decisions re-scored under the profit-fix code (zero model calls) | `d81b308` | `8088e95c1e20b0c7` (re-scored, not re-recorded) | Scoring-current as of the profit fix; now stale again re: the 678c109 prompt change (the decisions themselves are still pre-678c109) |
| `evidence/round0_run2_benchmark.json` | Round 0 re-run after the profit fix, full 72-row dump | `cac91bd` | `8088e95c1e20b0c7` | **Stale re: prompt** (pre-678c109) but **current re: scoring** -- re-scoring its stored raw decisions under today's code (checked this session) produces 0 verdict changes. This is the number the fresh round1 run supersedes. |
| `evidence/round0_run2_tier_report.json` | Tier evaluation against `round0_run2_benchmark.json` | `cac91bd` | `8088e95c1e20b0c7` | Same as above |
| **`evidence/round1_*` (placeholder)** | **Tomorrow's fresh 72-scenario run, post-678c109 AND post the rule_8c/rule_5 fix** | *(not yet run)* | `114f4a55af8ba01b` (expected) | **Pending** -- this is the number that supersedes `round0_run2` for the final submission |

## Shipped-demo evidence (README-referenced, judge-facing, re-recorded tomorrow)

| File | What it is | Commit | prompt_version | Status |
|---|---|---|---|---|
| `recordings/example_96row_day/` + `recordings/fileinput_0486961f6cc7/` | The 96-row day's recorded calls (two run_ids, same content -- see Gate 0.1) | `48e6e2d` (shipped) | `8088e95c1e20b0c7` | **Stale and currently broken** -- replay on current master misses 100% of rows (verified live, Gate 0.1). Re-record scheduled. |
| `recordings/day_report_example/` | The 12-row day's recorded **live-agent** calls | `43a3695` | `8088e95c1e20b0c7` | **Stale**, same reason |
| `evidence/day_report_example_agent_results.json` | The 12-row live-agent `ScenarioRunResult`s, as recorded | `43a3695` | `8088e95c1e20b0c7` | Stale decisions, but... |
| `evidence/day_report_example.json` / `.csv` | The built day report from the above, **re-scored under current rules** via `pipeline.reevaluate_stored` (zero model calls) | `50256d0` | N/A (re-scored) | **Current re: scoring** (first-attempt pass 83.3%, post rule_8c fix). Still describes a pre-678c109 prompt's decisions -- a fresh live 12-row run would still change the actual proposals, not just their verdicts. |

**Note on the two different "12-row reports" that caused this morning's confusion:** the table
above is the **live-agent** one (`day_report_example_agent_results.json`, real model decisions,
not stored as a committed day-report artifact's twin). A **separate**, not-committed-anywhere
12-row report was demonstrated live in chat during the B9 checkpoint and again during the
rule_8c fix verification, built from **Safe-mode dispatcher decisions** on the same
`file_input.EXAMPLE_DAY_ROWS` data, run fresh through the UI/API each time -- it has no evidence
file of its own and is reproducible on demand (`dispatcher.dispatch` on each row, zero model
calls). Do not confuse the two: same 12 input rows, different decision-makers, different
verdicts.

## Probes (deliberately dated, cited correctly as before/after)

| File | What it is | Commit | prompt_version | Status |
|---|---|---|---|---|
| `evidence/audit_h_cross_objective_probe.json` | Cross-objective probe, pre-reword baseline | `ee694a6` | `8088e95c1e20b0c7` | **Stale, intentionally** -- the documented "before" side of the ladder-reword comparison. Correct as-is. |
| `reports/audit_h_deepdive.md` | Write-up of the above | `edc3c2b` | `8088e95c1e20b0c7` | Same |
| `evidence/ladder_reword_probe.json` | Cross-objective probe, post-reword | `81ba71d` | `114f4a55af8ba01b` | **Current** |
| `reports/ladder_reword_probe.md` | Before/after write-up (uses both probes above) | `81ba71d` | mixed (by design) | **Current** |

## This session's own infrastructure evidence

| File | What it is | Commit | prompt_version | Status |
|---|---|---|---|---|
| `evidence/step6_evidence.json` | Deterministic suite: 200-scenario oracle + baselines, 72-case fault matrix, determinism checks, recordings-based prompt-leak scan | `6cd573a` | N/A (no model calls in A/B/C/E; D scans whatever's on disk at run time) | **Current** -- re-ran this session, numbers unchanged from the last known result |
| `reports/preflight_audit.md` | Full pre-flight audit (this file's own source material for the table above) | `6cd573a` | N/A (audit document) | Current as of its own commit; superseded in spirit by this INDEX for the stale/current question specifically |
| `evidence/secret_scan.md` | Secret-scan write-up | `bbebba9` | N/A (scan) | Covers repo state at `bbebba9`; re-scan before final push, not because anything is suspected |
| `evidence/secret_scan_post_audith.json` | Secret scan after audit-H recordings staged | `bbebba9` | N/A (scan) | Scope-limited to that commit's `git log`, not a standing guarantee |
| `evidence/secret_scan_round0.json` | Secret scan after Round 0 staged | `dd9cde1` | N/A (scan) | Same |

## Earlier project phases (Brief 2 / Patch 2 / Addendum C) -- historical record, not current-build claims

| File | What it is | Commit | prompt_version | Status |
|---|---|---|---|---|
| `evidence/brief2_after_run.json` | Brief 2 benchmark output | `24dcff3` | pre-dates `recordings/` tracking | Superseded by Round 0 |
| `evidence/brief2_patch2_benchmark.json` | Brief 2 Patch 2 benchmark output | `24dcff3` | pre-dates `recordings/` tracking | Superseded by Round 0 |
| `evidence/brief2_patch_benchmark.json` | Brief 2 Patch benchmark output | `24dcff3` | pre-dates `recordings/` tracking | Superseded by Round 0 |
| `evidence/brief2_patch_gapfill.json` | Brief 2 Patch gap-fill cases | `24dcff3` | pre-dates `recordings/` tracking | Superseded by Round 0 |
| `reports/patch2.md` | Patch 2 write-up | `24dcff3` | pre-dates `recordings/` tracking | Historical |
| `reports/patch3_step1.md` | Patch 3 Step 1 write-up | `24dcff3` | pre-dates `recordings/` tracking | Historical |
| `evidence/patch2_reeval_rule_fixes.json` | Patch 2 rule-fix re-evaluation (zero model calls) | `662009f` | N/A (re-scored) | Historical |
| `evidence/patch2_runs.jsonl` | Patch 2 raw run log | `1595d81` | pre-dates `recordings/` tracking | Historical |
| `evidence/patch2_summary.csv` | Patch 2 summary | `0b725fd` | pre-dates `recordings/` tracking | Historical |
| `evidence/addendumC_reeval.json` | Addendum C re-evaluation (zero model calls) | `1595d81` | N/A (re-scored) | Historical |
| `evidence/objective_audit.csv` / `reports/objective_audit.md` | Objective-cascade audit | `24dcff3` | pre-dates `recordings/` tracking | Historical -- findings folded into later work |

## Scratch (recordings only, not an evidence/report artifact -- flagged, not deleted)

`recordings/smoke_facts_ladder/`, `recordings/smoke_addendumC/`, `recordings/smoke_1791098861/`
-- referenced by nothing in `evidence/` or `reports/` beyond incidental mention inside the two
secret-scan JSON files' own file listings. See the separate size/classification report in
chat for detail. Not touched by this index.
