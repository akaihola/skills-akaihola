# commit-organizer

A shared skill for organizing a messy git working tree into a clean series of cohesive [Conventional Commits][cc], ordered by file modification time.

## How it works

Three pieces work together:

| Piece | Location | Purpose |
|---|---|---|
| Slash command | `~/.config/coding-agents/commands/commit-organizer.md` | User-facing `/commit-organizer` entrypoint in Pi sessions |
| Shared skill | `SKILL.md` (this directory) | Full methodology, heuristics, checklist, and edge-case guidance |
| Workspace config | `.ai/commit-organizer.yml` in each repo | Optional per-repo grouping buckets, naming hints, and ignore patterns |

The slash command is the thin entrypoint. It tells the agent what to do. The skill is the playbook – it tells the agent *how* to do it well. The workspace config tunes behavior for a specific repository without forking the skill.

The skill includes a **Phase 0 pre-flight triage** step: before organizing commits, it measures disk usage of all uncommitted changes, identifies generated/state noise, proposes `.gitignore` updates, runs `git rm --cached` on already-tracked artifacts, and commits the cleanup separately. This prevents runtime logs, temp files, and downloaded binaries from polluting commit groups.

## Workspace configuration

Before grouping files, the skill looks for a config file in this order:

1. `.ai/commit-organizer.yml`
2. `.commit-organizer.yml`

If neither exists, the skill falls back to generic grouping heuristics.

Config is treated as **guidance, not law**. The agent still uses judgment and explains any exceptions.

### Bootstrapping a new repo

Copy the sample config into your repo and edit it:

```bash
mkdir -p .ai
cp ~/prg/skills-akaihola/commit-organizer/examples/commit-organizer.yml .ai/commit-organizer.yml
```

Then adjust the `buckets`, `ignore`, and `naming` sections to match your repo's structure.

### Config format

```yaml
version: 1

grouping:
  buckets:
    - name: <bucket-name>
      paths:
        - <glob-pattern>
      defaultType: <conventional-commit-type>
      defaultScope: <scope-name>

keepSeparate:
  - deleted-only-cleanups
  - renames-with-content

ignore:
  - <glob-pattern>

naming:
  <bucket-name>: "<type>(<scope>)"
```

See [`examples/commit-organizer.yml`][example] for a working sample.

### Config fields

- **`grouping.buckets`** – path-based grouping rules. Each bucket names a set of glob patterns, a default commit type, and a default scope. Files matching a bucket are grouped together unless cohesion demands a split.
- **`keepSeparate`** – categories the agent should always commit separately (e.g. standalone deletion cleanup, renames bundled with content).
- **`ignore`** – glob patterns for generated noise. During Phase 0 triage, files matching these patterns are flagged as "safe to ignore." Tracked files matching them become candidates for `git rm --cached`; untracked files become candidates for `.gitignore` additions.
- **`naming`** – shorthand mapping from bucket name to preferred `type(scope)` prefix for commit messages.

## Helper scripts

Three Python scripts in `scripts/` automate the repetitive parts of the workflow. Run them via `uv run --with pyyaml`:

| Script | Purpose | Key flags |
|---|---|---|
| `co_triage.py` | Disk usage + classification table for all uncommitted files | `--json`, `--config` |
| `co_ignore.py` | Propose `.gitignore` additions and `git rm --cached` commands | `--apply`, `--config` |
| `co_plan.py` | Propose mtime-ordered commit groups from workspace config buckets | `--json`, `--config` |

All three auto-detect workspace config at `.ai/commit-organizer.yml` or `.commit-organizer.yml`. Pass `--config PATH` to override.

Typical workflow:

```bash
cd /path/to/repo

# 1. See what's there and how big it is
uv run --with pyyaml ~/prg/skills-akaihola/commit-organizer/scripts/co_triage.py

# 2. Clean up noise
uv run --with pyyaml ~/prg/skills-akaihola/commit-organizer/scripts/co_ignore.py --apply

# 3. Plan commits
uv run --with pyyaml ~/prg/skills-akaihola/commit-organizer/scripts/co_plan.py
```

The agent then reviews the plan, adjusts groupings, writes commit messages, and executes.

## Files in this directory

```
commit-organizer/
├── README.md                          ← this file
├── SKILL.md                           ← shared skill (methodology + checklist)
├── examples/
│   └── commit-organizer.yml           ← sample workspace config
└── scripts/
    ├── co_triage.py                   ← disk usage + classification
    ├── co_ignore.py                   ← gitignore + untrack proposals
    └── co_plan.py                     ← mtime-ordered commit grouping
```

[cc]: https://www.conventionalcommits.org/
[example]: examples/commit-organizer.yml
