---
name: zed-threads
description: Read and inspect Zed AI conversation threads stored in the local SQLite database. Use when the user asks to "show Zed threads", "read my Zed AI conversations", "inspect Zed chat history", "dump Zed thread", or wants to examine past Zed AI interactions.
---

# Zed Threads Reader

Read AI conversation threads from Zed's local SQLite database and display them
as human-readable YAML.

## Database location

```
~/.local/share/zed/threads/threads.db
```

## Quick usage

```bash
# Show the most recent thread (index 0)
uv run ~/prg/skills-akaihola/zed-threads/scripts/read_zed_threads.py

# Show thread at a specific index (0 = most recent, 1 = second most recent, …)
uv run ~/prg/skills-akaihola/zed-threads/scripts/read_zed_threads.py 5

# Disable syntax highlighting (useful when piping to a file)
uv run ~/prg/skills-akaihola/zed-threads/scripts/read_zed_threads.py --no-color

# Combine: third thread without colour
uv run ~/prg/skills-akaihola/zed-threads/scripts/read_zed_threads.py 2 --no-color
```

The script prints the number of threads found and the number successfully parsed
to stderr, so you can see the thread count without it mixing into the YAML output.

## Output format

Each thread is rendered as YAML with the following structure:

```yaml
messages:
  - User: "user message text"
  - Agent: "assistant reply text"
  - Thinking: "chain-of-thought reasoning (if present)"
  - Tool:
      name: read_file
      input: { path: "/some/file" }
      result: "file contents..."
```

Mentions (file references, rules) are expanded inline:

````yaml
- User: |
    @/path/to/file.py
    ```py
    <file contents>
    ```
    Can you review this?
````

## Thread indexing

Threads are ordered by `updated_at DESC`, so index 0 is always the most recently
updated thread.

## Requirements

- `uv` in PATH (handles all Python dependencies via PEP 723 inline metadata)
- Zed installed with at least one AI conversation recorded
- Dependencies (auto-managed): `ruamel.yaml`, `zstandard`, `pygments`, `pydantic`
