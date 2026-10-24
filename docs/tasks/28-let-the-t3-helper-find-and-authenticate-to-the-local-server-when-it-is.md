Steward issue, 2026-10-25 00:17 refill (steward decisions D53 and D95: a demonstrated failure with a bounded fix). Goal: agentic-leverage; skills-akaihola is tier 2 in `<steward-vault>/Goals.md`. Estimated 1 h.

Tracker: [TASKS.md](../../TASKS.md).

On 2026-10-24 an `/accept` run on the agent account's T3 machine needed three tries to send its settle request to the steward with `t3-start-thread/scripts/start_thread.py send`. That machine's T3 server listens on its tailnet address, not on loopback, so:

1. the helper's default `--url` (`http://127.0.0.1:3773`) reached no server, and
2. once given the real address, the helper refused to issue its own session ("Remote servers require T3_THREAD_AUTH_TOKEN"), because `Server.__init__` only self-issues for `localhost`, `127.0.0.1` and `::1`.

The agent got through by issuing a session with `t3 auth session issue` itself. Every `/accept` and every helper call without `--url` and a token on that machine hits the same two failures.

T3 records the address it is serving on in `<base dir>/userdata/server-runtime.json` (the base dir is `~/.t3` unless `--base-dir` says otherwise), whose `origin` field is the server's URL, for example `http://<host>:3773`.

## Work

1. Write the failing tests first, in `t3-start-thread/tests/test_start_thread.py`, with a temporary base dir holding a `server-runtime.json` and a fake `t3` command:
   - without `--url`, the helper targets the runtime file's `origin`;
   - without `--url` and without a runtime file, it still targets `http://127.0.0.1:3773`;
   - with no `T3_THREAD_AUTH_TOKEN`, it issues a session with the local `t3` CLI (passing `--base-dir` when given) when the URL is a loopback address or equals the runtime file's `origin`;
   - for any other host it still refuses with the same message and never runs `t3`.
2. Make them pass in `start_thread.py` with the least code: read `origin` from the runtime file when `--url` is omitted, and widen the self-issue condition to "loopback, or the local server's own recorded origin". Compare normalized origins (scheme, host, port), not string prefixes. A missing or unreadable runtime file falls back to today's behaviour.
3. In `t3-start-thread/SKILL.md`, replace any instruction that assumes loopback with one sentence: the helper finds the local server itself; pass `--url` and `T3_THREAD_AUTH_TOKEN` only for another machine's server.

## Ground rules

- The helper is the steward's only route for follow-ups and settling threads: keep the CLI, output shapes and other refusals unchanged.
- Never send a locally issued session to any host other than the local server's recorded origin or loopback. The token never appears in output, logs or committed files.
- Don't call a live T3 server from tests: fakes verify this work. After the merge the steward runs a read-only `inspect` and a `send --dry-run` against the deployed server without `--url` or a token.
- Run at most one focused test command at a time, under your launch prompt's memory rule.
- Keep private paths and host names out of committed docs and code; the check receipt (`*.evidence.json`) is exempt.
- If a formatting-only change is demanded by a required check, make it and say so.

## Acceptance

- The four new tests pass, and the helper's existing test suite passes with networking disabled.
- Only `t3-start-thread/scripts/start_thread.py`, its tests and `t3-start-thread/SKILL.md` change, besides this issue's own moves.
- Handoff: a short outcome; details stay in this file.
