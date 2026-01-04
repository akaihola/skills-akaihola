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
- ✅ Folder support (INBOX, Sent, Drafts, Archive, etc.)
- ✅ Unicode support (Finnish characters, emojis)
- ✅ Date range filtering
- ✅ Multiple search criteria
- ✅ Message ID-based safe deletion

## Safety

- Delete operations show preview before execution (dry-run by default)
- Uses message UIDs for safe identification
- Changes sync immediately with IMAP server
- No local file manipulation

## Troubleshooting

For connection issues, see [references/troubleshooting.md](references/troubleshooting.md).

## Script Reference

For detailed script documentation, see [references/scripts.md](references/scripts.md).
