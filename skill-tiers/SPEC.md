# skill-tiers — specification

Status: proposed, not implemented. Vocabulary in [CONTEXT.md](./CONTEXT.md);
the one architectural decision so far in
[docs/adr/0001](./docs/adr/0001-signals-are-mechanical-tiers-are-judged.md).

## What it is for

A skill author points this at a Subject and gets back one page telling them which
Directives are carrying more agent freedom than they warrant, what each one costs
per turn, and what a Bundled Script replacing it would look like.

It answers one question: **where in this skill am I paying an LLM to do something
a script should do?**

## Why it can exist

Anthropic's Agent Skills best-practices page already publishes the rubric, so the
tool does not have to invent one — it applies a documented standard:

- *"Prefer scripts for deterministic operations: Write `validate_form.py` rather
  than asking Claude to generate validation code."*
- *"Match the level of specificity to the task's fragility and variability."* —
  the three Freedom Tiers:
  - **high** (prose): multiple approaches valid; decisions depend on context;
    heuristics guide the approach
  - **medium** (parameterised script): a preferred pattern exists; some variation
    acceptable; configuration affects behaviour
  - **low** (exact script): operations fragile and error-prone; consistency
    critical; a specific sequence must be followed
- *"Once a skill loads, its content stays in context across turns, so every line is
  a recurring token cost."* — Bundled Scripts are executed, not loaded.

Citing the source rubric rather than a private opinion is what makes the report
persuasive, so every reported Tier Gap must name the criterion that triggered it.

## What it is not

- Not a runtime tracer. It never executes the Subject.
- Not a spec/format linter. `agnix`, `thedaviddias/skill-check`, `skillscheck` and
  the JetBrains Skill Inspector already cover frontmatter, naming, links, secrets
  and token budgets, and none of them classify Directives. This tool does the one
  thing they do not, and should not duplicate the things they do.
- Not a scorer. No grade, no pass/fail, no CI gate. It advises an author who is
  editing a skill.
- Not an auto-fixer. It proposes a Bundled Script signature; a human writes it.

## Shape

Two stages, per ADR 0001.

### Stage 1 — `scripts/signals.py` (deterministic, no API calls)

Input: a Subject directory. Output: a machine-readable table of Blocks, one row
per Block, plus Recurring Cost. Prints no Tiers.

Per Block it emits: id, source line range, heading path, a kind guess
(Directive / Exposition / Narration), the Signals matched, and token count.

### Stage 2 — the agent

Reads the table, assigns a Warranted Tier to each Directive by weighing Fragility
and Variability, names the Tier Gaps, and writes the report.

## Segmentation

A Block is **a list item, or a paragraph, within its heading section.** Headings
are too coarse — real skill sections mix Exposition and Directives freely.
Sentences are too fine. The heading path is retained on every Block because
section context is most of what distinguishes the three kinds.

Verified against real skills in this repo: `claude-session-logs`-style bodies are
mostly Exposition under `## File locations` / `## JSONL entry types`, with
Directives concentrated in `## Workflow …` and `### Diagnostic patterns` sections.

## Kind detection

The three-way split happens before any tiering, and getting it wrong is the main
way this tool fails.

**Narration is the trap.** `processing-scanned-receipts` has a `## What It Does`
section listing six numbered, imperative, highly mechanical items — *Extracts*,
*OCRs*, *Caches*, *Generates*, *Renames*, *Flags*. Every script-ability Signal
fires on it. It is documentation of a Bundled Script that already exists. Reporting
it as a Tier Gap would be worse than useless: it would tell the author to script
something they already scripted, and would discredit the rest of the report.

Narration evidence, in rough order of strength:
- the section names a Bundled Script the Subject ships, or sits under a heading
  like *What it does* / *How it works* / *What it reports*
- third-person present verbs (*extracts*, *reports*, *finds*) rather than
  second-person imperatives (*extract*, *report*, *find*)
- the Subject's `## Usage` shows a single command, implying the body describes it

Exposition evidence: no imperative verb; nouns-and-tables shape; headings naming
locations, formats, schemas, types.

When kind is uncertain the script says so rather than guessing; the agent resolves
it. An uncertain Block is never silently dropped.

## Signal catalogue

Evidence only. A Signal never decides a Tier — see ADR 0001.

Toward **low** Warranted Tier (fragile, invariant):
- fenced shell/bash block with fixed flags
- a fixed sequence: numbered items with no branch on judgment
- *always X then Y*, *never*, *exactly*, *in this order*, *do not modify*
- mechanical verbs: parse, format, validate, count, sort, dedupe, rename, convert
- glob and path manipulation
- API or CLI call with fixed parameters
- an objective verification step — schema, count, format, field existence
- **the same command string repeated in more than one Block** (strongest single
  signal, and cheap to detect)

Toward **high** Warranted Tier (judgment, variable):
- decide, judge, assess, consider, prefer
- *if it seems*, *appropriate*, *as needed*, *depends on*, *use your*
- tone, style, phrasing, wording
- summarise, synthesise, explain, describe
- ambiguity resolution; open-ended output

Two documented counterweights the agent must apply, or the tool over-flags:

1. **Fragility is required, not just determinism.** A deterministic Directive that
   is cheap to get slightly wrong stays at high freedom.
2. **Subjective verification stays prose.** The best-practices page keeps style-guide
   checking in prose precisely because the validator is a document Claude reads.
   Flag only objective checks.

## Recurring Cost

Per Block, in tokens, and as a share of the Body. This is the number that makes a
Tier Gap actionable — a fragile Directive costing 15 tokens is not worth a script;
one costing 400 probably is.

Magnitudes are the tool's own. Anthropic names four benefits of Bundled Scripts —
more reliable, saves tokens, saves time, ensures consistency — but supplies no
figures, so the report must not imply otherwise.

## Report

One page. For a human deciding what to edit next, not a machine.

- **Summary** — Body size, Recurring Cost, Directive/Exposition/Narration counts,
  number of Tier Gaps.
- **Top opportunities** — the Tier Gaps, ranked by Recurring Cost × Fragility. Per
  gap: what the Directive says, heading path and line range, As-Written vs
  Warranted Tier, **the best-practices criterion that triggered it**, Recurring
  Cost, and a proposed Bundled Script signature. The docs' own template is the
  model: `generate_report(data, format=..., include_charts=...)`.
- **Correctly tiered** — one line each, so the author can see the tool understood
  the skill and did not simply miss things.
- **Uncertain** — Blocks whose kind or Tier the agent could not settle, with the
  question it would need answered.

Report ids should follow the `category.rule` idiom the neighbouring linters use
(PromptLint's `clarity-vague-terms`, skill-check's `frontmatter.required`) so
output reads as familiar.

## Validation

Dogfood before shipping. This repo is a corpus of ~40 real skills.

1. `processing-scanned-receipts` — must report **zero** Tier Gaps in `## What It
   Does`. If it flags that section, kind detection is not working.
2. `fleet-audit` — already a fully realised script-first skill; should come back
   near-clean, confirming the tool does not flag well-built skills.
3. `commit-organizer` — prose-heavy with genuine judgment (*Group by cohesion*,
   *Triage first when the tree is noisy*) alongside mechanical config lookup;
   should split cleanly across tiers, and is the best test that the tool
   discriminates rather than flagging everything.
4. Its own `SKILL.md` — must survive its own analysis.

The honest measure is precision, not recall: an author will abandon a tool that
tells them to script things that are already scripted or that genuinely need
judgment. **When in doubt, stay silent.**

## Open questions

- Does the Subject's frontmatter `allowed-tools` help? A skill restricted to `Bash`
  is differently shaped from one with none, and this is free to read.
- Should a `references/` file be analysed too? It is loaded on demand, so its
  Recurring Cost differs — arguably out of scope for v1.
- Can a Bundled Script signature be proposed usefully from static text alone, or
  does it need the author's input to be worth printing?
- Is a repo-wide `CONTEXT-MAP.md` warranted here, treating each skill as a bounded
  context, or is a per-skill `CONTEXT.md` enough? Deferred — not this skill's call
  to make for the whole repo.
