---
name: secrets-scan
description: Scan a Git repository for leaked credentials with detect-secrets and secretlint, reporting locations and detector types without secret values. Use for requested secret, token or credential scans.
---

# Secrets Scan

[scripts/scan.py](scripts/scan.py) combines detect-secrets and secretlint.
It reads flagged lines internally to classify them, but emits only locations,
detector types and classifications in Markdown or JSON.

Resolve the helper from this skill’s installed directory. It requires Python
3.10+, Git and `uvx`; secretlint setup also needs `bun`. Scans may install
scanner packages, but detect-secrets is always invoked with `--no-verify`.
There is no wrapper option to enable credential verification.

## Usage

```bash
uv run /path/to/secrets-scan/scripts/scan.py --help
uv run /path/to/secrets-scan/scripts/scan.py /path/to/repo
uv run /path/to/secrets-scan/scripts/scan.py /path/to/repo --json
uv run /path/to/secrets-scan/scripts/scan.py /path/to/repo --no-secretlint
uv run /path/to/secrets-scan/scripts/scan.py /path/to/repo --all-files
```

| Argument | Behaviour |
| --- | --- |
| `path` | Repository directory; defaults to the current directory |
| `--json` | Emit the sanitized combined JSON report |
| `--no-secretlint` | Skip secretlint installation and scanning |
| `--all-files` | Include untracked files for detect-secrets only; secretlint still scans Git-tracked files |

The default exclusions cover common dependency, build and cache directories.
The two scanners use different exclusion lists; see
[EXCLUDE_DIR_REGEXES and EXCLUDE_DIR_PREFIXES](scripts/scan.py).

## Interpret a result

Read [classification and limits](references/classifying-findings.md) before
triaging findings. A placeholder substring anywhere on a flagged line causes
`likely-false-positive`; every other line is `review-required`. Neither label
proves that a credential is live or harmless.

Exit 1 means at least one reported finding needs review (or the path is invalid).
Exit 0 means no reported finding needs review. Some scanner failures are logged
and converted to empty results, so exit 0 alone does not prove a complete scan.
Check stderr for installation, scanner and parse failures.

Never print flagged source lines, credential values, or raw secretlint messages.
Use file/line and detector kind when reporting or handing off findings.
Do not run a credential verification or rotate/revoke credentials without
authorization for that operation. A confirmed exposed credential requires
rotation; deleting it from source does not revoke it.

## Offline validation

`--help` exits before installing or launching either scanner. Existing
redaction and attachment/cache regression tests use synthetic data:

```bash
uv run --no-project --with pytest --with typer --with rich pytest tests/test_security_boundaries.py -q
```
