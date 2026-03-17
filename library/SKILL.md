---
name: library
description: Private skill distribution system. Use when the user wants to install, use, add, push, sync, list, or search for skills, agents, or prompts from the shared library catalog. Triggers on /library commands or mentions of library, skill distribution, or agentic management.
argument-hint: [command] [name or details]
---

# The Library

A meta-skill for private-first distribution of agentics (skills, agents, and prompts) across workspaces, agents, and devices.

> Adapted from [disler/the-library](https://github.com/disler/the-library) for our symlink-based multi-workspace setup.

## Variables

- **LIBRARY_REPO_URL**: `https://github.com/akaihola/skills-akaihola.git`
- **LIBRARY_YAML_PATH**: `~/prg/skills-akaihola/library/library.yaml`
- **LIBRARY_SKILL_DIR**: `~/prg/skills-akaihola/library/`
- **SKILLS_BASE_DIR**: `~/prg/skills-akaihola/`

## How It Works

The Library is a catalog of references to your agentics. The `library.yaml` file points to where skills, agents, and prompts live (local filesystem or GitHub repos). Nothing is fetched until you ask for it.

**Our setup uses symlinks, not copies.** When you `use` a skill, it creates a symlink from the workspace's `.claude/skills/<name>` → the source directory. This means:
- Updates to `skills-akaihola` propagate instantly — no manual sync needed for already-installed skills
- `sync` just does a `git pull` in `skills-akaihola/`
- A single `library.yaml` in `skills-akaihola/library/` serves all workspaces

## Commands

| Command | Purpose |
|---------|---------|
| `/library install` | First-time setup: clone skills-akaihola and configure |
| `/library add <details>` | Register a new entry in the catalog |
| `/library use <name>` | Symlink a skill into the current workspace |
| `/library push <name>` | Push local changes back to source |
| `/library remove <name>` | Remove from catalog and optionally unlink locally |
| `/library list` | Show full catalog with install status |
| `/library sync` | Pull latest from skills-akaihola (symlinks auto-propagate) |
| `/library search <keyword>` | Find entries by keyword |

## Cookbook

Each command has a detailed step-by-step guide. **Read the relevant cookbook file before executing a command.**

| Command | Cookbook | Use When |
|---------|---------|---------|
| install | [cookbook/install.md](cookbook/install.md) | First-time setup on a new device |
| add | [cookbook/add.md](cookbook/add.md) | Register a new skill/agent/prompt in catalog |
| use | [cookbook/use.md](cookbook/use.md) | Symlink a skill into the current workspace |
| push | [cookbook/push.md](cookbook/push.md) | Push local skill improvements back to source |
| remove | [cookbook/remove.md](cookbook/remove.md) | Remove an entry from the catalog |
| list | [cookbook/list.md](cookbook/list.md) | See what's available and installed |
| sync | [cookbook/sync.md](cookbook/sync.md) | Pull latest versions from origin |
| search | [cookbook/search.md](cookbook/search.md) | Find a skill by keyword |

**When a user invokes a `/library` command, read the matching cookbook file first, then execute the steps.**

## Source Format

The `source` field in `library.yaml` supports these formats (auto-detected):

- `/absolute/path/to/SKILL.md` — local filesystem path
- `~/relative/path/to/SKILL.md` — home-relative path (expand `~` → `/home/agent`)
- `https://github.com/org/repo/blob/main/path/to/SKILL.md` — GitHub browser URL
- `https://raw.githubusercontent.com/org/repo/main/path/to/SKILL.md` — GitHub raw URL

The `source` always points to the **SKILL.md file** (or AGENT.md for agents). The library installs the entire parent directory.

## Install Mechanism (Symlinks)

Unlike the upstream template which copies files, we use symlinks so updates propagate automatically:

```bash
# For skills in skills-akaihola:
ln -sfn ~/prg/skills-akaihola/<skill-name> <target_dir>/<skill-name>

# For skills at arbitrary local paths:
ln -sfn <parent_dir_of_SKILL.md> <target_dir>/<skill-name>
```

The workspace `.claude/skills/` directory is the default target.

## Target Directories

```yaml
default_dirs:
  skills:
    - default: .claude/skills/       # workspace-level (relative to CWD)
    - global: ~/.claude/skills/      # user-level (all sessions)
  agents:
    - default: .claude/agents/
    - global: ~/.claude/agents/
  prompts:
    - default: .claude/commands/
    - global: ~/.claude/commands/
```

- If user says "global" or "globally" → use the `global` directory
- Otherwise → use the `default` directory (relative to current workspace root)

## Library Repo Sync

The library skill itself lives in `LIBRARY_SKILL_DIR` inside the `skills-akaihola` git repo. When `add` modifies `library.yaml`:
1. `git pull` in `LIBRARY_SKILL_DIR` first
2. Make the changes
3. `git add library.yaml && git commit -m "library: added <type> <name>" && git push`

## Typed Dependencies

The `requires` field uses typed references:
- `skill:name` — references a skill in the library catalog
- `agent:name` — references an agent in the library catalog
- `prompt:name` — references a prompt in the library catalog
