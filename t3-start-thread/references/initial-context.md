# Inspect initial thread context

Verified 2026-11-11 with local T3 Code Codex sessions. The thread timeline shows
conversation messages; inspect the provider session to establish which automatic
instructions preceded the first assistant response.

The local `~/.t3/userdata/statev2.sqlite` provider-thread projection
`orchestration_v2_projection_provider_threads` maps `thread_id` to
`payload_json.nativeThreadRef.nativeId`. Open SQLite with `mode=ro`. Use that native
ID to locate the corresponding `~/.codex/sessions/**/rollout-*.jsonl` file.
The native ID differs from T3's thread ID.

Read the initial `response_item` records whose payload has `type: "message"`,
stopping at the first assistant message. Distinguish developer instructions,
the user-role `# AGENTS.md instructions` block, and the opening task request.
Measure decoded text, rather than escaped JSON or later tool output. Exact
substring comparisons with candidate instruction files establish which content
was included; current files can differ from historical snapshots. Trace an
agent-authored opening request through its parent's saved launch call when
needed. Reading a file later does not establish startup inclusion.

This method was tested for local Codex sessions only; other providers and remote
servers require their own session evidence. Keep private transcript contents
and identifiers out of public skill examples.
