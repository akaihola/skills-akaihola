---
name: claude-session-logs
description: Search and analyze Claude Code session logs stored as JSONL files under ~/.claude/. Use when investigating why an agent didn't reply, reconstructing what happened in a past session, finding a specific message across all sessions, or diagnosing tool-call failures. Covers searching by text, timeline inspection, full transcript reconstruction, and tool-call auditing.
---

# Claude Session Logs

Claude Code records every session as a JSONL file. Each line is a JSON object
representing one event: a user message, a streaming assistant token, a tool
call, a tool result, or a queue operation. This skill provides two scripts
for finding and dissecting those logs.

## File locations

```
~/.claude/projects/<encoded-path>/<session-id>.jsonl   # per-project sessions
~/.claude/transcripts/<session-id>.jsonl               # other sessions
~/.claude/debug/<session-id>.txt                       # Claude's own debug log
```

The project directory name encodes the working directory path: leading `/` is
stripped and every `/` is replaced with `-`. For example the project at
`/home/agent/coleaders/conversations/slack-C0AJ5JEJH3P` becomes the directory
`-home-agent-coleaders-conversations-slack-C0AJ5JEJH3P`.

## JSONL entry types

| `type`            | What it is                                                                                                                                    |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `queue-operation` | Message batch queued/dequeued by a channel plugin. `operation` is `"enqueue"` or `"dequeue"`. The `content` field holds the full prompt text. |
| `user`            | A user turn — either a real message or a tool result. `message.content` is a string or a list of blocks.                                      |
| `assistant`       | An agent turn — text tokens and/or tool calls. During streaming, each token arrives as its own entry.                                         |

### Content block types (inside `message.content` lists)

| Block `type`  | Key fields               |
| ------------- | ------------------------ |
| `text`        | `text` — the text chunk  |
| `tool_use`    | `id`, `name`, `input`    |
| `tool_result` | `tool_use_id`, `content` |

## Workflow A — find a message across all sessions

Use `search-sessions.py` when you have a phrase and need to locate which
session it belongs to.

```bash
cd ~/prg/skills-akaihola/claude-session-logs
uv run scripts/search-sessions.py "pystytkö nyt listaamaan"
```

Sample output:

```
========================================================================
Session : a01cdfa4-5944-48da-8b2d-15bffab0c923
File    : /home/agent/.claude/projects/…/a01cdfa4-….jsonl
Project : /home/agent/coleaders/conversations/slack-C0AJ5JEJH3P
Matches : 2
========================================================================
   [ 175] 2026-03-04T12:56 assistant/assistant   Yritän uudelleen yksinkertaisemmin: …
   [ 176] 2026-03-04T12:56 assistant/assistant   QR-koodeista löytyi nämä videot: …
>>> [ 177] 2026-03-04T13:51 queue/enqueue         New message batch … pystytkö nyt listaamaan …
   [ 178] 2026-03-04T13:51 queue/dequeue
   [ 179] 2026-03-04T13:51 user/user             New message batch … pystytkö nyt …
```

Options:

```bash
uv run scripts/search-sessions.py "query" --context 5   # more surrounding entries
uv run scripts/search-sessions.py "query" --dir /extra/path
```

## Workflow B — inspect a specific session

Use `analyze-session.py` once you have the session file path or ID.

### Timeline mode (default) — one line per entry, streaming tokens merged

```bash
uv run scripts/analyze-session.py a01cdfa4-5944-48da-8b2d-15bffab0c923
# or with full path:
uv run scripts/analyze-session.py ~/.claude/projects/…/a01cdfa4-….jsonl
```

Consecutive single-token assistant entries are collapsed into one line with a
token count suffix so the timeline stays readable.

### Transcript mode — full reconstructed conversation

```bash
uv run scripts/analyze-session.py a01cdfa4 --mode transcript
```

Prints each turn as a block. Tool calls show the full input JSON; tool
results show up to 500 characters of output.

### Tools mode — only tool calls and results

```bash
uv run scripts/analyze-session.py a01cdfa4 --mode tools
```

Useful for quickly auditing what the agent tried to do (installs, file reads,
bash commands) and what each tool returned.

## Workflow C — read the Claude debug log

Claude writes a verbose debug log alongside every session:

```bash
cat ~/.claude/debug/<session-id>.txt | head -200
```

This log includes model-level details (token counts, stop reasons) not
present in the JSONL.

## Diagnostic patterns

### Why didn't the agent reply?

1. Run `search-sessions.py` to find the session.
2. Run `analyze-session.py --mode transcript` on that session and look for
   `<reply>` tags in the assistant turns.
3. Common causes:
   - **No `<reply>` tag at all** — agent chose silence; the prompt said the
     message was not a direct address.
   - **Unclosed `<reply>` tag** — agent opened `<reply>` before tool calls
     but never closed it; the reply extractor's regex found no complete pair.
   - **Empty `full_text`** — session resumed stale; the hard-mention retry
     should have caught this (< 3 s elapsed, zero text).
   - **`ProcessError`** — session was corrupt; dispatch retried fresh.
   - **Session ends mid-stream** — the subprocess crashed; check the debug log.

### Reconstructing `full_text` from multi-turn tool use

`dispatch_to_agent` concatenates text from all assistant turns.
`sdk_consume.py` inserts `\n\n---\n\n` between a text run and the following
text run whenever a tool call appeared in between.

So for a session with the pattern:

```
Turn 1: text + tool_use  →  "Opening text"
Turn 2: text + tool_use  →  "Intermediate text"
Turn 3: text only        →  "Final answer"
```

`full_text` will be:

```
Opening text

---

Intermediate text

---

Final answer
```

The `<reply>` extractor only sends what is inside `<reply>…</reply>` pairs
(or, after the 2026-03-04 fix, the tail after an unclosed `<reply>` tag).

### Checking whether a reply was actually sent

Search for the agent's name or a unique phrase from the expected response
in the session file of the _channel plugin_ (Slack/Matrix/WhatsApp), not the
Claude session. The channel plugin session records the outgoing `send_message`
tool call when a reply is dispatched.

Alternatively check the channel plugin's systemd log:

```bash
journalctl --user -u pykoclaw-slack -n 100
```

Look for `Agent response sent` (reply dispatched) or `Agent chose silence`
(reply suppressed because `_extract_reply` returned `None`).
