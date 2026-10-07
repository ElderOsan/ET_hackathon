# Ladder-reword probe: before/after (seed 777001)

## Scenario (unchanged between the two runs)

Tick 1, seed 777001, `D4_SURPLUS_DAY`:

| generation_mw | demand_mw | surplus_mw | transmission_headroom_mw | sellable_surplus_mw |
|---|---|---|---|---|
| 122.0 | 93.4 | 28.6 | 180.0 | 28.6 |

Transmission headroom (180.0 MW) is well above the surplus (28.6 MW), so the full surplus is
genuinely sellable — this is not the earlier audit-H probe's degenerate case where sellable
surplus exactly equaled charge headroom plus transmission headroom with nothing left over to
choose between selling and charging.

## Before vs after

"Before" = `audit_h_cross_objective_probe.py`'s run against this same seed, pre-reword
(prompt commit before 678c109). "After" = `probe_ladder_reword.py`, post-reword (678c109:
objective-dependent surplus ladder — `max_profit` sells before charging; every other
objective charges before selling), 3 samples per objective, all 12 calls `pass`.

| objective | before: sell / charge MW | after: sell / charge MW |
|---|---|---|
| cost_efficiency | 12.6 / 16.0 | 12.6 / 16.0 |
| min_carbon | 12.6 / 16.0 | 12.6 / 16.0 |
| max_renewable_utilisation | 12.6 / 16.0 | 12.6 / 16.0 |
| max_profit | 12.6 / 16.0 | **28.6 / 0.0** |

Full post-reword per-row data (all 3 samples per objective, all identical within each
objective) is in [`evidence/ladder_reword_probe.json`](../evidence/ladder_reword_probe.json);
live recordings are under `recordings/probe_ladder_reword/`.

## What this demonstrates

The ladder reword worked as intended for the one case it targeted: with a real sell-vs-charge
choice available, `max_profit` now sells the entire sellable surplus (28.6 MW) and charges
nothing, where before the reword it matched the other three objectives exactly (12.6/16.0).
This was confirmed live, 3/3 samples, not just read off the prompt text or the dispatcher's
code.

## What this does not demonstrate

This is a single scenario (one tick, one seed) under one specific surplus/headroom
configuration — it shows the reword changes behavior in at least this case, not that it holds
across all surplus configurations, nor that it's stable under different demand/price/battery-
SoC combinations. It also does not address the separate, previously-flagged finding that
`cost_efficiency`, `min_carbon`, and `max_renewable_utilisation` remain indistinguishable from
each other on this kind of state (all three produced byte-identical sell/charge numbers both
before and after the reword) — the reword was never intended to fix that, and it hasn't. No
rule, tolerance, balancer, or dispatcher logic was touched to produce this result; it reflects
the prompt-wording change alone.
