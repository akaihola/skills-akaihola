---
name: secrets-scan
description: >-
  Scan a git repository for leaked credentials, API keys, tokens, and other
  secrets using detect-secrets (uvx) and secretlint (bun). Runs both tools,
  reads each flagged line, and classifies findings as needing review vs. likely
  false positives. Use when the user asks to "scan for secrets", "check for
  credentials", "find leaked keys", "detect secrets", "check for API keys",
  "check for leaked tokens", or wants to verify no credentials are committed.
  Supersedes the credentials-check skill.
---

# Secrets Scan

Scan a git repository for leaked credentials using two complementary tools:

- **`detect-secrets`** (Yelp, PyPI) – entropy-based detection of 26+ secret
  types including AWS keys, GitHub tokens, private keys, and high-entropy
  strings
- **`secretlint`** (npm) – pattern-based detection tuned to known token
  formats (Slack `xoxb-*`, npm tokens, GCP service account keys, etc.)

Running both catches what each misses individually. The automation script
(`scripts/scan.py`) handles setup, runs both tools, reads the flagged lines,
auto-classifies findings, and emits a combined Markdown report.

## Quick Start (automation script)

```bash
# Scan the current directory (git-tracked files, both tools)
uv run /path/to/skills-akaihola/secrets-scan/scripts/scan.py

# Scan a specific repo
uv run /path/to/skills-akaihola/secrets-scan/scripts/scan.py /path/to/repo

# JSON output (for programmatic use or piping)
uv run /path/to/skills-akaihola/secrets-scan/scripts/scan.py --json

# detect-secrets only (faster; skip secretlint setup)
uv run /path/to/skills-akaihola/secrets-scan/scripts/scan.py --no-secretlint

# Include non-git-tracked files
uv run /path/to/skills-akaihola/secrets-scan/scripts/scan.py --all-files
```

The script exits with code 0 when all findings are classified as likely false
positives, or code 1 when any finding needs human review.

## Running the Tools Manually

### detect-secrets

```bash
# Scan current directory (git-tracked files only)
uvx detect-secrets scan

# Scan all files, excluding .venv/ and node_modules/
uvx detect-secrets scan --all-files \
  --exclude-files '\.venv/' \
  --exclude-files '\.git/' \
  --exclude-files 'node_modules/'

# Scan a single string
uvx detect-secrets scan --string 'AKIAIOSFODNN7EXAMPLE'

# Suppress noisy HexHighEntropyString detector
uvx detect-secrets scan --disable-plugin HexHighEntropyString

# Generate a baseline for pre-commit use
uvx detect-secrets scan > .secrets.baseline
uvx detect-secrets audit .secrets.baseline
```

### secretlint

secretlint requires a config file and its rule package to be co-installed.
Set up once in a temp directory, then run on git-tracked files:

```bash
# One-time setup
mkdir -p /tmp/sl-check
echo '{"name":"sl-check","version":"1.0.0","private":true}' \
  > /tmp/sl-check/package.json
echo '{"rules":[{"id":"@secretlint/secretlint-rule-preset-recommend"}]}' \
  > /tmp/sl-check/.secretlintrc.json
cd /tmp/sl-check
bun add --silent secretlint @secretlint/secretlint-rule-preset-recommend

# Run against repo (from repo root)
git ls-files | grep -v '\.venv' | grep -v node_modules \
  | xargs /tmp/sl-check/node_modules/.bin/secretlint \
      --secretlintrc /tmp/sl-check/.secretlintrc.json

# JSON output
git ls-files | xargs /tmp/sl-check/node_modules/.bin/secretlint \
  --format json --secretlintrc /tmp/sl-check/.secretlintrc.json
```

## Interpreting Results

### detect-secrets output

```json
{
  "results": {
    "path/to/file.py": [
      {
        "type": "AWS Access Key",
        "filename": "path/to/file.py",
        "hashed_secret": "abc123...",
        "is_verified": false,
        "line_number": 42
      }
    ]
  }
}
```

`"results": {}` means no secrets found. The secret value is hashed; use the
line number to read the actual content.

### secretlint output (JSON)

```json
[
  {
    "filePath": "/abs/path/to/file",
    "messages": [
      {
        "ruleId": "@secretlint/secretlint-rule-slack",
        "messageId": "SLACK_TOKEN",
        "message": "found slack token: ****",
        "loc": { "start": { "line": 7, "column": 24 } },
        "severity": "error",
        "docsUrl": "https://github.com/secretlint/secretlint/..."
      }
    ]
  }
]
```

## Classifying Findings

For every finding, read the flagged line. Then apply this decision tree:

```
Does the line contain a placeholder?
  → "your_key_here", "changeme", "example.com", "INSERT_", etc.
  → AWS doc example key: AKIAIOSFODNN7EXAMPLE
  → Generic connection string: "username:password@localhost"
  YES → Likely false positive. Add # pragma: allowlist secret comment.

Is it in a test fixture or documentation file?
  YES → Likely false positive. Review context.

Is it a high-entropy string in a third-party library (e.g. yt_dlp, node_modules)?
  YES → False positive. Exclude the path from future scans.

Otherwise → Real finding. Rotate the credential immediately.
```

See `references/classifying-findings.md` for a full table of common false
positive patterns and remediation steps.

## Handling Real Secrets

1. **Rotate immediately** – treat the credential as compromised. Revoke and
   re-issue even if the commit is old; assume it was scraped.
2. **Remove from source** – use an environment variable or a secrets manager:

   ```python
   # Before
   API_KEY = "klevu-15488592134928913"

   # After
   import os
   API_KEY = os.environ["KLEVU_API_KEY"]
   ```

3. **Rewrite history (optional)** – `git filter-repo` or BFG Repo Cleaner can
   strip the secret from all commits, but only matters if the repo is private
   and you have not pushed to a public remote.
4. **Add to baseline** to silence future scans for confirmed false positives:
   ```bash
   uvx detect-secrets scan > .secrets.baseline
   # commit .secrets.baseline
   ```

## Suppressing False Positives

### detect-secrets – inline allowlist

```python
API_KEY = "klevu-example-key"  # pragma: allowlist secret
```

### detect-secrets – exclude a file pattern

```bash
uvx detect-secrets scan --exclude-files '\.venv/' --exclude-files 'tests/fixtures/'
```

### secretlint – ignore file

Create `.secretlintignore` in the repo root (gitignore syntax):

```
.venv/
node_modules/
tests/fixtures/
```

## detect-secrets Plugin Reference

| Plugin                   | Detects                            |
| ------------------------ | ---------------------------------- |
| AWSKeyDetector           | AWS access keys and secret keys    |
| AzureStorageKeyDetector  | Azure storage account keys         |
| BasicAuthDetector        | Basic auth strings in URLs         |
| GitHubTokenDetector      | GitHub personal access tokens      |
| GitLabTokenDetector      | GitLab personal/project tokens     |
| JwtTokenDetector         | JSON Web Tokens                    |
| PrivateKeyDetector       | PEM-encoded private keys           |
| Base64HighEntropyString  | High-entropy base64 strings        |
| HexHighEntropyString     | High-entropy hex strings           |
| KeywordDetector          | passwords, secrets, tokens in code |
| OpenAIDetector           | OpenAI API keys                    |
| StripeDetector           | Stripe API keys                    |
| SlackDetector            | Slack tokens and webhooks          |
| TwilioKeyDetector        | Twilio API keys                    |
| SendGridDetector         | SendGrid API keys                  |
| TelegramBotTokenDetector | Telegram bot tokens                |
| DiscordBotTokenDetector  | Discord bot tokens                 |
| MailchimpDetector        | Mailchimp API keys                 |
| NpmDetector              | npm tokens                         |
| PypiTokenDetector        | PyPI API tokens                    |
| ArtifactoryDetector      | JFrog Artifactory tokens           |
| CloudantDetector         | IBM Cloudant credentials           |
| IbmCloudIamDetector      | IBM Cloud IAM keys                 |
| IbmCosHmacDetector       | IBM COS HMAC credentials           |
| SoftlayerDetector        | SoftLayer API keys                 |
| SquareOAuthDetector      | Square OAuth tokens                |

## detect-secrets CLI Reference

### scan options

| Flag                      | Description                                            |
| ------------------------- | ------------------------------------------------------ |
| `--all-files`             | Scan all files recursively, not just git-tracked       |
| `--baseline FILENAME`     | Update an existing baseline file                       |
| `--force-use-all-plugins` | Use latest plugins even if baseline specifies a subset |
| `--slim`                  | Minimal baseline (not compatible with `audit`)         |
| `--list-all-plugins`      | List all plugins that will be used                     |
| `-p, --plugin PATH`       | Path to a custom detector plugin                       |
| `--base64-limit N`        | Entropy limit for base64 strings (0–8, default 4.5)    |
| `--hex-limit N`           | Entropy limit for hex strings (0–8, default 3.0)       |
| `--disable-plugin NAME`   | Disable a plugin by class name                         |
| `--exclude-lines REGEX`   | Skip lines matching regex                              |
| `--exclude-files REGEX`   | Skip files matching regex                              |
| `--exclude-secrets REGEX` | Skip secrets matching regex                            |
| `--string [STRING]`       | Scan a single string instead of files                  |
| `-n, --no-verify`         | Skip online verification of secrets                    |
| `--only-verified`         | Only report verified secrets                           |
| `-v, --verbose`           | Verbose output                                         |
| `-C PATH`                 | Run as if started in PATH                              |
| `-c, --cores N`           | Number of parallel cores (default: all)                |

### audit options

```bash
uvx detect-secrets audit .secrets.baseline
```

Interactive workflow: generates `.secrets.baseline`, then `audit` lets you
mark each finding as true/false positive.
