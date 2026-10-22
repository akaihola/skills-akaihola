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
triaging findings. A finding is `likely-false-positive` only when the detected
value itself contains a placeholder marker; words elsewhere on its line do not
count. Every other finding is `review-required`. Neither label proves that a
credential is live or harmless.

The report names each scanner's outcome: `ran`, `skipped` on request
(`--no-secretlint`) or `failed` with a reason. A failure covers an unexpected
exit status, unparsable output, a setup failure (`bun add`, `git ls-files`)
or a secretlint batch that was not scanned. A requested skip is not a failure.

| Exit | Meaning |
| --- | --- |
| 0 | Every requested scanner finished and no finding needs review |
| 1 | Every requested scanner finished and a finding needs review |
| 2 | A requested scanner failed, or the arguments are invalid |

Exit 2 outranks exit 1: the report still lists findings from the scanners that
finished, but the scan is incomplete. Rerun it after fixing the named scanner
before calling a repository clean.

Never print flagged source lines, credential values, or raw secretlint messages.
Use file/line and detector kind when reporting or handing off findings.
Do not run a credential verification or rotate/revoke credentials without
authorization for that operation. A confirmed exposed credential requires
rotation; deleting it from source does not revoke it.

## Offline validation

`--help` exits before installing or launching either scanner. The scanner
tests put fake `uvx`, `bun`, `git` and secretlint executables first on `PATH`;
they and the redaction and attachment/cache regression tests use synthetic
data:

```bash
uv run --no-project --with pytest --with typer --with rich pytest tests/test_secrets_scan.py tests/test_security_boundaries.py -q
```
