# Cross-Objective Audit (Addendum B)

Report only, no code changes, no model calls — all from the stored 72-row benchmark
(`evidence/brief2_patch2_benchmark.json`, current rule state including the floor/rule_2b/dispatcher
fixes) and direct re-computation via `reference_dispatch`/`dispatch_at_floor`.

## A. Alignment table

| | cost_efficiency | min_carbon | max_renewable_utilisation | max_profit |
|---|---|---|---|---|
| **Prompt sentence** | "cost, then carbon, then renewable utilisation" — **no formula given** | "carbon, then cost, then renewable utilisation" — **no formula given** | "renewable utilisation, then cost, then carbon" — **no formula given** | "profit, then cost, then carbon... Profit is sale revenue minus purchase cost for this tick..." — **the only objective with an explicit formula** |
| **rule_9 metric** | `purchase_mw × buy_price` (sales never counted) | `purchase_mw` raw MW (a proxy — no `carbon_price_per_ton`, no carbon intensity) | `curtailed_mw` (lower = better) | `sale_revenue − purchase_cost` (single-tick, `physics.decision_profit`) |
| **Reference best** | `dispatch_at_floor(...).market_amount_mw` (buy side) | **same dispatcher call as cost** — identical MW number, different units | `physics.min_required_curtailment_mw` — **does NOT go through the dispatcher at all** | `dispatch_at_floor(...)` revenue − cost (max_profit's own sell-first ladder) |
| **Reference worst** | shortfall × buy_price, zero battery help | shortfall MW, zero battery help | `generation − demand` (entire surplus), zero sale | worst cost − zero revenue |
| **Tolerance (N/A test)** | `max(\|best\|,1) × 5%` | same | same | same, **plus an extra OR clause** (`\|best\|<tol and \|actual\|<tol`) the other three don't have |
| **Tolerance (pass/fail)** | scale-relative (5% of best) | scale-relative | **flat `CURTAIL_TOLERANCE_MW`=0.5MW — does NOT use the scale-relative tolerance computed just above it** | scale-relative |
| **Agree with each other?** | — | **cost and carbon are mechanically the same reference** (see below) | **inconsistent construction** (bypasses dispatcher) and **inconsistent tolerance mechanism** | has an N/A safety net the others lack |

**Direct answers to the specified questions:**
- **Are cost_efficiency and max_profit actually different?** Yes, genuinely. Cost ignores sales entirely; profit nets sales against purchases. Confirmed not a duplicate.
- **Does min_carbon ignore the carbon price, and is that stated anywhere?** Yes it ignores `carbon_price_per_ton` completely — the metric is raw import MW, not a priced or intensity-weighted quantity. **Not stated anywhere** — the prompt never discloses the carbon metric's formula, and `carbon_price_per_ton` is sent to the model with no stated purpose. Worth noting: cost and carbon currently share the *identical* underlying MW quantity (`min_grid_import_mw`/`worst_grid_import_mw`) — they are monotonically related and will essentially never disagree on which decision is "better," since there is no independent carbon dimension (price or intensity) in the current formula.
- **Does stored energy count as utilised? Does selling count?** Implicitly yes to both — the metric is purely curtailment avoidance, and neither storing nor selling is curtailment. But "utilisation" is never computed as an explicit ratio, and this is never stated to the model.
- **How does the prompt say stored energy is valued, for any objective?** It doesn't, anywhere. This is the one gap common to all four objectives, and it's the direct cause of the "charges instead of selling, believing it preserves value" pattern already reported for `max_profit`.

## B. Reference fairness checklist

| Item | cost | carbon | renewable | profit |
|---|---|---|---|---|
| Same applied floor | pass | pass | pass | pass |
| Same battery rate/SoC limits | pass | pass | pass | pass |
| Offline batteries respected | pass | pass | pass | pass |
| Transmission headroom respected | pass | pass | pass | pass |
| Same info as the model | pass | pass | pass | pass |
| Emergency handling | **FAIL — see finding below** | **FAIL (same ladder)** | n/a (surplus-side) | **FAIL (same ladder)** |
| Single-tick horizon | pass (matches the model's own current metric) | pass | pass | pass |
| Worst-feasible construction | consistent, but never routed through the dispatcher (own direct formula) — same for all four |

**Finding (reference defect, confirmed with a reproducing case — tick 46, seed 20291305):** the dispatcher's shortfall ladder (`dispatcher.py::_shortfall_ladder`) computes grid import **before** checking emergency battery discharge, even though its own docstring says the opposite ("use free battery capacity before paying for grid import"). At tick 46: shortfall 5.7MW, transmission headroom 2.0MW, battery_1 has 10MW of *emergency* discharge headroom available (SoC 31.2%, well above the 10% absolute floor) but zero *non-emergency* headroom (SoC already below the 45% applied floor). The ladder imports 2.0MW ($555) before ever checking emergency capacity, then uses emergency discharge only for the remaining 3.7MW — when the entire 5.7MW shortfall was coverable by free emergency battery discharge alone. The model's actual decision (discharge 5.7MW, buy nothing, $0 cost) is objectively better than the reference's own "best" ($555 cost) for this exact reason. This is a **reference defect**, not a model error — flagged for a fix decision, not fixed here.

## C. Coverage (active vs. N/A rule_9, by profile)

| Objective | Total | Active | N/A | Pass rate (active) | Pass rate (all) |
|---|---|---|---|---|---|
| cost_efficiency | 18 | 10 | 8 | 90.0% | 88.9% |
| min_carbon | 18 | 9 | 9 | 100.0% | 100.0% |
| max_renewable_utilisation | 18 | 7 | 11 | 71.4% | 88.9% |
| max_profit | 18 | 16 | 2 | 43.8% | 50.0% |

Coverage is wildly uneven — `max_profit` is active in 16/18 rows (it almost always has a real decision to judge), while `max_renewable_utilisation` is active in only 7/18 (mostly N/A because most profiles have no surplus to curtail or sell). Pass rates are **not comparable across objectives** as instructed; `max_profit`'s much lower rate partly reflects simply being judged far more often, not necessarily worse performance per judged instance.

## D. Row review (classifications)

**cost_efficiency non-pass (2, not 3 — one of the original 3 flipped to pass via the floor fix):**
- tick 27 (price_spike): `rule_5` flagged — avoidable charging at a price peak. **Model strategy error.**
- tick 38 (multi_failure_cascade): `rule_3`/`rule_10` FAIL — over-imported past transmission headroom, 3.7MW unserved. **Arithmetic error** (already classified in the Step 6 report).

**min_carbon non-pass: 0.** Every min_carbon row passes — consistent with carbon and cost sharing an identical reference (see A); nothing here independently stresses a carbon-specific path.

**max_renewable_utilisation non-pass (2):**
- tick 32 (price_spike): `rule_8b` — floor outside the expected band. **Unrelated to the objective** — a floor-calibration flag, not a renewable-utilisation judgment.
- tick 55 (surplus_day): `rule_6`/`rule_9`/`rule_10` FAIL — unforced curtailment with 180MW of free headroom available. **Model strategy error** (already classified).

**max_profit non-pass (9, previously reported):** all `rule_9`, mostly the "charges instead of selling" misreading (6 rows) plus 3 surplus_day rows that sold only part of the achievable surplus. No new classification beyond what's already reported — all **model strategy errors**, confirmed not reference artifacts (these are all surplus-side rows, unaffected by the shortfall-ladder bug in B).

**3 passing + rule_9-active rows per objective (false-pass check):** cost_efficiency and min_carbon's sampled rows are clean ($0 vs $0, or exact matches) — no false passes found. `max_renewable_utilisation`'s sample (ticks 7/8/9) are genuine zero-curtailment passes. `max_profit`'s sample includes **tick 46 — the reference-defect row above**: it passes, but for the wrong reason (the reference is broken, not because the model's own performance was verified against a sound baseline). This is exactly the kind of false-pass-for-the-wrong-reason the review was designed to catch.

## E. Tolerance calibration (gap ÷ tolerance, active rows only)

| Objective | 0–0.5 | 0.5–1 | 1–2 | >2 |
|---|---|---|---|---|
| cost_efficiency | 10 | 0 | 0 | 0 |
| min_carbon | 9 | 0 | 0 | 0 |
| max_renewable_utilisation | 6 | 0 | 0 | 1 |
| max_profit | 7 | 0 | 0 | **9** |

Cost and carbon are extremely clean — every active row is well within tolerance (consistent with "the model gets this right" rather than "the tolerance happens to be forgiving"). **`max_profit` is the outlier: 9 of 16 active rows miss by more than 2× the tolerance** — not a borderline calibration issue, a large, consistent gap. Combined with the row review (D) and the already-reported "charges instead of selling" misreading, this looks like a real, severe strategy gap on this specific objective, not a tolerance-setting problem — though the tick-46-style reference defect means at least one row's gap size is not to be trusted at face value.

## F. Interactions

- **rule_5** (no-avoidable-charging-at-a-price-peak): applicable only for `cost_efficiency` and `max_profit` (18/18 each), N/A for `min_carbon`/`max_renewable_utilisation` (18/18 each) — by design (Patch 2 Step 3), since neither carbon nor renewable framing trades off against price-peak charging the way cost does.
- **rule_2b** (battery below its own applied floor outside an emergency): applicable for **all four objectives, always** (18/18 each) — no objective-based gating, since battery-floor discipline is a golden-rule-adjacent concern independent of the declared cascade.
- **tick 32** (`rule_8b`, price_spike, max_renewable_utilisation): proposed floor 25% against an expected 30–45% band. This is a floor-band miscalibration flag, unrelated to the renewable objective itself — the same kind of flag that could occur under any objective.

## Summary of fix candidates (not implemented, awaiting one combined approval)

1. **Reference defect:** shortfall ladder imports before checking emergency battery discharge — confirmed, reproducible (tick 46).
2. **Reference defect:** `max_renewable_utilisation`'s "best" bypasses the dispatcher (uses a separate physics formula) — inconsistent construction vs. the other three objectives.
3. **Rule defect:** `max_renewable_utilisation`'s pass/fail tolerance is a flat 0.5MW, not the scale-relative tolerance used for cost/carbon/profit — inconsistent mechanism.
4. **Prompt/definition gap, all four objectives:** no objective's formula is ever stated to the model, and no objective states how (or whether) stored energy has value. This is the root cause of the `max_profit` "charges instead of selling" pattern and likely degrades cost/carbon too, just less visibly since their rule_9 numbers happen to already be clean.
5. **Definition gap, min_carbon specifically:** the carbon metric ignores `carbon_price_per_ton` and uses import MW as a raw proxy — addressed by Addendum C's carbon-intensity proposal, not decided here.

None of these were fixed in this pass, per instruction. Stopping here and waiting for direction.
