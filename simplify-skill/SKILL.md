---
name: simplify-skill
description: Review a skill, AGENTS.md, or CLAUDE.md and propose which instructions can be removed or shortened with minimal behavioural cost. Classifies each chunk by why it would or would not matter — instructions that restate the model's own defaults, instructions it would ignore anyway, and instructions whose value depends on the user's actual workload — and returns that last group as questions rather than guesses. Use when asked to simplify, trim, shrink, prune or de-bloat an instruction file, to find redundant or dead instructions, to check whether a rule is worth keeping, or to cut prompt tokens.
---

You are reviewing an instruction file that you yourself will execute. Every
judgement below must be about what *you* would actually do — not about what a
well-written instruction file ought to contain. Do not evaluate the writing.
Evaluate the behavioural difference.

## Step 0 — Resolve the target and the mode

The user names the file to review. If they did not, ask which one; do not guess.
Read it in full before starting.

Two modes:

- **Core (default).** The file alone. Deletes only what is inert for reasons
  independent of the workload, and returns everything else as a question.
- **With invocations.** The user supplies real past requests this file governed,
  or asks you to harvest them (`claude-session-logs` / `pi-session-logs` can pull
  8–15 real invocations). This resolves the questions mechanically and unlocks the
  headroom check in Step 4.

Offer the upgrade once, briefly, then proceed in core mode unless they take it.

State plainly at the top of your answer which model you are. This method rests on
a model predicting its *own* sensitivity; in the pilot behind it, one model rated
another's largest measured effect at 0.03. If the file is normally executed by a
different model than the one running now, say so and treat the output as weaker
evidence.

## Constraints

- Removals and shortenings only. Do not rewrite the file, do not propose
  additions, restructuring, or wording changes made for style.
- Do not touch frontmatter or the `description:` field. Those govern when the
  skill is retrieved, not what it does, and this review measures nothing about
  retrieval. Trimming a description can silently break triggering while every
  behavioural check still passes.
- Never guess how often a request type occurs. That is the user's knowledge, not
  yours. Surface the condition; let them answer it.
- Propose only. Do not edit the file unless the user asks after seeing the table.

## Step 1 — Chunk

Split the body into the smallest units that could be removed independently. Give
each an id `C1`, `C2`, … and quote its opening words. A chunk is typically one
bullet, one sentence, or one short paragraph. Include chunks you expect to be
essential.

## Step 2 — Classify

Assign each chunk exactly one class. This is the load-bearing step: two chunks can
be equally inert for reasons that differ completely in whether it is safe to delete
them.

- `DEFAULT` — you would behave this way without being told. The chunk restates your
  own disposition. **Independent of workload.**
- `IGNORED` — you would probably not comply with this even when it applies. Say why.
  An instruction you do not follow is dead weight regardless of its quality.
  **Independent of workload.**
- `CONDITIONAL: <condition>` — it changes what you do, but only when something
  specific is true of the request. State that condition precisely and in terms the
  user can check against their own work ("the request involves writing a commit
  message", not "when relevant"). **Depends on workload — you cannot resolve it.**
- `ACTIVE` — it changes what you do on essentially any request this file governs.

Be strict about `DEFAULT` versus `CONDITIONAL`. "I already try to be careful here"
is `DEFAULT`. "I do this only when the request touches X" is `CONDITIONAL`, even if
X feels common.

## Step 3 — Breakage pass (do not skip)

For every chunk you are about to mark `REMOVE` — every `DEFAULT` and `IGNORED` —
answer: what would have to be true of a request for removing it to make your answer
**worse**, not merely different? Consider correctness, tool and command choice,
destructive or irreversible actions, and anything the user would otherwise have to
catch by hand. If nothing plausible exists, write `NONE`.

Treat this as an active search. Models doing this task describe length, format and
content, and reliably fail to notice accuracy risk — including in measured cases
where the instructed run returned a wrong answer and the uninstructed run did not.

## Step 4 — Only in invocation mode

Resolve the `CONDITIONAL` chunks against the actual workload:

- If no invocation satisfies the condition, mark the chunk `REMOVE` and note
  `no invocation triggers this`. Do not upgrade it further; the list may not be
  representative.
- Otherwise, for each triggering invocation give `p` (0.00–1.00): the probability
  that removing the chunk would **materially** change your response to that
  specific request. Material means a reader comparing the two responses blind would
  call the difference substantive, not paraphrase drift.

Then apply the headroom check to every `p` you just gave, and to `ACTIVE` chunks:
does that request's answer leave the chunk **room to act**? An instruction to be
concise cannot change a two-line answer. This is the error you are most likely to
make, so check it on every row rather than at the end.

Verdicts from `p`: max `p` ≤ 0.05 → `REMOVE`; 0.05 < max `p` < 0.5 → `REVIEW`;
max `p` ≥ 0.5 → `KEEP`.

## Step 5 — Output

One table, one row per chunk, sorted `REMOVE` first:

| id | opening words | class | verdict | breakage risk | note |

Verdicts:

- `REMOVE` — `DEFAULT` or `IGNORED`, with breakage `NONE`. In invocation mode, also
  any chunk resolved to `REMOVE` by Step 4.
- `SHORTEN` — the chunk earns its place but spends more words than the behaviour
  needs. Preserve the trigger condition exactly.
- `ASK` — `CONDITIONAL` and unresolved. The `note` column must contain the question
  for the user, phrased so they can answer it from knowledge of their own work:
  *"Does your use of this skill ever involve …?"*
- `REVIEW` — invocation mode only, 0.05 < max `p` < 0.5.
- `KEEP` — `ACTIVE`, or max `p` ≥ 0.5, or **any** breakage risk touching
  correctness, tool choice, or destructive actions, at any probability.

Then, for `REMOVE` and `SHORTEN` rows only, give the exact current text and the
exact replacement (empty for `REMOVE`), so the edit can be applied mechanically.

Close with one line: the count per verdict, and the approximate share of the body's
words that `REMOVE` + `SHORTEN` would cut.

Finally, offer to apply the `REMOVE` and `SHORTEN` rows, and to answer the `ASK`
rows together. Apply nothing until the user says so.

## On your incentives

You are not being asked to please the author, and "this is a reasonable
instruction" is not a reason to keep it. The only question is whether your
behaviour changes without it.

Err toward `KEEP` and `ASK`. A chunk wrongly kept costs tokens; a chunk wrongly
removed costs a regression that may go unnoticed for weeks. `ASK` is never the
wrong answer when the condition is genuinely outside your knowledge.

## Why the steps are shaped this way

From a 130-call with/without experiment over 5 deployed models
(`~/prg/instruction-reflection-pilot`, `docs/findings/2026-07-21-first-full-run.md`):

- Models predict their own sensitivity to an instruction well — pooled Brier 0.057
  against a 0.210 base-rate baseline — but roughly twice as well as they predict
  another model's (0.113), which is why this is self-review only.
- Judgements that did not depend on the task had **zero variance across tasks in
  all five models**; task-dependent ones ranged 0.00 to 0.97. That is why core mode
  can skip the workload for `DEFAULT`/`IGNORED` and must not for `CONDITIONAL`.
- An instruction that restates a default and one that simply never fires look
  identical from outside. Step 2 separates them because only the first is safe to
  delete blind.
- The two measured failure modes are the headroom blind spot (Step 4) and never
  spontaneously flagging accuracy risk (Step 3). One model returned a wrong
  arithmetic total under an instruction it had rated 0.00 for any effect.

The `REMOVE` band matched reality 29/30 times in that run. The `REVIEW` band is
exactly where predictions failed. This skill itself has not been validated.
