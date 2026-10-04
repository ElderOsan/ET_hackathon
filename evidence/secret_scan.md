# Secret scan (Patch 3 addendum)

**Tool:** `detect-secrets` 1.5.0 (installed into `backend/.venv`, not a runtime dependency —
not added to `requirements.txt`).
**Date:** 2026-10-04
**Scope:** all 74 git-tracked files (`git ls-files`) + a full-history check for `.env`.

## Result: 0 real secrets found.

**`backend/.env` was never committed, at any point in history:**
```
git log --all --full-history -- "**/.env" "backend/.env"
```
returns nothing. It is, and has always been, `.gitignore`d.

**10 raw findings, all false positives, individually verified:**
- `recordings/*/calls/*.json` (9 findings) and `recordings/*/manifest.sha256` — flagged as
  "Hex High Entropy String." These are `cache_key`/`scenario_hash`/`prompt_version` fields
  (SHA-256-derived hex digests) and the manifest's own file hashes — legitimately
  high-entropy by design, since that's what a hash is. Not credentials.
- `backend/tests/test_recording.py` line 92 — a deliberately-constructed fake `AQ.`-shaped
  key used to test the scrub pattern (`test_03c_scrub_redacts_aq_shaped_key_generically`),
  not a real one.

## Key-leak defense in `app/data/recording.py::scrub()`

Two shape patterns (`AIza...` classic Google Cloud key, `AQ....` AI Studio key — this
project's actual format) plus a literal scrub of the exact key used for a given call. All
recorded files pass through `scrub()` before being written to disk; `test_recording.py`
covers both the shape patterns and a literal scrub of this project's real configured key.

Scanning `.venv`/`node_modules` was tried first and produced ~124 files of pure noise from
third-party packages' own SBOM/license hashes — excluded since those are gitignored and
never reach git history anyway; the scan above is scoped to exactly what's actually tracked.
