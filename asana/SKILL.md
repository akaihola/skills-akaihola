---
name: asana
description: Manage Asana tasks and projects. Use when the user asks about "Asana tasks", "what's on my Asana board", "create an Asana task", "update Asana priority", "sync Asana", or any request to query, create, or modify tasks in Asana.
---

# Asana Task Management

> **Status: Not yet implemented.**
> This skill is designed but the scripts have not been created yet.
> See `README.md` in this directory for the planned architecture.

When implemented, this skill will manage Asana tasks via a local SQLite cache
with bidirectional sync. The planned scripts live in `scripts/`:

| Script                | Purpose                                      |
| --------------------- | -------------------------------------------- |
| `scripts/tasks.py`    | Query / create / update tasks in local cache |
| `scripts/sync.py`     | Bidirectional sync with Asana API            |
| `scripts/projects.py` | List and manage projects                     |

## Configuration (planned)

```bash
export ASANA_TOKEN="your_personal_access_token"
export ASANA_WORKSPACE_GID="1234567890"
```

## Setup (planned)

```bash
# Run once to do initial full sync
python scripts/sync.py full --workspace $ASANA_WORKSPACE_GID
```

## Usage (planned)

```bash
# List tasks
python scripts/tasks.py list --workspace $ASANA_WORKSPACE_GID

# Search tasks
python scripts/tasks.py search "meeting notes"

# Create a task
python scripts/tasks.py create --name "Review PR" --due 2026-03-10

# Mark complete
python scripts/tasks.py complete <task_gid>

# Incremental sync (fast)
python scripts/sync.py incremental --workspace $ASANA_WORKSPACE_GID
```

See `README.md` for full architecture details, database schema, and migration
path to a plugin.
