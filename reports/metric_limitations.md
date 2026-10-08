# Known metric limitations (not agent defects)

Logged here rather than left only in chat, so the write-up has a citable source.

## E.6 — max_profit's profit divergence is bounded by round-trip charge loss, not a trading gain

**Context:** D.5's surplus-sweep probe (`evidence/baseline_divergence_probe.json`,
`backend/scripts/probe_baseline_divergence.py`) found 30/31 states where `max_profit` and
`cost_efficiency` dispatch diverge sharply (sell-everything vs charge-to-cap-then-sell), but
cost/emissions/curtailment/renewable-utilisation are identical on every state -- only profit
moves.

**Hypothesis checked and CONFIRMED:** the profit delta is exactly the avoided round-trip
charging loss, not an optimisation win over the same economic outcome.

`decision_profit()` (`backend/app/data/physics.py`) values stored energy at
`sell_price_per_mwh` (Addendum C, point 2) -- the same price a sale earns. So selling now and
charging now are valued identically per the model's own definition, EXCEPT for charging
efficiency, which is strictly lossy.

Probe state (seed 777001, D4_SURPLUS_DAY): `electricity_price_per_mwh=25.3`,
`sell_price_per_mwh=24.04`, `TICK_HOURS=0.25`. Batteries: `battery_1` 10.0 MW / 92% charging
efficiency, `battery_2` 6.0 MW / 90%.

At the plateau (surplus >= 16 MW, both baselines' battery actions saturate at the 16 MW total
charge cap either way):
- bus-side energy drawn charging to the cap: `16.0 MW x 0.25h = 4.0 MWh`
- energy actually stored: `10.0x0.25x0.92 + 6.0x0.25x0.90 = 2.3 + 1.35 = 3.65 MWh`
- round-trip loss: `4.0 - 3.65 = 0.35 MWh`
- loss valued at sell price: `0.35 x 24.04 = $8.414`

Observed plateau in the probe: diffs oscillate **$8.40-$8.50** across surplus=16..60 (per-tick
`net_profit` is rounded to 1 decimal at each of 3 intermediate steps -- revenue, stored_value,
net_profit -- independently for each baseline, which is exactly the rounding noise band
around the unrounded $8.414; it is not a second mechanism). This reproduces the hypothesis:
**confirmed, not refuted.**

**Framing for the write-up (as instructed, a metric boundary, not an agent one):**
`decision_profit()` values stored energy at the CURRENT tick's sell price. It therefore can
never credit charging with the thing an operator actually charges during a price spike for --
selling that same energy LATER at a HIGHER price. Under this definition, charging can only
ever look like a same-tick opportunity cost (the round-trip loss), never a forward-looking
gain. That means, as implemented, `max_profit` dispatch can only ever prefer selling over
charging on a surplus tick, and the profit divergence the cascade produces is bounded above
by the round-trip loss on whatever MW get reallocated from charge to sell -- not by any
larger trading gain. This is a boundary of the metric as defined (no time-value-of-stored-
energy term), not a bug in the dispatcher, the balancer, or the agent.

**Does not weaken D.5:** the 30/31 divergence result stands -- the dispatch genuinely branches
on the declared objective. This note bounds what that divergence is worth in dollars, not
whether it exists.
