# Himalaya Email Manager

Natural language interface for email management using Himalaya IMAP CLI tool.

## Quick Start

### Get Daily Summary

Get a summary of emails from the past 24 hours:

```bash
scripts/email-summary.sh
```

### Search Emails

Search by sender, subject, date, or folder:

```bash
# Basic search (latest 20)
scripts/email-search.sh

# By sender
scripts/email-search.sh --from "spotify.com"

# By subject
scripts/email-search.sh --subject "invoice"

# By date range
scripts/email-search.sh --date-start "2025-12-01" --date-end "2025-12-31"

# Multiple filters
scripts/email-search.sh --from "@newsletter.com" --subject "unsubscribe" --limit 5
```

### Save Emails

Save email content to file:

```bash
# Save as markdown
scripts/email-save.sh 56873

# Save to specific directory
scripts/email-save.sh 56873 --output ~/saved-emails

# Save with date prefix
scripts/email-save.sh 56873 --date-prefix

# Save as JSON
scripts/email-save.sh 56873 --format json

# Save from Sent folder
scripts/email-save.sh --folder Sent 12345
```

### Delete Emails

Delete with safety preview:

```bash
# Preview deletion
scripts/email-delete.sh 56838

# Actually delete
scripts/email-delete.sh 56838 --execute
```

## Natural Language Queries

- "Show me emails from Spotify from the last week"
- "Find all emails about invoices"
- "Save email ID 56873"
- "Save email with attachments to ~/documents"
- "Delete email ID 56838"
- "What did I send yesterday?"

## Installation

Himalaya is installed via Nix:

```bash
nix-shell -p himalaya --run "himalaya --help"
```

The IMAP account is configured in `~/.config/himalaya/config.toml`.

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
