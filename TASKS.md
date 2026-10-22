# Issue tracking for skills-akaihola

This is the canonical tracker for work admitted by the T3 pacer. The existing
root `BACKLOG.md` and `library/BACKLOG.md` retain their older planning records;
they are not pacer inputs. Keep each task in one tracker only.

## Unverified proposals

## Ordered backlog

- [27] Fold the T3 helper's duplicate handoff test fakes into the V2 wire
  fixture
    - Depends on: [24], [25]

  <!-- hai:{"id":"simple-1e95468b-5345-49ad-b895-e08ef7960f7c","labels":["steward"],"createdAt":"2026-10-22T06:03:50.173Z","updatedAt":"2026-10-22T06:03:50.173Z"} -->

## Scheduled

## In Progress

- [~] [26] Stop the T3 helper re-reading thread shells it already has
    - Depends on: [25]

      <!-- hai:{"id":"simple-d88e8d1c-78f9-434c-81ef-96a84ed74406","labels":["steward"],"createdAt":"2026-10-22T06:03:47.550Z","updatedAt":"2026-10-22T06:49:12.778Z"} -->

## Completed / Accepted

- [ ] [25] Bring the T3 helper's launch and send recovery under one record path
    - Depends on: [24]

      <!-- hai:{"id":"simple-378e94c4-14d8-4c22-980b-8bb03a61d8b3","labels":["steward"],"createdAt":"2026-10-22T06:03:43.671Z","updatedAt":"2026-10-22T06:34:00.662Z"} -->

- [ ] [24] Retire the T3 helper's V1 transport while keeping saved requests readable
      <!-- hai:{"id":"simple-d5793ab1-d324-4f47-af0c-09a210753dc1","labels":["steward"],"createdAt":"2026-10-22T06:03:28.860Z","updatedAt":"2026-10-22T06:21:34.457Z"} -->

- [ ] [23] Review the t3-start-thread helper's architecture for deep modules and
  over-engineering
      <!-- hai:{"id":"simple-82639beb-fb21-455e-bd4b-a31f63c9b6a0","labels":["steward","review"],"createdAt":"2026-10-22T05:11:44.943Z","updatedAt":"2026-10-22T06:02:03.961Z"} -->

- [x] [22] Make the himalaya-email-manager README match its five wrappers
      <!-- hai:{"id":"simple-f836c9be-a6ae-4f60-8413-76dad942fc2a","labels":["steward"],"createdAt":"2026-10-22T00:16:24.586Z","updatedAt":"2026-10-22T03:25:25.871Z"} -->

- [x] [21] Keep the library cookbooks in the caller's workspace, create targets and
  honour the source branch
      <!-- hai:{"id":"simple-4c4bd8cd-f4e3-4dca-9166-b0d8498f7eb8","labels":["steward"],"createdAt":"2026-10-22T00:16:23.005Z","updatedAt":"2026-10-22T03:25:28.160Z"} -->

- [x] [20] Give same-name outside documents their own read-as-markdown cache, and
  fail on conversion errors
      <!-- hai:{"id":"simple-3f84bf2c-1de8-4af4-9933-73b5b7e9e239","labels":["steward"],"createdAt":"2026-10-22T00:16:21.764Z","updatedAt":"2026-10-22T03:25:30.555Z"} -->

- [ ] [19] Make secrets-scan fail when a requested scanner doesn't finish
      <!-- hai:{"id":"simple-8adc391b-0ca6-4b11-a1c5-8fe3e232a961","labels":["steward"],"createdAt":"2026-10-22T00:16:20.104Z","updatedAt":"2026-10-22T00:41:30.108Z"} -->

- [ ] [18] Check skills-akaihola's README and the skills changed since 10-19 against
  their scripts
      <!-- hai:{"id":"simple-1d542bfe-f9d6-4bf2-a423-4d485640c4f0","labels":["steward","review"],"createdAt":"2026-10-21T23:15:03.957Z","updatedAt":"2026-10-21T23:38:35.793Z"} -->

- [x] [17] Run the four safe help probes the skill review could not run
      <!-- hai:{"id":"simple-9882987d-c9c5-4325-b2b0-f9055f920051","labels":["steward"],"createdAt":"2026-10-21T11:21:20.385Z","updatedAt":"2026-10-21T21:54:09.756Z"} -->

- [ ] [16] Fix the three high findings of the 2026-10-21 security review
      <!-- hai:{"id":"simple-05a0bf66-a5a3-4c17-8e7e-157d9eb43a5d","labels":["steward"],"createdAt":"2026-10-20T22:25:34.040Z","updatedAt":"2026-10-20T22:34:45.664Z"} -->

- [x] [15] Security scan of skills-akaihola: credentials, scripts, skill
  instructions and history
      <!-- hai:{"id":"simple-ca1b151c-d1bf-46fe-b05d-729a31172f8c","labels":["steward","security"],"createdAt":"2026-10-20T19:38:12.045Z","updatedAt":"2026-10-21T05:18:20.861Z"} -->

- [x] [14] Send review findings to the thread that implemented the work
      <!-- hai:{"id":"simple-345f3047-2675-4813-b434-f30bf4a8e48e","labels":["steward"],"createdAt":"2026-10-19T17:05:31.441Z","updatedAt":"2026-10-19T18:40:28.077Z"} -->

- [x] [13] Fix the skills review's next three: library argument hint, Asana
  discovery, ECB command
      <!-- hai:{"id":"simple-b6046199-2631-4b0b-80d1-cb7f05f0f51b","labels":["steward"],"createdAt":"2026-10-19T14:11:43.093Z","updatedAt":"2026-10-19T18:42:28.472Z"} -->

- [ ] [12] Sanitize skill examples and check secrets without printing them
      <!-- hai:{"id":"simple-d601aeb2-dff1-4782-b654-92461629afc9","labels":["steward"],"createdAt":"2026-10-19T11:18:14.878Z","updatedAt":"2026-10-19T12:52:42.762Z"} -->

- [x] [11] Make receipt dry-run use cached metadata without side effects
      <!-- hai:{"id":"simple-de3d951d-c147-420b-89be-1533b86c3ba8","labels":["steward"],"createdAt":"2026-10-19T11:18:14.475Z","updatedAt":"2026-10-19T14:05:50.335Z"} -->

- [x] [10] Separate T3 child-task delegation from top-level launches
      <!-- hai:{"id":"simple-3b280fda-1d0f-4a06-bd23-4c27f05ddd56","labels":["steward"],"createdAt":"2026-10-19T11:18:14.060Z","updatedAt":"2026-10-19T14:05:50.617Z"} -->

- [ ] [9] Review every skill for stale instructions, weak triggers and token cost,
  and draft the fixes
      <!-- hai:{"id":"simple-2d9cbdb6-f827-4bd2-96e4-eed5462ebd07","labels":["steward"],"createdAt":"2026-10-19T08:08:27.558Z","updatedAt":"2026-10-19T08:53:40.873Z"} -->

- [x] [8] Gather acceptance evidence for the 2 review-queue items
      <!-- hai:{"id":"simple-9467a5ab-9645-4aa0-89cc-747c91768be8","labels":["steward"],"createdAt":"2026-10-17T20:09:27.827Z","updatedAt":"2026-10-21T17:12:39.680Z"} -->

- [x] [7] Add a settle command to the t3-start-thread helper
    - Depends on: [6]

      <!-- hai:{"id":"simple-74d6e5ba-0944-485e-97ba-aa94a578d8eb","labels":["steward"],"createdAt":"2026-10-17T12:52:25.981Z","updatedAt":"2026-10-21T17:12:40.467Z"} -->

- [x] [6] Make the t3-start-thread helper speak T3's V2 protocol as well as V1
      <!-- hai:{"id":"simple-88599925-e2e3-4c51-af5c-f4b0e9ebe196","labels":["steward"],"createdAt":"2026-10-16T20:05:55.680Z","updatedAt":"2026-10-21T17:12:41.782Z"} -->

- [x] [5] Discover imported Android bugreports with uppercase ZIP extensions
  <!-- hai:{"id":"simple-f2a552a8-9a18-49f4-8d8e-3334a7c39243","priority":"low","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.488Z","updatedAt":"2026-10-15T15:47:57.923Z"} -->

- [x] [4] Redact short Wi-Fi names in explicit network contexts
  <!-- hai:{"id":"simple-71a4a9a7-3b77-40f6-b4a1-759bee3d2729","priority":"medium","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.364Z","updatedAt":"2026-10-15T15:47:55.227Z"} -->

- [x] [3] Redact valid email addresses with package-like domain prefixes
  <!-- hai:{"id":"simple-8e743a01-6d8d-4718-b07b-a4721954d82a","priority":"medium","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.244Z","updatedAt":"2026-10-15T08:20:43.649Z"} -->

- [x] [2] Require a valid baseline before reporting Android live traffic rates
  <!-- hai:{"id":"simple-f7bacf22-0266-4ed7-a938-0f489dd00ffa","priority":"medium","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.115Z","updatedAt":"2026-10-15T08:20:22.439Z"} -->

- [x] [1] Protect Android diagnostics captures from other local users
  <!-- hai:{"id":"simple-cd33e380-dfe6-48da-a292-776e182ccb6d","priority":"high","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:52.995Z","updatedAt":"2026-10-15T08:12:40.769Z"} -->

[*]: TASKS.md

[1]: docs/tasks/1-protect-android-diagnostics-captures-from-other-local-users.md

<!-- hai:reserved-numbers:1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27 -->

[2]: docs/tasks/2-require-a-valid-baseline-before-reporting-android-live-traffic-rates.md

[3]: docs/tasks/3-redact-valid-email-addresses-with-package-like-domain-prefixes.md

[4]: docs/tasks/4-redact-short-wi-fi-names-in-explicit-network-contexts.md

[5]: docs/tasks/5-discover-imported-android-bugreports-with-uppercase-zip-extensions.md

[6]: docs/tasks/6-make-the-t3-start-thread-helper-speak-t3-s-v2-protocol-as-well-as-v1.md

[7]: docs/tasks/7-add-a-settle-command-to-the-t3-start-thread-helper.md

[8]: docs/tasks/8-gather-acceptance-evidence-for-the-2-review-queue-items.md

[9]: docs/tasks/9-review-every-skill-for-stale-instructions-weak-triggers-and-token-cost.md

[10]: docs/tasks/10-separate-t3-child-task-delegation-from-top-level-launches.md

[11]: docs/tasks/11-make-receipt-dry-run-use-cached-metadata-without-side-effects.md

[12]: docs/tasks/12-sanitize-skill-examples-and-check-secrets-without-printing-them.md

[13]: docs/tasks/13-fix-the-skills-review-s-next-three-library-argument-hint-asana-discove.md

[14]: docs/tasks/14-send-review-findings-to-the-thread-that-implemented-the-work.md

[15]: docs/tasks/15-security-scan-of-skills-akaihola-credentials-scripts-skill-instruction.md

[16]: docs/tasks/16-fix-the-three-high-findings-of-the-2026-10-21-security-review.md

[17]: docs/tasks/17-run-the-four-safe-help-probes-the-skill-review-could-not-run.md

[18]: docs/tasks/18-check-skills-akaihola-s-readme-and-the-skills-changed-since-10-19-agai.md

[19]: docs/tasks/19-make-secrets-scan-fail-when-a-requested-scanner-doesn-t-finish.md

[20]: docs/tasks/20-give-same-name-outside-documents-their-own-read-as-markdown-cache-and-.md

[21]: docs/tasks/21-keep-the-library-cookbooks-in-the-caller-s-workspace-create-targets-an.md

[22]: docs/tasks/22-make-the-himalaya-email-manager-readme-match-its-five-wrappers.md

[23]: docs/tasks/23-review-the-t3-start-thread-helper-s-architecture-for-deep-modules-and-.md

[24]: docs/tasks/24-retire-the-t3-helper-s-v1-transport-while-keeping-saved-requests-reada.md

[25]: docs/tasks/25-bring-the-t3-helper-s-launch-and-send-recovery-under-one-record-path.md

[26]: docs/tasks/26-stop-the-t3-helper-re-reading-thread-shells-it-already-has.md

[27]: docs/tasks/27-fold-the-t3-helper-s-duplicate-handoff-test-fakes-into-the-v2-wire-fix.md

## Rules

### Review and ordering

- Only the user, or the steward (`~/my-knowledge/agents/steward/`) for a
  proposal that fits `~/my-knowledge/pages/Goals.md`, promotes proposals to
  Ordered backlog; the steward lists each move in its daily digest. An
  explicit request to add tasks for reviewed findings authorizes adding those
  tasks there.
- Before adding an issue, check all sections and the older backlog files for
  duplicates. Merge overlapping proposals instead of making another record.
- Each issue has exactly one lifecycle section. Preserve its stable Hai ID,
  reference number, text and wrapping when moving it.
- Use numbered references for tasks with detailed descriptions in
  `docs/tasks/N-description.md`. Keep simple tasks inline with `[*]`.
- Keep dependency metadata consistent between indented `- Depends on: [N]`
  lines and description-file YAML frontmatter. Order prerequisites first.
- Schedule only reviewed issues whose dependencies are completed. Proposals
  and issues already in progress are not candidates for new launches.

### Tracker changes and validation

- Use `hai-tasks` or the `hai_tasks.TasksStore` Python API for issue mutations.
  Read the current revision before each write; re-read after every write.
- If the CLI is unavailable, run `python3 -m hai_tasks` from an environment
  containing the Hai package. Never substitute a task number for a stable ID.
- Before committing tracker changes, load the whole tracker through Hai and
  verify that every detail link resolves and every issue occurs once.
- The T3 pacer's `--dump-order` validates configuration and shows eligible
  work without scheduling or launching it. Keep local configuration outside
  this public repository. Use one pacer process for each tracker.

### Scheduling, implementation and completion

1. On a clean `main` checkout, move the selected issue from Ordered backlog
   to Scheduled through Hai and commit the scheduling change. The pacer does
   this before creating the task's isolated T3 worktree.
2. In that worktree, rebase onto `main`, move only that issue to In Progress
   through Hai, and commit. Implement its requirements and run its acceptance
   checks. Preserve unrelated work and keep the branch rebased.
3. Merge the reviewed change into `main` using the repository's normal Git
   workflow. Keep the worktree and branch after merging.
   Remove them only when the user explicitly requests it.
   Record completion only after merge, under Completed / Accepted
   with `[ ]`, and commit the tracker update. Tests passing alone do not mean
   that the user has accepted the result.
4. Only explicit user acceptance changes `[ ]` to `[x]`. During later tracker
   maintenance, retire accepted entries and detail files only when no other
   task references them. Never reuse their reference numbers.

When tracker updates conflict, start from `main`'s tracker and reapply only
the current issue's move. Read the whole tracker again and check for duplicate
issues, missing links and inconsistent dependencies before committing.
