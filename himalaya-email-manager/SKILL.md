---
name: himalaya-email-manager
description: Email management using Himalaya CLI tool (IMAP). Search, summarize, and delete emails from an IMAP account. Supports natural language queries for email operations.
---

# Himalaya Email Manager

## Configuration

Invocation: `uv run ~/.claude/skills/himalaya-email-manager/scripts/<script>.py` (handles Python environment and dependencies, do NOT cd into skill directory)

## Get Daily Email Summary

Show emails from the past 24 hours in INBOX and Sent folders:

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-summary.py
```

## Search Emails

Find emails by sender, subject, date range, or folder:

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-search.py [options]
```

**Options:**

- `--folder FOLDER` - Folder to search (default: INBOX)
- `--from SENDER` - Filter by sender email/name (case-insensitive)
- `--subject TEXT` - Filter by subject text (case-insensitive)
- `--date-start DATE` - Start date (YYYY-MM-DD)
- `--date-end DATE` - End date (YYYY-MM-DD)
- `--limit N` - Maximum results (default: 20, capped at 100)
- `--no-limit` - Bypass the 100-result limit cap
- `--help` - Show help message

All filters apply with AND logic. FROM matches both sender name and email address.

**Examples:**

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-search.py --from "spotify.com" --subject "invoice" --limit 5
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-search.py --date-start "2025-12-17" --date-end "2025-12-31"

# Bypass the 100-result cap — both flags required
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-search.py --limit 200 --no-limit
```

## Save Emails to File

Save email content to a file in various formats:

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email_save.py <message-id> [options]
```

**Options:**

- `--folder FOLDER` - Folder to search (default: INBOX)
- `--output PATH` - Output directory or file path (default: current directory)
- `--format FORMAT` - Output format: markdown, text, or json (default: markdown)
- `--date-prefix` - Add YYYY-MM-DD date prefix to filename (uses email date)
- `--no-download-attachments` - Skip downloading email attachments (default: attachments are downloaded)
- `--attachment-dir PATH` - Directory for attachments (default: current directory, same as email save location)
- `--overwrite` - Overwrite existing file without confirmation
- `--help` - Show help message

## Post-Save Attachment Processing

After saving emails, automatically inspect each attachment using vision capabilities:

1. **Use vision to analyze** each image attachment
2. **Classify** the content type (icon, logo, table, signature, complex image)
3. **Convert** to text representation where appropriate
4. **Update** the saved email file with replacements
5. **Delete** replaced attachment files

### Classification Guidelines

| Content Type              | Characteristics                            | Replacement Format                          |
| ------------------------- | ------------------------------------------ | ------------------------------------------- |
| **Icons/Emojis/Symbols**  | Small, single glyph, no text               | Unicode character (e.g., ✓, ★, →)           |
| **Logos**                 | Company/brand imagery, decorative          | Text description: `[Logo: Company Name]`    |
| **Signatures**            | Handwritten-style text, often at email end | Text: `[Signature: Name]` or extracted text |
| **Brief text**            | Very short text content (1-3 words)        | Extracted text verbatim                     |
| **Simple tables**         | Single-line cells, no images               | Markdown table                              |
| **Complex tables**        | Multi-line cells, no images                | ASCII table                                 |
| **Photos/Complex images** | Photographs, screenshots, diagrams         | **Keep unchanged**                          |

**Filename behavior:**

- Default: `{message-id}.{ext}`
- With `--date-prefix`: `{YYYY-MM-DD}-{subject-sanitized}.{ext}`
- Subject characters: Spaces and emojis preserved, slashes converted to dashes

**Examples:**

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email_save.py 56873
uv run ~/.claude/skills/himalaya-email-manager/scripts/email_save.py 56873 --output ~/saved-emails --date-prefix
uv run ~/.claude/skills/himalaya-email-manager/scripts/email_save.py --folder Sent 12345 --output ~/sent-emails
uv run ~/.claude/skills/himalaya-email-manager/scripts/email_save.py 56873 --no-download-attachments
```

## Read Full Email Content

Fetch and display the full body of a specific email by message ID:

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-read.py <message-id> [options]
```

**Options:**

- `--folder FOLDER` - Folder to read from (default: INBOX)
- `--format FORMAT` - Output format: `text` (default), `json`, `raw`
- `--preserve-html` - Keep HTML content (for json/raw formats)

**Examples:**

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-read.py --folder Sent 12345 --format json
```

## Delete Emails

Delete emails by message ID with safety preview:

```bash
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-delete.py <message-id> [options]
```

**Options:**

- `--folder FOLDER` - Folder to delete from (default: INBOX)
- `--execute` - Actually perform deletion (default: dry-run mode)
- `--help` - Show help message

**Safety:** Always run in dry-run mode first to verify the correct message.
In interactive mode, you'll be prompted for confirmation before deletion.

**Examples:**

```bash
# Preview deletion
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-delete.py 56838

# Actually delete (interactive - will prompt for confirmation)
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-delete.py 56838 --execute

# Delete from specific folder
uv run ~/.claude/skills/himalaya-email-manager/scripts/email-delete.py --folder Sent 12345 --execute
```

## Implementation Notes

**When calling scripts:**

1. Always run delete operations in dry-run mode first without --execute flag
2. Ask user for confirmation before running delete with --execute flag (interactive mode only)

**Avoid these pitfalls:**

- Don't use --since or --until (not implemented - use --date-start/--date-end)
- Don't try to search body content (only headers are available in JSON output)
- Don't forget to add --execute flag when actually deleting (dry-run by default)

**Follow this workflow for search and delete:**

1. Use email-search.py to find messages
2. Review results with user
3. Use email-delete.py <ID> to preview deletion
4. Get user confirmation
5. Use email-delete.py <ID> --execute to actually delete
