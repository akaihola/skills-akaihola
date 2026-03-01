---
name: markdown-pm
description: This skill should be used when the user asks to "query projects", "show active projects", "update project status", "mark project as completed", "generate project dashboard", or mentions project metadata management in Obsidian-style markdown repositories. Provides automated tools for querying, updating, and tracking projects with structured YAML frontmatter.
version: 1.0.0
---

# Markdown Project Management Skill

Manage projects in this Obsidian-style markdown repository using structured frontmatter and automated dashboards.

## Overview

This skill provides tools for querying, updating, and tracking projects stored in `pages/Projects/`. All project files should include standardized YAML frontmatter for metadata:

- `status`: Active, Planning, On Hold, Completed, Abandoned
- `priority`: P1, P2, P3
- `created`: YYYY-MM-DD
- `last_updated`: YYYY-MM-DD
- `tags`: List of tag keywords
- `repo`: (optional) GitHub repository URL

## Tools

### query_projects.py

Query and filter projects from `pages/Projects/`.

**Usage patterns agents should use:**

```bash
# List all active projects
.claude/skills/markdown-pm/query_projects.py --status Active

# Show high priority projects
.claude/skills/markdown-pm/query_projects.py --priority P1

# Filter by tag
.claude/skills/markdown-pm/query_projects.py --tag web,python

# Output as JSON for processing
.claude/skills/markdown-pm/query_projects.py --priority P1 --json
```

**When agents should use this:**

- User asks "What are my active projects?" OR "Show me P1 projects"
- User asks "What projects have the #web tag?"
- Agent needs to understand current project state before suggesting work

---

### update_project.py

Safely update project frontmatter metadata.

**Usage patterns agents should use:**

```bash
# Mark project as completed
.claude/skills/markdown-pm/update_project.py --file "Darkgray" --status Completed

# Change priority
.claude/skills/markdown-pm/update_project.py --file "Web AI assistant" --priority P1

# Add tags
.claude/skills/markdown-pm/update_project.py --file "readfish" --add-tag python

# Remove tags
.claude/skills/markdown-pm/update_project.py --file "readfish" --remove-tag oldtag

# Set custom fields
.claude/skills/markdown-pm/update_project.py --file "Project name" --set repo="https://github.com/user/repo"
```

**When agents should use this:**

- User asks "Mark Darkgray as completed"
- User asks "Promote this project to P1 priority"
- **After significant work on any project (automatic - do not ask)**
- When adding new tags or metadata

**IMPORTANT:** Always use this script. Never edit project files directly for frontmatter updates. This ensures:

- Consistent timestamp updates (`last_updated` is automatically set to today's date on every update)
- Proper YAML formatting
- No accidental damage to file content

**Note:** The `last_updated` field is automatically set to the current date whenever you run `update_project.py`. There is no `--last-updated` argument because this timestamp is always set automatically. Do not attempt to manually set `last_updated` using `--set`.

---

### generate_dashboard.py

Generate a markdown dashboard file summarizing all projects.

**Usage patterns agents should use:**

```bash
# Generate dashboard to terminal
.claude/skills/markdown-pm/generate_dashboard.py

# Write to file (IMPORTANT: --output requires full file path, not just directory)
.claude/skills/markdown-pm/generate_dashboard.py --output pages/PKB/Project dashboard.md
```

**When agents should use this:**

- User asks "Generate the project dashboard"
- After updating any project status
- User asks for a visual overview of all projects

**IMPORTANT:** The `--output` parameter requires a full file path including the filename (e.g., `--output pages/PKB/Project dashboard.md`). Do NOT pass only a directory path (e.g., `--output pages/PKB/`) as this will cause an `IsADirectoryError`.

---

## Agent Instructions

### When User Asks About Projects

1. **First:** Query to understand current state
   - Run `query_projects.py` with relevant filters
   - Present results in a clear, concise format

2. **Then:** Ask if user wants action
   - "Would you like me to update any project status or priority?"

3. **After updates:** Suggest dashboard refresh
   - "Shall I regenerate the dashboard to reflect these changes?"

### When User Wants to Create New Project

1. Ask for details: name, priority, tags, repo (if applicable)

2. Create file in `pages/Projects/` with proper frontmatter:

```yaml
---
type: project
status: Planning
priority: P3
created: 2025-01-11
last_updated: 2025-01-11
tags: []
---
# Project Name

## Overview
## Goals
## Tasks
```

3. Use `update_project.py` to set initial status/priority after creation

### When User Wants to Work on a Specific Project

1. Query project details to understand current state
2. Read the full project file to understand context
3. Perform the requested work
4. **ALWAYS update the project status after significant work**:
   - Use `update_project.py` to update status, priority, or add tags
   - Automatically regenerate the dashboard
   - Do not ask the user whether to update - this is automatic

---

## Project Metadata Schema

```yaml
---
type: project # Always "project"
status: Active # Active, Planning, On Hold, Completed, Abandoned
priority: P1 # P1 (high), P2 (medium), P3 (low)
created: 2025-01-11 # Creation date
last_updated: 2025-01-11 # Last modification (auto-updated by scripts; cannot be manually set)
tags: # List of relevant tags
  - web
  - python
repo: https://github.com/user/repo # Optional GitHub URL
---
```

---

## Integration with Repository Patterns

This skill integrates with existing repository patterns:

- Uses `pages/Projects/` for individual project files
- Uses `pages/PKB/Project dashboard.md` for generated dashboards
- Compatible with Obsidian's Wiki-link syntax (`[[link]]`)
- Maintains compatibility with your existing `Project rotation.md` (can be deprecated in favor of auto-generated dashboards)

After dashboard generation, update `Start page.md` to link to the new dashboard location if desired.
