# detect-secrets CLI Reference

## Installation

No installation needed — run via `uvx`:

```bash
uvx detect-secrets <command> [options]
```

## Commands

### scan

Create a baseline by scanning a repository for secrets.

```
uvx detect-secrets scan [options] [path ...]
```

**Positional arguments:**
- `path` — Files or directories to scan. Defaults to the current directory
  (git-tracked files only).

**Scan options:**
- `--all-files` — Scan all files recursively, not just git-tracked files.
- `--baseline FILENAME` — Update an existing baseline by importing its settings.
- `--force-use-all-plugins` — Use the latest plugins even when a baseline specifies
  a subset.
- `--slim` — Produce a minimal baseline (not compatible with `audit`).

**Plugin options:**
- `--list-all-plugins` — List all plugins that will be used.
- `-p, --plugin PLUGIN` — Path to a custom secret detector plugin.
- `--base64-limit LIMIT` — Entropy limit for base64 strings (0.0–8.0, default 4.5).
- `--hex-limit LIMIT` — Entropy limit for hex strings (0.0–8.0, default 3.0).
- `--disable-plugin NAME` — Disable a plugin by class name.

**Filter options:**
- `--exclude-lines REGEX` — Exclude lines matching a regex.
- `--exclude-files REGEX` — Exclude files matching a regex.
- `--exclude-secrets REGEX` — Exclude secrets matching a regex.
- `-f, --filter FILTER` — Path to a custom filter.
- `--disable-filter NAME` — Disable a built-in filter.

**Verification options:**
- `-n, --no-verify` — Skip verification of secrets.
- `--only-verified` — Only report verified secrets.

**Other options:**
- `--string [STRING]` — Scan an individual string instead of files.
- `--only-allowlisted` — Only scan lines flagged with `allowlist secret`.

### audit

Manually review a baseline to confirm or dismiss findings.

```
uvx detect-secrets audit FILENAME
```

Interactive workflow:
1. Run `scan` to generate a `.secrets.baseline` file.
2. Run `audit .secrets.baseline` to review each finding interactively.
3. Mark findings as true/false positives.

## Global Options

- `-v, --verbose` — Verbose mode.
- `--version` — Display version information.
- `-C <path>` — Run as if started in `<path>`.
- `-c, --cores NUM` — Number of cores for parallel processing (default: all).

## Inline Allowlisting

Add a comment to suppress a specific line:

```python
API_KEY = "not-a-real-key"  # pragma: allowlist secret
```

## Output Format

JSON with the following structure:

```json
{
  "version": "1.5.0",
  "plugins_used": [...],
  "filters_used": [...],
  "results": {
    "file.py": [
      {
        "type": "Secret Keyword",
        "filename": "file.py",
        "hashed_secret": "...",
        "is_verified": false,
        "line_number": 10
      }
    ]
  },
  "generated_at": "2026-02-13T00:00:00Z"
}
```

Empty `"results": {}` means no secrets were detected.
