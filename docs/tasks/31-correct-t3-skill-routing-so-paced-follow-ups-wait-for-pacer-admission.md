Tracker: [the skill tracker]. Correct the ordinary-thread routing instructions so a requested paced follow-up waits for the pacer even when the native MCP send tool is exposed. This fixes a demonstrated instruction gap and prevents unexpected subscription use; it does not change T3 or the pacer.

## Evidence and scope

On October 26, a follow-up ending in the literal `...` was sent with native `t3_thread_send`, `mode=queue`. The idle target started at 14:18:22 UTC, while its provider was paused by the pacer. The steward interrupted it at 14:18:51. Sending a continuation through the existing WebSocket helper at 14:19:18 produced a durable queued run with no start time and preserved the target model options. The [run record] preserves the private delivery evidence; do not copy actual messages, identities or authentication into this repository.

The [routing skill] currently says to prefer a native tool for ordinary-thread operations. Its [helper reference] separately says the trailing marker parks messages. That combination caused the native choice. Inspect the installed T3 native-send implementation and the helper's command translation to establish the route difference before documenting it. The native service delegates to ThreadManagementService.sendToThread; its queue-after-active mode is not proof of pacer admission when no run is active. Do not infer that all native tools or future versions behave the same.

## Work

- Add the smallest explicit exception at the routing decision: for paced follow-ups on this integration, use the helper's send path unless the native tool has an explicit, verified way to preserve pacer admission. Keep the default native preference for operations that are not affected. Do not create another transport or change launch/delegation behavior.
- Explain the observed limitation and how to verify persistence versus admission: a message can be delivered while the run remains queued with no start time. `mode=queue` and a trailing marker alone did not keep the native request parked here. Preserve existing dry-run, target-resolution, model-setting and request-recovery guidance.
- Verify this conclusion from local code and existing fixtures. If the helper already preserves the required dispatch shape and marker, leave its implementation alone. Add or adjust a focused regression only if there is a real untested behavioral boundary; no test that merely matches documentation text. Never send a live probe, restart a service, or change an existing conversation to test this task.
- Use the writing-for-agents and skill-creator workflows for the skill edit. Keep progressive disclosure and exact copyable commands. Examples must be synthetic and portable; no actual prompt text or account details.

## Acceptance

The routing decision and helper reference agree on how paced follow-ups reach admission. The evidence distinguishes the native queue mode from pacer parking and scopes the limitation to the observed integration. Existing ordinary messaging, delegation, settlement, model preferences, dry runs and idempotent recovery keep their documented behavior. Run the relevant existing helper and skill validation, inspect the final diff for private data, and record literal delivery commits and a passing check receipt. No live send or configuration change is needed for completion.

Expected focused effort about 30 minutes. Keep the final handoff brief; no owner action is expected. Do not push, deploy, send messages, add new infrastructure or change pacer settings.

[the skill tracker]: ../../TASKS.md
[routing skill]: ../../t3-start-thread/SKILL.md
[helper reference]: ../../t3-start-thread/references/helper.md
[run record]: http://tinni/my-knowledge/agents/steward/log/2026-10-26.md?f#1613-refill-pacer-wake-up
