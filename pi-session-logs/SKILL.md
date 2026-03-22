---
name: pi-session-logs
description: Search and analyze Pi agent session logs stored as JSONL files under ~/.pi/agent/sessions/, and query CCM (Claude Code Mux) proxy logs via journalctl. Use when investigating what Pi did in a past session, why a build or tool call failed, how Pi used interactive_shell, what CCM routed and at what latency, or reconstructing a full session transcript. Covers searching by text, timeline inspection, tool-call auditing, and correlating Pi session timestamps with CCM routing decisions.
---

# Pi Session Logs

Pi records every agent session as a JSONL file. CCM (Claude Code Mux) logs
are available via `journalctl --user -u ccm`.

## File locations

```
~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<uuid>.jsonl
```

The directory name encodes the working directory: each `/` becomes `-` and the
whole string is wrapped in `--`. For example:
`/home/agent/repos/ai/pi/pi-mono` → `--home-agent-repos-ai-pi-pi-mono--`

Session filenames: `2026-03-07T10-58-20-235Z_<uuid>.jsonl`

## JSONL entry types

| `type`                  | What it is                                                                |
| ----------------------- | ------------------------------------------------------------------------- |
| `session`               | Opening metadata: `version`, `id`, `timestamp`, `cwd`                     |
| `session_info`          | Session name set by user or agent: `name`                                 |
| `model_change`          | Provider/model switch: `provider`, `modelId`                              |
| `thinking_level_change` | Extended thinking toggle: `thinkingLevel`                                 |
| `message`               | Main content — see roles below                                            |
| `compaction`            | Context compacted: `summary` holds the replacement summary                |
| `custom_message`        | Injected context (e.g. orchestrator-agents list): `customType`, `content` |
| `custom`                | Extension events (e.g. extmgr-auto-update): `customType`, `data`          |

### Message roles (inside `message.message.role`)

| Role         | Content blocks                                             |
| ------------ | ---------------------------------------------------------- |
| `user`       | `text` blocks (the user's prompt)                          |
| `assistant`  | `text`, `toolCall`, `thinking` blocks                      |
| `toolResult` | top-level `toolCallId` + `toolName`; `text` content blocks |

### Content block types (camelCase — different from Claude Code's snake_case)

| Block `type` | Key fields                                      |
| ------------ | ----------------------------------------------- |
| `text`       | `text`                                          |
| `toolCall`   | `id`, `name`, `arguments` (object, not `input`) |
| `thinking`   | `thinking`, `thinkingSignature`                 |

## Workflow A — find a message across all Pi sessions

```bash
cd ~/prg/skills-kaihola/pi-session-logs
uv run scripts/search-pi-sessions.py "cargo build"
uv run scripts/search-pi-sessions.py "interactive_shell" --context 3
uv run scripts/search-pi-sessions.py "timeout" --recent 20   # last 20 sessions only
```

Sample output:

```
========================================================================
Session : 2026-03-07T08-49-47-276Z_225c45fc-...
File    : /home/agent/.pi/agent/sessions/--home-agent-repos-ai-claude-code-mux--/...
CWD     : /home/agent/repos/ai/claude-code-mux
Name    : ChatGPT Plus OAuth streaming fix
Started : 2026-03-07 08-49
Matches : 7
========================================================================
   [ 41] 2026-03-07T09:11:34 message/assistant        [TOOL:bash {"command": "cd ...}]
>>> [ 42] 2026-03-07T09:11:34 message/assistant        [TOOL:bash {"command": "cd ... && cargo build --release ...}]
   [ 43] 2026-03-07T09:13:37 message/toolResult       [RESULT for bash ...] error[E0308]: ...
```

## Workflow B — inspect a specific session

```bash
cd ~/prg/skills-kaihola/pi-session-logs

# Timeline (default) — one line per entry
uv run scripts/analyze-pi-session.py 225c45fc-7dfb-4752-97dc-be57fd9a6c32

# Full path also works
uv run scripts/analyze-pi-session.py ~/.pi/agent/sessions/--home-agent-repos-ai-claude-code-mux--/2026-03-07T08-49-47-276Z_225c45fc-...jsonl

# Timestamp prefix
uv run scripts/analyze-pi-session.py "2026-03-07T08-49"

# Transcript — full conversation turn by turn
uv run scripts/analyze-pi-session.py 225c45fc --mode transcript

# Tools — only tool calls and results
uv run scripts/analyze-pi-session.py 225c45fc --mode tools
```

## Workflow C — CCM logs (model routing proxy)

CCM logs go to journalctl only (no persistent log file).

```bash
# Recent routing decisions
journalctl --user -u ccm -n 100 --no-pager

# Since a specific time
journalctl --user -u ccm --since "2026-03-07 08:49" --no-pager

# Filter for errors/warnings
journalctl --user -u ccm --since "1 hour ago" --no-pager | rg "ERROR|WARN|failed|⚠️"

# Filter for a specific model
journalctl --user -u ccm --since "2026-03-07 08:00" --no-pager | rg "cargo-build-model"
```

### CCM log format

Each line:

```
maalis 07 09:11:34 gogo ccm[PID]: 2026-03-07T07:11:34.123Z  INFO ccm::server: [profile:stream] model-alias → provider/actual-model
maalis 07 09:13:37 gogo ccm[PID]: 2026-03-07T07:13:37.456Z  INFO ccm::providers::streaming: 📊 provider:model Nms ttft:Xms Y.Zt/s out:N in:M cache:P%
```

Key fields in `📊` lines:

- total latency (`Nms`), time to first token (`ttft:Xms`), tokens/s, output tokens, input tokens, cache hit %

Error patterns:

- `⚠️ Provider X streaming failed: ... trying next fallback` — provider failed, CCM falling back
- `Provider API error: 404 - {"detail":"Not Found"}` — wrong endpoint/model

## Correlating Pi sessions with CCM

Pi session timestamps are in UTC. CCM journalctl timestamps are in local time
(Finnish time = UTC+2 in winter, UTC+3 in summer). Subtract 2h (or 3h in
summer) when matching Pi session events to CCM log lines.

Example: Pi session entry at `2026-03-07T09:11:34Z` → look for CCM entry at
`maalis 07 11:11:34` (UTC+2 offset).

## Diagnostic patterns

### Pi retrying builds due to timeouts

Search for repeated `bash` tool calls with escalating timeouts:

```bash
uv run scripts/search-pi-sessions.py "cargo build" | rg "timeout"
uv run scripts/analyze-pi-session.py <id> --mode tools | rg "cargo|timeout"
```

Signs of bad `bash` timeout handling:

- Multiple `cargo build` calls with increasing `timeout` values (60 → 120 → 180)
- Same command repeated after a `toolResult` showing truncation or timeout error
- `cargo build ... &` in background without `interactive_shell` — Pi can't observe it

Good pattern: use `interactive_shell` in `hands-free`/`dispatch` mode for builds > 30s:

```json
{ "command": "cd /repo && cargo build 2>&1", "mode": "dispatch" }
```

Then poll with `{"sessionId": "...", "drain": true}` until done.

### Finding what model CCM used for a session

1. Get session start time from Pi JSONL (`session` entry timestamp)
2. Convert to local time (+2h Finnish winter)
3. `journalctl --user -u ccm --since "<time>" --until "<time+5min>" --no-pager`
