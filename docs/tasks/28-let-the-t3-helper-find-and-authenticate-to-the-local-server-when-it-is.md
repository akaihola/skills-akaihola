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


## Implementation and validation

The helper reads the selected base directory's runtime origin when no URL
is supplied. Local session issuance permits loopback or the same normalized
scheme, hostname and effective port as that origin. Other remote origins
retain the existing refusal. Explicit URLs and saved resume records retain
their endpoint selection.

Four new parametrized tests use an isolated home, temporary runtime data and
an executable fake CLI. They cover discovery, fallback, session arguments,
case/default-port normalization and refusal across scheme, host and port.
Malformed JSON, invalid ports and an unreadable runtime path fall back safely.

The initial test-first run reproduced the defect: six failing cases, fourteen
passing cases. After implementation, the full helper suite passed 103 tests
with networking disabled. Ruff lint, formatting and whitespace checks passed.
Ruff required formatting-only edits in the two changed Python files.

```bash
unshare -rn env PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-project --with pytest==9.1.1 --with websocket-client==1.9.2 pytest -p no:cacheprovider t3-start-thread/tests -q
ruff check t3-start-thread/scripts/start_thread.py t3-start-thread/tests/test_start_thread.py
ruff format --check t3-start-thread/scripts/start_thread.py t3-start-thread/tests/test_start_thread.py
git diff --check
```

No live server was contacted. The steward owns the later deployed-server
read-only inspection and send dry run.

## Resource record

Commands ran sequentially with a 180-second bound and process-group cleanup,
monitoring available memory and swap against the launch thresholds.

- **Test-first focused cases — started at once:** wait 0.0 s; admission
  MemAvailable 57863 MiB; final 57785 MiB; starting swap
  0 MiB; growth 0 MiB; elapsed 1.1 s; exit 1.

- **Initial full helper suite — started at once:** wait 0.0 s; admission
  MemAvailable 57939 MiB; final 57834 MiB; starting swap
  0 MiB; growth 0 MiB; elapsed 1.2 s; exit 0.

- **Final full helper suite — started at once:** wait 0.0 s; admission
  MemAvailable 57931 MiB; final 57907 MiB; starting swap
  0 MiB; growth 0 MiB; elapsed 1.2 s; exit 0.

## Merge and recorded evidence

Fast-forwarded `main` from `38a7941f94c48925b7da8d53d6c0dc5e9792ea41` to
`1c3fce303eb22ad3f27a4078b6a01e4262a51914`. Delivery commits, oldest first:

- `1c3fce303eb22ad3f27a4078b6a01e4262a51914`

The task worktree remains clean and detached at the merged commit; its branch
is retained. The shared checkout remains on `main`.

Both checks were recorded against the merged commit and passed (exit 0):

- **`helper-fake-suite`:** all 103 helper tests with networking disabled.
- **`lint-format-whitespace`:** Ruff lint and formatting for both Python
  files, plus whitespace validation of the delivery diff.

The [machine receipt] records commands, commit identity and SHA-256
fingerprints. This helper has no lockfile and uses no editable dependency;
the offline test dependencies are pinned in the command.

- **Recorder helper-fake-suite — started at once:** wait 0.0 s;
  admission MemAvailable 57882 MiB; final 57833 MiB;
  starting swap 0 MiB; growth 0 MiB;
  elapsed 1.4 s; exit 0.

- **Recorder lint-format-whitespace — started at once:** wait 0.0 s;
  admission MemAvailable 57848 MiB; final 57850 MiB;
  starting swap 0 MiB; growth 0 MiB;
  elapsed 0.2 s; exit 0.

No acceptance conditions remain unmet. Completion is recorded unchecked;
user acceptance stays separate. The steward owns the later deployed-server
inspection and send dry run. No owner action is required.

[machine receipt]: 28-let-the-t3-helper-find-and-authenticate-to-the-local-server-when-it-is.evidence.json
