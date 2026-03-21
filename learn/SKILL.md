# learn

Reflect and extract learnings from the current conversation. Capture actionable lessons in the most appropriate durable form.

## When to use

Use this skill when:

- A task is complete and had interesting friction or discovery
- The user asks you to reflect or says `learn`
- You notice a repeated pattern worth capturing
- Something took longer than it should have

## Process

### 1. Reflect on the conversation

Ask yourself:

- **What did I do?** (the task itself)
- **What went smoothly?** (keep doing this)
- **What was friction?** (manual steps, missing context, trial-and-error)
- **What knowledge was missing?** (had to discover something that should have been known)
- **What will repeat?** (this exact task or pattern will come up again)

### 2. Load project-specific guidance

Read `LEARN.md` or `.claude/LEARN.md` from the current workspace root if it exists. It overrides or extends the defaults below with project-specific capture locations (memory paths, backlog files, naming conventions, etc.).

### 3. Classify each learning

For each insight, decide the best capture format:

| Format                  | When to use                                 | Where it lives                                 |
| ----------------------- | ------------------------------------------- | ---------------------------------------------- |
| **Script**              | Multi-step routine that will repeat exactly | `~/bin/` or project `bin/`                     |
| **Skill**               | Capability needing instructions + judgment  | `.claude/skills/<name>/SKILL.md`               |
| **Memory note**         | Fact, preference, lesson, context           | See `LEARN.md` for workspace-specific location |
| **CLAUDE.md update**    | Workflow pattern or convention              | `CLAUDE.md`                                    |
| **Improvement backlog** | Idea that needs discussion first            | See `LEARN.md` for workspace-specific location |

### 4. Capture

- Write the learning to the appropriate location (consult `LEARN.md` for workspace-specific paths)
- For scripts: make them executable, add comments explaining purpose
- For skills: follow the `.claude/skills/<name>/SKILL.md` pattern
- For memory: be concise but include enough context for future-you

### 5. Report to user

Always tell the user what you learned, in this format:

```markdown
## What I learned

**[Learning 1]**: [concise description]
→ Captured as: [script/skill/memory note] in `[path]`

**[Learning 2]**: [concise description]
→ Captured as: [script/skill/memory note] in `[path]`
```

If nothing meaningful was learned, say so honestly — don't fabricate insights.

## Examples

**After a build/deploy task:**

> "Mitto needs `nix-shell -p gnumake go` to build — neither `make` nor `go` are on PATH. Captured in memory."
> "The pull-build-install-restart cycle is a routine. Created `~/mitto/bin/rebuild.sh`."

**After debugging:**

> "The CSP nonce regression was caused by [X]. Added to memory so I check for this pattern next time."

**After research:**

> "Found that library X requires config Y. Added to the project skill."

## Constraints

- Be honest — don't manufacture learnings for the sake of it
- Prefer updating existing files over creating new ones
- Scripts should be idempotent and safe to re-run
- Always tell the user AND log to a file — both, not just one
