# Classifying Secrets-Scan Findings

Both `detect-secrets` and `secretlint` produce false positives. This reference
lists common patterns and how to handle each.

## Decision Criteria

| Signal                                                                                                | Classification  | Action                                    |
| ----------------------------------------------------------------------------------------------------- | --------------- | ----------------------------------------- |
| Line contains a placeholder string (see table below)                                                  | False positive  | Add `# pragma: allowlist secret`          |
| File is in `.venv/`, `node_modules/`, `dist/`                                                         | False positive  | Exclude path from scan config             |
| File is a test fixture with synthetic data                                                            | False positive  | Exclude via `--exclude-files`             |
| File is documentation or a SKILL.md with example keys                                                 | False positive  | Add allowlist comment or exclude          |
| Variable name is generic (`key`, `secret`, `password`) but value is empty string or env var reference | False positive  | No action needed                          |
| Value matches a known vendor format AND is not a placeholder                                          | **Real secret** | Rotate + remove                           |
| High-entropy string in a `.py` or `.js` file in the project (not a dep)                               | Likely real     | Read line to confirm, then rotate if real |

## Common Placeholder Strings (auto-classified by scan.py)

These strings cause `scan.py` to mark a finding as `likely-false-positive`:

| Pattern                          | Why it appears                        |
| -------------------------------- | ------------------------------------- |
| `your_key_here`, `your-api-key`  | Documentation template                |
| `your_actual_key_here`           | SKILL.md / README placeholder         |
| `changeme`                       | Default config value                  |
| `AKIAIOSFODNN7EXAMPLE`           | AWS official documentation example    |
| `wJalrXUtnFEMI/K7MDENG`          | AWS official documentation secret key |
| `username:password@`             | Generic connection string template    |
| `xoxb-your-slack-bot-token-here` | Slack MCP example config              |
| `<your...`, `[your...`           | Documentation prompt                  |
| `INSERT_`, `TODO:`, `FIXME:`     | Unset placeholder marker              |

## False Positive Examples by Tool

### detect-secrets – HexHighEntropyString

Very common in third-party libraries (e.g. `yt_dlp`, `youtube_dl`) where
video site IDs, CSS hashes, and other hex constants trip the entropy detector.

**Fix:** Exclude the vendor path:

```bash
uvx detect-secrets scan --exclude-files '\.venv/' --exclude-files 'node_modules/'
```

Or raise the hex entropy threshold if too many false positives in your own code:

```bash
uvx detect-secrets scan --hex-limit 4.0
```

### detect-secrets – Basic Auth Credentials

Triggered by any URL containing `:` between host and path, or `user:pass@`
patterns in documentation.

**Common false positives:**

- `postgresql://username:password@localhost/db` – connection string template
- `https://user:pass@proxy.example.com` – proxy docs

### detect-secrets – Secret Keyword

Triggered when variable names like `password`, `secret`, `token`, `api_key`
are assigned any value (including empty strings and env var lookups).

**False positive examples:**

```python
password = os.getenv("DB_PASSWORD")   # reads from env, not a secret
api_key = ""                           # empty default
SECRET_KEY = config.get("secret_key") # reads from config
```

### secretlint – SLACK_TOKEN

Triggered by the `xoxb-` prefix. The full string `xoxb-your-slack-bot-token-here`
is a placeholder but still fires because the prefix matches.

**Fix:** Add to `.secretlintignore`:

```
mcp-to-skill/assets/examples/
docs/
```

### secretlint – GCP_SERVICE_ACCOUNT / GITHUB_TOKEN patterns

These are pattern-matched against well-known prefixes. Any placeholder that
uses the same prefix (e.g. `ghp_yourTokenHere`) will trigger.

## Suppressing False Positives

### Inline suppression (detect-secrets)

```python
EXAMPLE_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret
```

### Exclude a file or directory (detect-secrets)

Add to your scan command or `.secrets.baseline`:

```bash
uvx detect-secrets scan \
  --exclude-files '\.venv/' \
  --exclude-files 'tests/fixtures/' \
  --exclude-files 'docs/'
```

### Exclude paths (secretlint)

Create `.secretlintignore` in the repo root:

```
.venv/
node_modules/
docs/
tests/fixtures/
```

### Persist allowlist via baseline

After reviewing all findings and marking false positives:

```bash
uvx detect-secrets scan > .secrets.baseline
uvx detect-secrets audit .secrets.baseline
# Mark each finding; baseline stores your decisions
git add .secrets.baseline
git commit -m "chore: add detect-secrets baseline"
```

Future scans diff against the baseline and only report new findings.

## Verified vs Unverified Findings

`detect-secrets` can attempt live verification for some secret types (e.g.
AWS keys via STS `GetCallerIdentity`). A finding marked `"is_verified": true`
is definitely a live credential. `"is_verified": false` means either:

- Verification was skipped (`--no-verify`)
- The token format matched but the key is no longer active
- It is a false positive

Use `--no-verify` to speed up scans in CI where network calls are undesirable.
Use `--only-verified` to focus only on confirmed live secrets.
