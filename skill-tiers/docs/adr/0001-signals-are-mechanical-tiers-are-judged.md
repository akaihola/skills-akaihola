# Signals are extracted mechanically; Tiers are judged by the agent

Deciding a Warranted Tier requires weighing Fragility and Variability, which are
properties of the Subject's problem domain and are not recoverable from its text —
so a pure regex linter would have to guess, and would over-flag every Directive
that merely looks mechanical. Deciding it entirely inside the model instead would
make the report unreproducible and would have this skill fail its own advice, since
segmenting a Body, matching Signals and counting tokens are exactly the
deterministic operations it tells others to bundle as code. We therefore split the
work: a Bundled Script performs segmentation, Signal extraction and Recurring Cost
measurement and emits a table of evidence, and the agent reads that table to assign
Warranted Tiers and name Tier Gaps.

## Consequences

The script must never print a Tier — if a future contributor adds a
`--tier` column to its output, this decision has been silently reversed. The
script's output is evidence and is expected to be verbose; only the agent's report
is written for a human.
