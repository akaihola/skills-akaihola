# T3 helper architecture review

The best return is to retire V1 server support while retaining old request
records, then bring launch and send recovery under one owner. Keep the helper
as one script. A transport framework, persistent socket pool, or separate class
for each command would add interfaces without hiding useful complexity.

## Scope and baseline

Reviewed `main` at `8e45bbda384ace41013fce0cd8f4c7105dfec9bb`.
Every line citation below refers to that revision, including citations in
drafts. Repository-relative links open the corresponding file; use the baseline
commit when its current line numbers differ.

Read all 667 lines of [t3-start-thread/scripts/start_thread.py][code], all 1,199
lines of [t3-start-thread/tests/test_start_thread.py][tests],
[t3-start-thread/SKILL.md][skill], and
[t3-start-thread/references/helper.md][reference]. Also read the
[V1/V2 migration task][protocol-task], [settlement task][settle-task],
[child-task routing task][routing-task], and the relevant portions of the
[collection review][collection-review] and [documentation review][docs-review].

Applied Honey's deletion and stdlib-first principles. No `codebase-design`
skill was available in this session; the vocabulary used here is explicit:
a **deep module** hides substantial policy behind a small interface;
**information leakage** makes callers know that policy;
**temporal coupling** requires operations in a particular undocumented order.
These are design judgments, not measurements of production failures.

V2-only deployment is a premise supplied by this task, not independently
verified. This review made no T3 calls and performed no vulnerability probes.
The existing fake-server suite passed: **100 tests** with networking disabled.
The [review task record][review-task] records the command and resource checks.
No implementation or test files were changed.

## Boundaries worth keeping

- **Session and RPC:** `Server` already hides authentication, tickets, request
  correlation, Ping/Pong, deadlines and socket cleanup behind `call()`:
  [t3-start-thread/scripts/start_thread.py, lines 76–193][code]. Keep that
  boundary. It opens one socket per RPC; a single invocation's bearer session
  is shared. Reusing sockets would require a new subscription lifecycle, with
  no measured need in this review.
- **Durable handoff:** saving IDs before dispatch and reconciling after a lost
  reply are essential behavior, not incidental boilerplate:
  [t3-start-thread/scripts/start_thread.py, lines 348–427][code]. Launch and
  send should share ownership of that policy while preserving their different
  output formats.
- **Settlement:** the batch is a different operation. It intentionally has no
  request record and refreshes the shell before each target. Retain independent
  errors, pending-question refusal, archived-target refusal, dry-run behavior
  and server rejection handling:
  [t3-start-thread/scripts/start_thread.py, lines 294–345][code]. Share transport
  and activity interpretation; do not force settlement into handoff recovery
  or cache the whole batch's eligibility snapshot.
- **CLI and target routing:** `argparse`, `pathlib`, JSON and `urllib` already do
  the ordinary work. `paced_thread()` hides the Hai-to-launch-record join and
  ambiguity policy behind a single result:
  [t3-start-thread/scripts/start_thread.py, lines 35–73 and 565–644][code]. Its
  single caller does not make it a useless abstraction. The tiny
  `all_threads()` helper likewise names the archived-recovery rule. Neither
  needs a generic repository, resolver registry or command framework.

## Findings by benefit per hour

Each finding has an approximately one-agent-hour draft below. Savings are
maintenance and fewer state transitions; no production latency claim is made.

- **F1 — Remove live V1 compatibility, retain saved records. Highest return.**
  Evidence: [t3-start-thread/scripts/start_thread.py, lines 112–139][code]
  starts every invocation without a protocol, attempts V1, then recursively
  retries V2 with a fresh ticket after a specific rejection. Protocol state
  escapes `Server` into `dispatch()` at lines 201–204 and `submit()` at
  lines 365–373. V1 thread normalization and activity interpretation remain at
  lines 188–193 and 280–290. The all-command test matrix doubles server
  variants at [t3-start-thread/tests/test_start_thread.py, lines 565–575][tests].

  The present deployment no longer needs this live-server variation. Fixed
  V2 transport removes the first rejected connection/ticket per invocation
  and the caller requirement to discover the protocol before dispatch.
  However, newly saved commands are still V1-shaped at
  [t3-start-thread/scripts/start_thread.py, lines 448–460 and 508–557][code].
  Deleting `bootstrap` handling or the V2 translation at lines 205–242 would
  break both current and older records. Keep the existing record format and
  its translation; do not combine retirement with a record-schema migration.

  **Recommendation:** do D1 first. Remove the obsolete server dimension,
  update the protocol claims, and keep identifier-preserving resume tests.
  Preserve summary keys and settlement guards until their contracts are
  deliberately changed; a legacy-looking field alone is not proof it is dead.

- **F2 — Give launch and send one reconciliation policy. High return.**
  Evidence: [t3-start-thread/scripts/start_thread.py, lines 359–389 and
  392–427][code] independently perform observe, refuse an acknowledged-but-
  absent result, dispatch, save acknowledgement, observe again, save summary
  and print. The launch route additionally inspects `server.protocol` and
  infers operation kind from `bootstrap`.

  The duplication already permits different completion rules. On V2, an
  existing launch checks its initial message at lines 368–373; after a new
  dispatch, lines 381–389 check only that the thread exists. Send checks the
  exact message after dispatch at lines 406–410. The fake suite tests partial
  launch recovery and pre-existing acknowledged-but-missing results at
  [t3-start-thread/tests/test_start_thread.py, lines 773–844][tests], but does
  not simulate an acknowledgement followed by a visible thread whose initial
  message is still absent.

  One record-oriented reconciler can hide IDs, acknowledgement persistence
  and no-replay policy from `start`, `send` and `resume`, with an explicit
  launch/send branch for observing results and formatting output. The visible
  change is that a newly acknowledged partial launch asks the caller to resume
  instead of presenting thread visibility as completed reconciliation. This
  makes initial submission obey the same persistence rule as resume; it is a
  small behavior correction, not just line deletion.

  **Recommendation:** do D2 after D1. Keep the existing CLI and successful
  output shapes. Avoid callback-driven workflows, operation subclasses or a
  generic retry loop; none is needed for two operation kinds.

- **F3 — Stop fetching shell metadata to test message existence. Medium return.**
  Evidence: [t3-start-thread/scripts/start_thread.py, lines 183–193][code]
  fetches a V2 thread projection, then a shell snapshot, and merges them on
  every `thread_snapshot()` call. `submit_message()` invokes it both before
  and after dispatch, at lines 396 and 406. Launch resume has just read a
  shell at line 365 when line 369 causes another shell read indirectly.
  This hides an extra network operation and mixes observations from two times.

  A successful fresh V2 send currently uses six successful RPCs: initial shell,
  pre-send detail and shell, dispatch, post-send detail and shell. This count is
  derived from [t3-start-thread/scripts/start_thread.py, lines 183–193,
  392–415 and 614–620][code]; it excludes the initial failed V1 handshake.
  Pre-send message existence needs the projection's message IDs, not another
  shell. Separate that observation from summary assembly. Keep a fresh
  post-dispatch summary, reducing this path to five RPCs; reuse the shell
  already read during launch resume, reducing that successful reconciliation
  from three RPCs to two.

  **Recommendation:** do D3 after D2 establishes observation ownership. Keep
  projection/shell merge precedence and archived lookup in one narrow place.
  Do not add a session cache, remove post-dispatch freshness, or change
  settlement's per-target refresh. This is a bounded call reduction, not a
  proposal to optimize every lookup.

- **F4 — Consolidate overlapping fakes after retirement. Lower return.**
  Evidence: [t3-start-thread/tests/test_start_thread.py, lines 24–159][tests]
  has a V1 `LostReplyServer` with launch tests; lines 162–366 add a V1
  `MessageServer` with send tests. `WireServer` at lines 385–575 and CLI tests
  at lines 603–697 exercise overlapping lost-reply, settings, workspace and
  delivery cases through the actual helper transport. Maintaining three fake
  implementations makes a protocol change touch several descriptions of
  acceptance and message persistence.

  Migrate the unique assertions into the V2 wire fixture, then delete the two
  older fake classes and redundant setup. Preserve the pre-acceptance loss
  case (lines 338–352), identical-text/different-ID case (lines 226–228 and
  264–269), settings rejection (lines 144–147), record permissions, dry-run
  output checks, and target validation. The fake needs a bounded failure
  switch, not a configurable simulation framework. Passing fewer parametrized
  cases is justified only when the removed dimension is live V1 service.

  **Recommendation:** do D4 after D1 and D2. This saves fixture maintenance;
  the current test runtime does not justify test deletion for speed. Keep
  every distinct refusal, persistence and recovery assertion.

## Skill agreement and rejected expansions

[t3-start-thread/SKILL.md, lines 18–64][skill] now separates child delegation
from ordinary conversations. [t3-start-thread/scripts/start_thread.py,
lines 565–597][code] exposes only the five documented ordinary-thread actions.
The [child-task routing task][routing-task] fixed the collection review's D1;
do not propose a delegation command in this script.

Parent/settings exclusivity, exact settings keys, shared-checkout branch
restrictions and authenticated dry runs agree between
[t3-start-thread/SKILL.md, lines 14–16 and 92–93][skill],
[t3-start-thread/references/helper.md, lines 70–72 and 139–157][reference], and
[t3-start-thread/scripts/start_thread.py, lines 461–473, 489–505,
541–543 and 587–598][code]. V2 send carries model selection and leaves runtime
and interaction modes out of its message command (lines 205–219); the fakes
cannot independently establish current-server behavior for those modes.

The reference's dual-protocol claims at
[t3-start-thread/references/helper.md, lines 16, 37, 65–68 and 170–188][reference]
accurately describe today's code. They become stale only when D1 is implemented.
Retain old-record resume guidance. The fork discussion at lines 195–199 is
already explicitly historical; it is not evidence about the current server.
No additional documentation-only draft is warranted.

No hand-rolled stdlib replacement or unused production helper was established.
Repeated project selection in `send()`/`start()` (lines 432–443 and 483–501)
is a possible small extraction during related work, but `inspect()` at
lines 625–627 deliberately accepts zero or multiple matches. Do not replace
those different policies with one generic selector merely to save lines.
Record protection, safe diagnostics and validation remain part of the
architecture. Short docstrings and lint-exception rationale do not justify a
standalone narration-cleanup task.

## Draft issues

Drafts only; nothing was filed. Checked every lifecycle section in
[TASKS.md][tracker], [BACKLOG.md][backlog] and
[library/BACKLOG.md][library-backlog] at the baseline. Unverified proposals,
Ordered backlog and Scheduled were empty; this review was the only In Progress
item. None of the four drafts duplicates an open implementation issue.

**Recommendation:** do **D1, D2, then D3** first: remove the obsolete protocol
dimension, centralize durable reconciliation, then reduce its redundant reads.
D4 follows once the resulting behavior has stable coverage. Each draft is
roughly one agent hour of implementation and fake-server checks; any later
live environment setup is additional.

- **D1 — Retire V1 transport while preserving saved requests.**
  Evidence: F1. **Work:** connect with V2 immediately; remove V1 handshake
  fallback, server-state decoding and protocol selection outside transport.
  Retain the saved command shape and V2 converter, summary compatibility keys,
  CLI, settings and settlement refusals. Collapse live-server parametrization
  to V2, adapt the older direct fakes enough to keep the whole suite passing,
  and update the helper reference in the same change. Keep record migration
  and wholesale fixture consolidation out of scope.

  **Acceptance:** the first socket requests V2 with one ticket; failed
  authentication/upgrade does not retry; the full helper suite passes with
  all five actions covered on V2.
  Old start/send records retain their saved command, thread and message IDs;
  pending, acknowledged, archived and lost-reply recovery still pass.
  Documentation distinguishes V2 server support from old record support.
  **Overlap:** deliberately supersedes the accepted [dual-protocol task][protocol-task];
  reference edits touch the completed, unchecked [documentation task][docs-task],
  so include them here instead of filing another docs proposal.
  **Live T3 needed:** yes, before operational rollout to confirm the supplied
  V2-only premise and first-handshake compatibility. A later authorized
  read-only `inspect` can establish this; no live call was made for this review.

- **D2 — Centralize durable launch and send reconciliation.**
  Evidence: F2. **Work:** use one record-oriented submission path for saved IDs,
  acknowledgement writes, accepted-but-missing refusal and final persistence.
  Keep operation-specific dispatch and output small and explicit. Check the
  V2 launch's initial message after dispatch as well as on resume.

  **Acceptance:** fake loss before and after acceptance preserves IDs and
  never creates a second message; an acknowledged missing result never
  redispatches. A newly acknowledged launch with a visible thread but absent
  initial message reports incomplete visibility and retains its record; once
  visible, resume finishes without replay. Archived launch recovery, private
  record handling and both successful CLI output shapes remain covered.
  **Overlap:** none open; preserves the recovery contract of the
  [protocol task][protocol-task]. **Dependency:** D1.
  **Live T3 needed:** no for this bounded refactor and regression; fake failures
  verify the decisions. This does not claim fresh production compatibility.

- **D3 — Read message persistence without redundant shells.**
  Evidence: F3. **Work:** separate projection/message reads from shell-summary
  composition inside the existing server/reconciliation boundary. Reuse a
  shell already fetched for that observation, preserve merge precedence and
  archived lookup, and fetch fresh summary state after a dispatch. Add no
  persistent connection or snapshot cache.

  **Acceptance:** fake request traces show five successful RPCs for a fresh
  V2 send and two for an already-visible V2 launch resume. Message-ID checks,
  summary output and archived recovery are unchanged. A fake state change
  after dispatch appears in the returned summary; each settle target still
  gets its own fresh shell and independent refusal/error outcome.
  **Overlap:** none open; explicitly preserves the accepted
  [settlement task][settle-task]. **Dependency:** D2.
  **Live T3 needed:** no for call counts and behavior; real latency is unmeasured.

- **D4 — Consolidate duplicate handoff test fakes.**
  Evidence: F4. **Work:** move distinct assertions from `LostReplyServer` and
  `MessageServer` tests into the existing V2 wire fixture and delete duplicated
  classes/setup. Keep failure controls local to the scenarios; no fixture
  inheritance or general transport simulator.

  **Acceptance:** enumerate the migrated assertions in the change; preserve
  pre-/post-acceptance loss, exact message identity, settings rejection,
  workspace checks, private records and dry-run behavior. Run the helper suite
  with networking disabled. No live V1 fake remains; old-record-on-V2 tests
  still exist. Review coverage by behavior, not the former parametrized count.
  **Overlap:** none open; D1 owns V1 parametrization removal and minimal fake
  adaptation, this draft owns redundant fake implementations. If D1's migration
  already removes a fake, omit that completed portion. **Dependencies:** D1 and D2.
  **Live T3 needed:** no; all work concerns fake tests.

[code]: ../../t3-start-thread/scripts/start_thread.py
[tests]: ../../t3-start-thread/tests/test_start_thread.py
[skill]: ../../t3-start-thread/SKILL.md
[reference]: ../../t3-start-thread/references/helper.md
[protocol-task]: ../tasks/6-make-the-t3-start-thread-helper-speak-t3-s-v2-protocol-as-well-as-v1.md
[settle-task]: ../tasks/7-add-a-settle-command-to-the-t3-start-thread-helper.md
[routing-task]: ../tasks/10-separate-t3-child-task-delegation-from-top-level-launches.md
[docs-task]: ../tasks/18-check-skills-akaihola-s-readme-and-the-skills-changed-since-10-19-agai.md
[review-task]: ../tasks/23-review-the-t3-start-thread-helper-s-architecture-for-deep-modules-and-.md
[collection-review]: 2026-10-19-skills-review.md
[docs-review]: 2026-10-22-docs-review.md
[tracker]: ../../TASKS.md
[backlog]: ../../BACKLOG.md
[library-backlog]: ../../library/BACKLOG.md
