# Add a New Entry to the Library

## Context
Register a new skill, agent, or prompt in the library catalog.

## Input
The user provides: name, description, source path or GitHub URL, and optionally the type and dependencies.

## Steps

### 1. Sync the Library Repo
```bash
cd ~/prg/skills-akaihola && git pull
```

### 2. Determine the Type
From the user's prompt or the source path:
- Source contains `SKILL.md` or user says "skill" → type: `skill`
- Source contains `AGENT.md` or user says "agent" → type: `agent`
- User says "prompt" → type: `prompt`
- If ambiguous, ask.

### 3. Validate the Source
- **Local path**: Check the file exists. If in `skills-akaihola`, prefer the `~/prg/skills-akaihola/...` form.
- **GitHub URL**: Confirm it's well-formed and points to a specific file.
- Source must point to a file, not a directory.

### 4. Detect Dependencies
Look through the skill/agent/prompt file for `/<skill|agent|prompt>:name` references in the frontmatter or content. Format as typed references: `skill:name`, `agent:name`, `prompt:name`. Warn if a dependency isn't yet in `library.yaml`.

### 5. Add the Entry to library.yaml
Read `~/prg/skills-akaihola/library/library.yaml`, add under the correct section, **sorted alphabetically by name**:

```yaml
- name: <name>
  description: <description>
  source: <source>
  requires: [<typed:refs>]  # omit if no dependencies
```

### 6. Commit and Push
```bash
cd ~/prg/skills-akaihola
git add library/library.yaml
git commit -m "library: added <type> <name>"
git push
```

### 7. Confirm
Tell the user the entry was added and is now available via `/library use <name>`.
