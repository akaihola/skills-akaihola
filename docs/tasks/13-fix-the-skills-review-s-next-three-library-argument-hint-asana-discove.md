Steward issue, 2026-10-19. Drafts D19, D4 and D6 of [9]'s review, `docs/reviews/2026-10-19-skills-review.md`, the next three by its ranking after D1, D18 and D2 ([10]-[12]). They are small, so they go together: one commit per draft.

## D19. Quote the library argument hint so frontmatter parses

Evidence: `library/SKILL.md:4` contains two unquoted bracketed expressions.
`yaml.safe_load` rejects this frontmatter with `ParserError`; the other 47
frontmatters parse. The description still can be measured independently, but a
strict loader cannot parse the complete metadata.

Draft title: **Repair library frontmatter and validate all skill metadata.**
Work: quote the hint; add a small offline metadata check covering every tracked
skill with useful path-specific failures. Acceptance: all 48 frontmatters parse,
required names/descriptions are strings, and an invalid synthetic hint fails.
Benefit: restores strict-loader compatibility and detects this class of breakage
before discovery. Estimate: 1 hour. Overlap: none.

## D4. Stop discovering Asana as an implemented operational skill

Evidence: `asana/SKILL.md:3` advertises task creation and updates, while
`asana/SKILL.md:8` says implementation does not exist. The three scripts named
at `asana/SKILL.md:17` are absent. This is a known design, not a missing
runtime dependency.

Draft title: **Move the unimplemented Asana workflow out of automatic discovery.**
Work: retain the design in its README; make the discoverable entry explicit
about design-only status or remove it from operational skill registration.
Acceptance: an Asana task query cannot lead an agent to run absent scripts;
the architecture remains available for explicit planning. Benefit: avoids a
certain dead end. Estimate: 0.5 to 1 hour. Overlap: none.

## D6. Document and test the real ECB command

Evidence: `ecb-rates/SKILL.md:12` advertises `fetch-rates [YEAR]`, but no such
wrapper is tracked. `ecb-rates/fetch_ecb_rates.py:4` names the actual invocation
and its extra dependency. `ecb-rates/fetch_ecb_rates.py:78` parses the first
argument as an integer and retains the 2025 default. Historical data is valid;
an unexplained fixed year is the stale expectation.

Draft title: **Give the ECB helper a documented CLI and offline fixture.**
Work: use the actual script path, expose year/output arguments through argparse,
state the historical-year policy explicitly and declare the XML dependency.
Acceptance: help exits before any fetch; an invented local XML fixture produces
the expected ordered CSV; the documented command matches the parser. Benefit:
removes a missing-command failure and makes the requested year explicit.
Estimate: 1 hour. Overlap: none.