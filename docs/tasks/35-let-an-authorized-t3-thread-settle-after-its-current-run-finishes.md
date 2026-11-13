Agents can now arrange settlement after their final reply without starting another AI turn. The existing helper has a bounded `settle --after-run RUN_ID` mode; the detached invocation is in [the helper guide].

## Verification on 2026-11-13

- The helper suite passed 113 tests. Ruff and ty passed for the helper and tests.
- Tests cover waiting for successful completion, newer user messages and runs, failed runs, timeout, and settlement read-back.
- A live call naming an earlier run returned `cancelled` because a newer run existed. It did not dispatch settlement.
- The run/message check and settlement RPC remain separate; strict atomic protection requires server support for an expected run ID.
- Initial tests exposed an existing hard-coded Bash fallback: authentication fixtures deliberately have no Bash in PATH. The helper now sets SHELL only when Bash is found. The type checker needed the temporary uv dependency directories as explicit search paths; uv removes its temporary launcher environment after a command exits.

## Automatic continuation

Owner: the originating conversation. A detached worker is being armed for its current run. The worker will log success, cancellation, timeout or error to [the private settlement log]. Live successful self-settlement cannot be verified until the current reply ends.

When the registered clipboard after-rebuild check wakes [the originating conversation], its agent must read this log, record the actual outcome here, and finish or repair this helper task before requesting acceptance. The clipboard task remains separate and still requires the joint clipboard test. No immediate user action is needed.

[the helper guide]: ../../t3-start-thread/references/helper.md?f#settle-after-the-current-run
[the private settlement log]: http://atom/.local/state/t3-start-thread/0e79fa68-fd2f-4338-bb4e-482bbd6ad095.settle.log?f
[the originating conversation]: t3-thread://v1/0e79fa68-fd2f-4338-bb4e-482bbd6ad095
