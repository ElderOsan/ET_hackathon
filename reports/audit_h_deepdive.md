# Audit H deep-dive — report only, no changes

Follow-up on `evidence/audit_h_cross_objective_probe.json` (the 24-call cross-objective
probe). All data below comes from the already-recorded calls under
`recordings/audit_h_cross_objective/` — zero new model calls.

## 1. Prompt diff: surplus state, cost_efficiency vs. max_profit (sample 0)

Exactly two lines differ between the two rendered prompts: the declared-objective line and
the `"objective"` field inside the JSON (`cost_efficiency` → `max_profit`). Every other byte
— including all physics facts (`sellable_surplus_mw: 28.6`, `total_charge_headroom_mw:
16.0`) — is identical. The two calls received the same state; the only input difference was
the objective label itself.

## 2. Full reasoning text, both cells

**cost_efficiency:** *"Position: surplus (net_position_mw = 28.6 MW). Following surplus
ladder: serve load, then charge batteries (battery_1: 10 MW, battery_2: 6 MW), then sell
remaining surplus to the grid (12.6 MW). Golden Rules 1, 2, 3, 4 are respected (no
curtailment, within transmission headroom, valid battery rates). Objective is
cost_efficiency, prioritized via cost-effective battery charging and selling surplus."*

**max_profit:** *"Position is surplus (net +28.6 MW). Following surplus dispatch ladder:
serve load, charge batteries to max capacity (battery_1: 10 MW, battery_2: 6 MW), then sell
remaining surplus (12.6 MW) to the grid. Golden rules 1, 2, 3, and 4 respected (no
curtailment, no buying, headroom respected). Objective is max_profit: prioritizing profit
via charging and selling at sell_price_per_mwh."*

Both reasonings **name** the declared objective. Neither **justifies** charging 16MW over
selling more — both describe the identical generic "charge-then-sell" ladder and append a
one-clause objective label at the end. Neither acknowledges that max_profit's own prompt
sentence calls for the opposite order (sell before charge). This reads as the same reasoning
with a different label attached, not objective-sensitive reasoning.

## 3. Shortfall probe: could cost and carbon actually disagree?

No. Price was **$244.7/MWh** (near the top of the shortfall_day range, not cheap) and carbon
intensity was **0.55 t/MWh** (just under the 0.3–0.9 range's 0.6 midpoint, not high). This is
"expensive + roughly average," not "cheap + dirty" — minimizing import was simultaneously
cost-optimal and carbon-optimal here, so there was no real trade-off for the objectives to
diverge on. **This invalidates the shortfall half of the probe** as a test of cost-vs-carbon
divergence — a coincidence of the fixed seed, not a designed trade-off.

## 4. Is "charge 16.0MW" a cap or a choice?

The cap: `total_charge_headroom_mw` was exactly **16.0** (battery_1's 10.0 + battery_2's 6.0)
in the recorded physics facts, matching the charged amount precisely. The **magnitude** was a
hard cap, not a free choice — the model maxed out both batteries' charge headroom. What
remained a genuine (uncapped) choice was the **order**: charge-to-cap-then-sell-leftover vs.
sell-the-full-28.6-then-charge-0 (which max_profit's own prompt sentence prescribes). The
original finding narrows to: the model chose the generic ladder's order under every
objective, not that it picked an arbitrary charge amount.

## 5. Regression check (Step 6 re-run, after the profit fix and file-input build)

| Check | Before | After | Changed? |
|---|---|---|---|
| Oracle (200 scenarios) | 143/200 = 71.5% | 143/200 = 71.5% | no |
| Fault injection | 70/72, 0 false alarms | 70/72, 0 false alarms | no |
| Determinism (both checks) | True | True | no |
| Prompt audit | 0 findings | 0 findings (184 calls now, up from the added file-input/audit-H recordings) | no |
| `pytest` | 125/125 | 125/125 | no |

No regression anywhere.
