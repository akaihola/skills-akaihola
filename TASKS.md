# Issue tracking for skills-akaihola

This is the canonical tracker for work admitted by the T3 pacer. The existing
root `BACKLOG.md` and `library/BACKLOG.md` retain their older planning records;
they are not pacer inputs. Keep each task in one tracker only.

## Unverified proposals

## Ordered backlog

- [3] Redact valid email addresses with package-like domain prefixes
  <!-- hai:{"id":"simple-8e743a01-6d8d-4718-b07b-a4721954d82a","priority":"medium","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.244Z","updatedAt":"2026-10-12T03:58:53.244Z"} -->

- [4] Redact short Wi-Fi names in explicit network contexts
  <!-- hai:{"id":"simple-71a4a9a7-3b77-40f6-b4a1-759bee3d2729","priority":"medium","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.364Z","updatedAt":"2026-10-12T03:58:53.364Z"} -->

- [5] Discover imported Android bugreports with uppercase ZIP extensions
  <!-- hai:{"id":"simple-f2a552a8-9a18-49f4-8d8e-3334a7c39243","priority":"low","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.488Z","updatedAt":"2026-10-12T03:58:53.488Z"} -->

## Scheduled

## In Progress

## Completed / Accepted

- [ ] [2] Require a valid baseline before reporting Android live traffic rates
  <!-- hai:{"id":"simple-f7bacf22-0266-4ed7-a938-0f489dd00ffa","priority":"medium","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:53.115Z","updatedAt":"2026-10-14T20:08:33.816Z"} -->

- [ ] [1] Protect Android diagnostics captures from other local users
  <!-- hai:{"id":"simple-cd33e380-dfe6-48da-a292-776e182ccb6d","priority":"high","labels":["android-diagnostics","review"],"createdAt":"2026-10-12T03:58:52.995Z","updatedAt":"2026-10-14T20:04:11.913Z"} -->

[*]: TASKS.md

[1]: docs/tasks/1-protect-android-diagnostics-captures-from-other-local-users.md

<!-- hai:reserved-numbers:1,2,3,4,5 -->

[2]: docs/tasks/2-require-a-valid-baseline-before-reporting-android-live-traffic-rates.md

[3]: docs/tasks/3-redact-valid-email-addresses-with-package-like-domain-prefixes.md

[4]: docs/tasks/4-redact-short-wi-fi-names-in-explicit-network-contexts.md

[5]: docs/tasks/5-discover-imported-android-bugreports-with-uppercase-zip-extensions.md

## Rules

### Review and ordering

- Only the user promotes proposals to Ordered backlog. An explicit request to
  add tasks for reviewed findings authorizes adding those tasks there.
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
   workflow. Record completion only after merge, under Completed / Accepted
   with `[ ]`, and commit the tracker update. Tests passing alone do not mean
   that the user has accepted the result.
4. Only explicit user acceptance changes `[ ]` to `[x]`. During later tracker
   maintenance, retire accepted entries and detail files only when no other
   task references them. Never reuse their reference numbers.

When tracker updates conflict, start from `main`'s tracker and reapply only
the current issue's move. Read the whole tracker again and check for duplicate
issues, missing links and inconsistent dependencies before committing.
