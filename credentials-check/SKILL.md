---
name: credentials-check
description: >-
  Scan files and directories for leaked credentials using detect-secrets.
  Use when the user asks to "check for credentials", "scan for secrets",
  "find leaked keys", "detect secrets", "check for API keys",
  or wants to verify no credentials are committed.
---

# Credentials Check

Scan files, directories, or git repositories for accidentally committed
credentials using Yelp's `detect-secrets` via `uvx`.

## Quick Start

```bash
# Scan the current directory (git-tracked files only)
uvx detect-secrets scan

# Scan a specific directory (all files, including non-git)
uvx detect-secrets scan --all-files path/to/dir

# Scan the .git/ directory for credentials in git internals
uvx detect-secrets scan .git/

# Scan a single string
uvx detect-secrets scan --string 'AKIAIOSFODNN7EXAMPLE'
```

## Interpreting Results

The output is JSON. A clean scan looks like:

```json
{
  "results": {}
}
```

A finding looks like:

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

When findings exist:
1. Review each finding — some may be false positives (test data, example keys).
2. For real secrets: remove the credential, rotate it, and add the file path to
   `.secrets.baseline` or an allowlist.
3. For false positives: add an inline `# pragma: allowlist secret` comment, or
   exclude the pattern via `--exclude-secrets`.

## Common Workflows

### Pre-commit check

```bash
uvx detect-secrets scan > .secrets.baseline
uvx detect-secrets audit .secrets.baseline
```

### Scan with custom entropy thresholds

```bash
uvx detect-secrets scan --base64-limit 5.0 --hex-limit 3.5
```

### Disable noisy plugins

```bash
uvx detect-secrets scan --disable-plugin HexHighEntropyString
```

### Scan non-git files

```bash
uvx detect-secrets scan --all-files .
```

## Detected Secret Types

detect-secrets ships with 26 plugins covering:

| Plugin                    | Detects                              |
|---------------------------|--------------------------------------|
| AWSKeyDetector            | AWS access keys and secret keys      |
| AzureStorageKeyDetector   | Azure storage account keys           |
| BasicAuthDetector         | Basic auth strings in URLs           |
| GitHubTokenDetector       | GitHub personal access tokens        |
| GitLabTokenDetector       | GitLab personal/project tokens       |
| JwtTokenDetector          | JSON Web Tokens                      |
| PrivateKeyDetector        | PEM-encoded private keys             |
| Base64HighEntropyString   | High-entropy base64 strings          |
| HexHighEntropyString      | High-entropy hex strings             |
| KeywordDetector           | Passwords, secrets, tokens in code   |
| OpenAIDetector            | OpenAI API keys                      |
| StripeDetector            | Stripe API keys                      |
| SlackDetector             | Slack tokens and webhooks            |
| TwilioKeyDetector         | Twilio API keys                      |
| SendGridDetector          | SendGrid API keys                    |
| TelegramBotTokenDetector  | Telegram bot tokens                  |
| DiscordBotTokenDetector   | Discord bot tokens                   |
| MailchimpDetector         | Mailchimp API keys                   |
| NpmDetector               | npm tokens                           |
| PypiTokenDetector         | PyPI API tokens                      |
| ArtifactoryDetector       | JFrog Artifactory tokens             |
| CloudantDetector          | IBM Cloudant credentials             |
| IbmCloudIamDetector       | IBM Cloud IAM keys                   |
| IbmCosHmacDetector        | IBM COS HMAC credentials             |
| SoftlayerDetector         | SoftLayer API keys                   |
| SquareOAuthDetector       | Square OAuth tokens                  |

## References

- `references/detect_secrets_cli.md` — Full CLI reference and advanced options.
