# UI copy corrections (pending documentation pass)

Logged here, not fixed yet, per instruction -- fix together in the documentation pass.

## E.3 — day-report screen's baseline-match explanation

**Location:** the day-report screen's explanation of why the `same_objective_baseline` and
`fixed_cost_baseline` columns show the same numbers.

**Wrong:** "the declared objective was already cost [efficiency]."

**Right:** the two baselines matched on the 12-row example day because the transmission/sell
cap binds on every one of that day's surplus ticks (sellable_surplus_mw < total battery
charge capacity there -- 12.0 < 16.0 -- see D.5, `evidence/day_report_example.json` and
`reports/round1.md`'s D.4/D.5 discussion), not because the declared objective happened to be
`cost_efficiency`. D.5's own follow-up probe (`evidence/baseline_divergence_probe.json`)
confirms the mechanism itself is live: on a swept set of surplus states where the sell cap is
NOT binding (sellable_surplus_mw > total charge capacity), 30/31 states diverge sharply
between `max_profit` and `cost_efficiency` (max_profit sells the full surplus and never
charges; cost_efficiency charges to its 16 MW cap first and sells only the remainder) --
declaring an objective does reach the dispatch. The 12-row day's baseline match is a
property of that specific day's surplus/charge-cap ratio, not a sign the objective cascade
is inert.
