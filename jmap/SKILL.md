---
name: jmap
description: Generic JMAP email utilities. Use when syncing emails from any sender domain to disk, querying the local JMAP server, or downloading attachments. The sync script lives at ~/.claude/skills/jmap/sync_emails.py — always invoke it directly instead of writing ad-hoc Python.
---

# JMAP Email Utilities

## Infrastructure

- JMAP proxy runs on the remote host; accessed locally via **reverse SSH tunnel on port 8895**
- Base URL: `http://127.0.0.1:8895`
- Primary account: `kaihola`

Verify the tunnel is up before any JMAP operation:
```bash
xh GET http://127.0.0.1:8895/.well-known/jmap
```
If that fails with "Connection refused", ask the user to bring up the tunnel from the remote host.

## Email Sync Script

**Always run the pre-made script** — never write ad-hoc Python for email sync:

```bash
python3 ~/.claude/skills/jmap/sync_emails.py \
  --from-filter <domain-or-address-fragment> \
  --output-dir  <absolute-path-to-email-folder>
```

Optional flags:
| Flag | Default | Purpose |
|------|---------|---------|
| `--account` | `kaihola` | JMAP account ID |
| `--jmap-url` | `http://127.0.0.1:8895` | JMAP base URL |
| `--limit` | `500` | Max emails per run |

### Examples

```bash
# All mail from one sender domain
python3 ~/.claude/skills/jmap/sync_emails.py \
  --from-filter example.com \
  --output-dir ~/documents/archive/example-com/emails

# A second sender, archived separately
python3 ~/.claude/skills/jmap/sync_emails.py \
  --from-filter example.org \
  --output-dir ~/documents/archive/example-org/emails
```

The script is idempotent: existing `email.md` files and attachments are skipped.

## Output Layout

```
<output-dir>/YYYY-MM-DD <Subject>/
  email.md        # headers + plain-text body
  <attachment>    # original filename, downloaded once
```

Characters illegal in filenames (`< > : " / \ | ? *`) are replaced with `_`.

## JMAP Quick Reference

| Operation | Filter field | Example value |
|-----------|-------------|---------------|
| By sender domain | `"from"` | `"example.com"` |
| By mailbox | `"inMailbox"` | `"INBOX"` |
| Full-text search | `"text"` | `"capital call"` |
| Date range | `"after"` / `"before"` | `"2026-01-01T00:00:00Z"` |

Sort options: `"receivedAt"`, `"subject"`, `"size"` — add `"isAscending": false` for newest-first.

Download URL pattern:
```
http://127.0.0.1:8895/jmap/download/{accountId}/{blobId}/{filename}
```
Both `blobId` and `filename` must be URL-encoded.
