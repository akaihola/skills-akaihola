# Himalaya Email Manager

Natural language interface for email management using Himalaya IMAP CLI tool.

## Quick Start

### Get Daily Summary

Get a summary of emails from the past 24 hours:

```bash
uv run scripts/email-summary.py
```

### Search Emails

Search by sender, subject, date, or folder:

```bash
# Basic search (latest 20)
uv run scripts/email-search.py

# By sender
uv run scripts/email-search.py --from "spotify.com"

# By subject
uv run scripts/email-search.py --subject "invoice"

# By date range
uv run scripts/email-search.py --date-start "2025-12-01" --date-end "2025-12-31"

# Multiple filters
uv run scripts/email-search.py --from "@newsletter.com" --subject "unsubscribe" --limit 5
```

### Save Emails

Save email content to file:

```bash
# Save as markdown
uv run scripts/email-save.py 56873

# Save to specific directory
uv run scripts/email-save.py 56873 --output ~/saved-emails

# Save with date prefix
uv run scripts/email-save.py 56873 --date-prefix

# Save as JSON
uv run scripts/email-save.py 56873 --format json

# Save from Sent folder
uv run scripts/email-save.py --folder Sent 12345
```

### Delete Emails

Delete with safety preview:

```bash
# Preview deletion
uv run scripts/email-delete.py 56838

# Actually delete
uv run scripts/email-delete.py 56838 --execute
```

## Natural Language Queries

- "Show me emails from Spotify from the last week"
- "Find all emails about invoices"
- "Save email ID 56873"
- "Save email with attachments to ~/documents"
- "Delete email ID 56838"
- "What did I send yesterday?"

## Installation

Himalaya must be installed on your system. Test your installation:

```bash
himalaya --help
```

The IMAP account is configured in `~/.config/himalaya/config.toml`.

All scripts use PEP 723 inline metadata and require Python 3.13+. Invoke with `uv run` to automatically handle Python environment and dependencies.

- ✅ Fast IMAP search (server-side)
- ✅ Safe deletion with preview (dry-run by default)
- ✅ Save emails to file (markdown, text, JSON formats)
- ✅ Download email attachments with custom directory support
- ✅ Folder support (INBOX, Sent, Drafts, Archive, etc.)
- ✅ Unicode support (Finnish characters, emojis)
- ✅ Date range filtering
- ✅ Multiple search criteria
- ✅ Message ID-based safe deletion

## Safety

- Delete operations show preview before execution (dry-run by default)
- Save operations prompt before overwriting existing files (use --overwrite to skip)
- Attachment downloads default to himalaya's downloads directory (customize with --attachment-dir)
- Uses message UIDs for safe identification
- Changes sync immediately with IMAP server

## Troubleshooting

For connection issues, see [references/troubleshooting.md](references/troubleshooting.md).

## Script Reference

For detailed script documentation, see [references/scripts.md](references/scripts.md).
