---
name: library
description: Manage the shared skills, agents and prompts catalog through /library install, add, use, push, remove, list, sync or search workflows.
argument-hint: "[command] [name or details]"
---

# The Library

This is an agent-run workflow over [library/library.yaml](library.yaml), with
step-by-step [cookbooks](cookbook/). There is no bundled CLI, source-format
parser, dependency resolver or install-status script. Commands below instruct
the agent to perform those steps; they are not executable shell commands.

The repository is public. The catalog can reference private local material,
but “private-first” describes source placement, not a confidentiality guarantee
for committed catalog entries. Keep private content out of public changes.

## Commands

Read the matching cookbook before executing a command.

| Command | Cookbook |
| --- | --- |
| `/library install` | [library/cookbook/install.md](cookbook/install.md) |
| `/library add <details>` | [library/cookbook/add.md](cookbook/add.md) |
| `/library use <name>` | [library/cookbook/use.md](cookbook/use.md) |
| `/library push <name>` | [library/cookbook/push.md](cookbook/push.md) |
| `/library remove <name>` | [library/cookbook/remove.md](cookbook/remove.md) |
| `/library list` | [library/cookbook/list.md](cookbook/list.md) |
| `/library sync` | [library/cookbook/sync.md](cookbook/sync.md) |
| `/library search <keyword>` | [library/cookbook/search.md](cookbook/search.md) |

The cookbooks assume this checkout location:

```text
~/prg/skills-akaihola/
  library/library.yaml
  library/cookbook/
```

Those are workflow assumptions, not environment variables read by a program.
Resolve the actual installation before running commands. Capture the caller’s
workspace root before any cookbook step changes directory to the library repo.

## Catalog and installation model

The catalog groups entries under `library.skills`, `library.agents` and
`library.prompts`. Each entry has `name`, `description` and `source`;
optional `requires` entries use `skill:name`, `agent:name` or `prompt:name`.
The agents/prompts lists are currently empty.

Local sources are absolute or home-relative file paths. For skills, the
source points to the skill instruction file and installation links its
parent directory. GitHub source URLs are described in the cookbooks, but
remote installation uses copies and needs a separate refresh.

Local symlinks reflect edits in their actual source checkout immediately.
Pulling this repository updates sources located here; it does not update
local sources in other repositories or remote copies.

The catalog’s `default_dirs` selects workspace or global destinations:

```yaml
default_dirs:
  skills:
    - default: .claude/skills/
    - global: ~/.claude/skills/
  agents:
    - default: .claude/agents/
    - global: ~/.claude/agents/
  prompts:
    - default: .claude/commands/
    - global: ~/.claude/commands/
```

Use global destinations only when requested. Script-backed list/search,
source-health checks, multi-workspace installation and cataloging agents or
prompts remain proposals in [library/BACKLOG.md](BACKLOG.md).

Adapted from the [upstream library template](https://github.com/disler/the-library).
