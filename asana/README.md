# Asana Skill for Pykoclaw

## Architecture Philosophy

This skill follows the **"thick scripts, thin prompts"** pattern to ensure future migration to a plugin is straightforward. All business logic lives in Python scripts; the SKILL.md only provides routing instructions to the LLM.

## Directory Structure

```
~/skills-akaihola/asana/
├── SKILL.md                    # LLM instructions (routing layer only)
├── scripts/
│   ├── __init__.py
│   ├── asana_client.py         # Asana API wrapper (reusable in plugin)
│   ├── db.py                   # SQLite models & connection
│   ├── sync.py                 # Bidirectional sync logic
│   ├── tasks.py                # Task query operations
│   └── projects.py             # Project operations
├── migrations/                 # Alembic-style DB migrations
│   ├── 001_initial.sql
│   └── 002_add_projects.sql
├── pyproject.toml              # Dependencies
└── README.md                   # This file
```

## Database Schema (Migration-Safe)

Design for **eventual plugin migration** — use clean SQLAlchemy-style models that can move to pykoclaw's shared DB:

```sql
-- tables: asana_tasks, asana_projects, asana_sync_state, asana_users

CREATE TABLE asana_tasks (
    id INTEGER PRIMARY KEY,
    asana_gid TEXT UNIQUE NOT NULL,      -- Asana's global ID
    name TEXT NOT NULL,
    notes TEXT,
    completed BOOLEAN DEFAULT 0,
    due_on DATE,
    due_at TIMESTAMP,
    priority TEXT,                        -- custom field mapping
    project_gid TEXT,
    assignee_gid TEXT,
    workspace_gid TEXT NOT NULL,
    modified_at TIMESTAMP,                -- Asana's last modified
    local_modified_at TIMESTAMP,          -- Our last sync
    sync_status TEXT DEFAULT 'synced',   -- 'synced', 'dirty', 'conflict'
    raw_json TEXT                       -- Full API response for debugging
);

CREATE TABLE asana_sync_state (
    id INTEGER PRIMARY KEY,
    workspace_gid TEXT UNIQUE,
    last_full_sync TIMESTAMP,
    last_incremental_sync TIMESTAMP,
    sync_token TEXT                     -- For Asana's incremental sync
);
```

**Migration consideration:** When converting to plugin, these tables move to pykoclaw's database. The `raw_json` column allows data recovery if schema diverges.

## API Client Design (`scripts/asana_client.py`)

```python
"""
Pure API wrapper — no LLM logic, no DB calls.
Reusable as-is when migrating to plugin.
"""

import requests
from typing import Optional, List, Dict
from datetime import datetime

class AsanaClient:
    def __init__(self, token: str, base_url: str = "https://app.asana.com/api/1.0"):
        self.token = token
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
    
    def get_tasks(
        self, 
        workspace_gid: str,
        assignee_gid: Optional[str] = None,
        project_gid: Optional[str] = None,
        completed_since: Optional[datetime] = None,
        modified_since: Optional[datetime] = None
    ) -> List[Dict]:
        """Fetch tasks from Asana API."""
        ...
    
    def get_task(self, task_gid: str) -> Dict:
        """Fetch single task with full details."""
        ...
    
    def create_task(self, data: Dict) -> Dict:
        """Create new task."""
        ...
    
    def update_task(self, task_gid: str, data: Dict) -> Dict:
        """Update existing task."""
        ...
    
    def get_workspaces(self) -> List[Dict]:
        """List available workspaces."""
        ...
    
    def get_projects(self, workspace_gid: str) -> List[Dict]:
        """List projects in workspace."""
        ...
    
    def get_incremental_sync(self, sync_token: str) -> Dict:
        """Asana's incremental sync endpoint."""
        ...
```

## Sync Logic (`scripts/sync.py`)

```python
"""
Bidirectional sync with conflict resolution.
Called by: LLM via Bash, future scheduler, future plugin.
"""

class AsanaSync:
    def __init__(self, db_path: str, token: str):
        self.db = Database(db_path)
        self.client = AsanaClient(token)
    
    def full_sync(self, workspace_gid: str):
        """Complete refresh — use sparingly (rate limits)."""
        ...
    
    def incremental_sync(self, workspace_gid: str):
        """Fast sync using Asana's sync token."""
        ...
    
    def sync_task_to_asana(self, local_task_id: int):
        """Push local changes to Asana."""
        ...
    
    def resolve_conflict(self, task_gid: str, strategy: str = "asana_wins"):
        """Handle simultaneous edits."""
        ...
```

## SKILL.md Design (Thin Prompt)

```markdown
# Asana Task Management

You can help the user manage their Asana tasks. You have access to a local cache of their tasks and can sync with Asana when needed.

## Available Tools

When the user asks about tasks, use these scripts:

### Query local cache (fast, no API calls)
```bash
python ~/skills-akaihola/asana/scripts/tasks.py list --workspace <gid> [--project <gid>] [--assignee <gid>] [--due-before <date>]
python ~/skills-akaihola/asana/scripts/tasks.py search <query>
python ~/skills-akaihola/asana/scripts/tasks.py get <task_gid>
```

### Sync with Asana (slow, API calls)
```bash
python ~/skills-akaihola/asana/scripts/sync.py incremental --workspace <gid>
python ~/skills-akaihola/asana/scripts/sync.py full --workspace <gid>
```

### Modify tasks
```bash
python ~/skills-akaihola/asana/scripts/tasks.py create --name "..." [--project <gid>] [--due <date>]
python ~/skills-akaihola/asana/scripts/tasks.py complete <task_gid>
python ~/skills-akaihola/asana/scripts/tasks.py update <task_gid> --notes "..."
```

## Workflow

1. **User asks about tasks** → Query local cache first
2. **Cache stale or missing data** → Run incremental sync, then query
3. **User wants to create/modify** → Make change locally, sync to Asana
4. **"What's urgent?"** → Query due within 3 days, incomplete, sorted by priority

## Configuration

The skill reads `ASANA_TOKEN` and `ASANA_WORKSPACE_GID` from environment.
If not set, ask the user to configure them.

## Caching Strategy

- Full sync: Run once on first use, then weekly
- Incremental sync: Run on every task query (fast, uses Asana's sync token)
- Local changes: Mark as 'dirty', sync immediately when possible
```

## LLM "Smartness" Boundaries

**Keep in skill (LLM-mediated):**
- Interpreting vague queries ("what's urgent?" → due < 3 days, high priority)
- Deciding when sync is needed ("cache is 2 hours old, probably stale")
- Natural language task creation ("remind me to call mom tomorrow" → task with due date)

**Move to scripts (code-mediated):**
- API authentication and error handling
- Database queries and caching logic
- Conflict resolution algorithms
- Rate limit handling

**This boundary ensures:** When we migrate to plugin, we only rewrite the "smartness" layer, not the core logic.

## Testing Strategy

```bash
# Unit tests for scripts (pytest)
cd ~/skills-akaihola/asana
pytest scripts/test_*.py

# Integration test with mock Asana API
pytest tests/test_integration.py --mock-api

# Manual test via pykoclaw chat
pykoclaw chat test
> What are my high priority tasks?
```

## Migration Path to Plugin (Documented)

When ready to migrate to `pykoclaw-asana` plugin:

1. **Move code:** `scripts/` → `pykoclaw_asana/` (package)
2. **Database:** Migration script to move SQLite tables to pykoclaw's DB
3. **Register tools:** Convert script entry points to MCP tool decorators
4. **Scheduler:** Add `@scheduler` decorated functions calling sync logic
5. **Remove SKILL.md:** Replace with tool descriptions in `CLAUDE.md`

**Estimated effort:** 2-3 hours (mostly mechanical, not architectural)

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "asana-skill"
version = "0.1.0"
dependencies = [
    "requests>=2.31.0",
    "sqlite3",  # stdlib, but explicit
    "python-dateutil>=2.8.0",
    "pydantic>=2.0",  # for data validation
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "responses"]
```

## Configuration

Skill reads from environment (set in `~/.bashrc` or pykoclaw's env):

```bash
export ASANA_TOKEN="your_personal_access_token"
export ASANA_WORKSPACE_GID="1234567890"  # Default workspace
```

Or support multiple workspaces:
```bash
export ASANA_WORKSPACES='{"Personal": "123...", "Work": "456..."}'
```

## First-Time Setup Script

```python
#!/usr/bin/env python3
# scripts/setup.py

"""
Interactive setup for first use.
Guides user through:
1. Getting Asana token
2. Selecting workspace
3. Initial full sync
"""

def main():
    print("Let's set up Asana integration...")
    # ... interactive prompts
    # ... save to ~/.config/asana-skill/config.json
    # ... run initial sync
```

## Security Considerations

- **Token storage:** Use keyring if available, fallback to env var
- **Database:** SQLite file permissions 0600
- **Logging:** Never log full API responses (may contain sensitive data)
- **Rate limits:** Respect Asana's 150 requests/minute

## Future Enhancements (Post-Migration)

When this becomes a plugin:
- Webhook support for real-time sync
- Rich task editing via chat UI
- Project templates
- Time tracking integration
- Multi-workspace seamless switching

---

**Status:** Ready for implementation
**Next step:** Create `SKILL.md` and `scripts/asana_client.py` scaffold
