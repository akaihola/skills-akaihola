---
name: sync-plugin-cache
description: >-
  Apply local edits to a Claude Code plugin and propagate them to the installed
  plugin cache so they take effect without a full marketplace reinstall. Use when
  you have edited a plugin's source under a local clone (e.g.
  ~/prg/skills-akaihola/<plugin>/) and need the running Claude Code to pick up the
  change — the cache copy at ~/.claude/plugins/cache/ is what Claude actually
  loads, not the source clone. Triggers on "sync the plugin cache", "my plugin
  edit isn't taking effect", "push plugin changes", or iterating on a slash
  command / skill / hook that lives in an installed plugin.
---

# Sync a plugin edit into the installed cache

Claude Code loads plugins from `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`,
**not** from your source clone. After editing the source you must copy the changed
file(s) into the cache (and ideally commit/push the source) for the change to take
effect. This is the loop, distilled from iterating on `reflect-extensions`.

## The four steps

Given a source clone at `$SRC` (e.g. `~/prg/skills-akaihola`), a marketplace name
`$MP`, plugin `$PLUGIN`, and version `$VER`:

1. **Edit the source** under `$SRC/$PLUGIN/...` (the canonical copy).

2. **Copy to the cache.** Find the live cache path and overwrite it:
   ```bash
   CACHE="$HOME/.claude/plugins/cache/$MP/$PLUGIN/$VER"
   command cp "$SRC/$PLUGIN/commands/foo.md" "$CACHE/commands/foo.md"
   ```
   Use `command cp` to bypass any `cp -i` alias. The cache mirrors the source
   layout (`commands/`, `skills/`, `hooks/`, `scripts/`, ...).

3. **Commit and push the source** so the change is durable and shareable:
   ```bash
   cd "$SRC" && git add "$PLUGIN/commands/foo.md" && git commit -m "..." && git push
   ```

4. **Bump the recorded SHA** so Claude Code doesn't consider the cache stale or
   overwrite it on next update. Edit `~/.claude/plugins/installed_plugins.json`,
   find the entry for `$PLUGIN@$MP`, and set its `gitCommitSha` to the new
   `git rev-parse HEAD`.

## Notes

- **A restart (or `/reload-skills`) is required** for command/skill text changes to
  be re-read; new hooks/plugins need a full restart.
- The cache may hold **multiple versions** (e.g. `4.0.2` and `4.0.3` side by side).
  Edit the version Claude is actually loading — check `installed_plugins.json` for
  the active `version`/`installPath`.
- For `!`-injection command files, see the memory note `cc-bang-injection-authoring`
  for authoring gotchas (bang-backtick runs in prose; `(N)` glob qualifier is ignored).
