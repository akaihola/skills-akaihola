# Script Reference

Detailed documentation for Himalaya Email Manager scripts.

## email-summary.py

Shows emails from the past 24 hours in INBOX and Sent folders.

**Usage:**

```bash
uv run scripts/email-summary.py
```

**Flags:** None (uses fixed 24-hour window)

**Output format:**

- Markdown with timestamps, senders, and subjects
- Categorized by folder (📥 INBOX, 📤 Sent)
- Unicode support (Finnish characters, emojis)

**Example output:**

```markdown
# Email Summary - December 31, 2025

Last 24 hours

## 📥 INBOX (10 emails)

• 2025-12-31 13:54+00:00 - Spotify - Viimeinen tilaisuus saada 2 kk hintaan 6,50 €
• 2025-12-31 06:31+00:00 - Makita Oy - Puutarhakoneiden huolto talvikaudella – etuja varaosiin
• 2025-12-31 06:15+00:00 - HS Hyviä uutisia - Viikon tärkeimmät toiveikkaat uutiset.

## 📤 Sent (0 emails)

No emails sent in the last 24 hours.
```

## email-search.py

Search emails by various criteria with case-insensitive matching.

**Usage:**

```bash
uv run scripts/email-search.py [options]
```

**Options:**

- `--folder FOLDER` - Folder to search (default: INBOX)
- `--from SENDER` - Filter by sender email/name (case-insensitive)
- `--subject TEXT` - Filter by subject text (case-insensitive)
- `--date-start DATE` - Start date (YYYY-MM-DD)
- `--date-end DATE` - End date (YYYY-MM-DD)
- `--limit N` - Maximum results (default: 20)
- `--no-limit` - Bypass the 100-result limit cap
- `-v, --verbose` - Show himalaya commands being executed
- `--help` - Show help message

**Search logic:**

- All filters are case-insensitive
- Multiple filters apply with AND logic
- Results include message IDs for deletion
- Dates are in YYYY-MM-DD format
- FROM filter matches both sender name and email address

**Examples:**

```bash
# Search by sender (case-insensitive)
uv run scripts/email-search.py --from "spotify.com"

# Search by subject
uv run scripts/email-search.py --subject "invoice"

# Search by date range
uv run scripts/email-search.py --date-start "2025-12-17" --date-end "2025-12-31"

# Search in Sent folder
uv run scripts/email-search.py --folder Sent --limit 10

# Multiple filters (AND logic)
uv run scripts/email-search.py --from "@newsletter.com" --subject "unsubscribe" --limit 5

# Search with no limit
uv run scripts/email-search.py --limit 200 --no-limit
```

## email-delete.py

Delete emails by message ID with safety preview.

**Usage:**

```bash
uv run scripts/email-delete.py [message-id] [options]
```

**Options:**

- `--folder FOLDER` - Folder to delete from (default: INBOX)
- `--execute` - Actually perform deletion (default: dry-run mode)
- `-v, --verbose` - Show himalaya commands being executed
- `--help` - Show help message

**Arguments:**

- `message-id` - Message ID to delete (obtained from search results)

**Safety features:**

- Always shows preview before deletion (dry-run mode by default)
- Requires --execute flag to actually delete
- Shows date, sender, and subject of message to be deleted
- Returns error if message ID not found

**Examples:**

```bash
# Preview deletion (dry-run)
uv run scripts/email-delete.py 56838

# Actually delete
uv run scripts/email-delete.py 56838 --execute

# Delete from specific folder
uv run scripts/email-delete.py --folder Sent 12345 --execute
```

**WARNING:** Always run in dry-run mode first to verify the correct message!

## email-save.py

Save email content to file in various formats.

**Usage:**

```bash
uv run scripts/email-save.py <message-id> [options]
```

**Options:**

- `--folder FOLDER` - Folder to search (default: INBOX)
- `--output PATH` - Output directory or file path (default: current directory)
- `--format FORMAT` - Output format: markdown, text, or json (default: markdown)
- `--date-prefix` - Add YYYY-MM-DD date prefix to filename (uses email date)
- `--download-attachments` - Download email attachments
- `--attachment-dir PATH` - Directory for attachments (default: himalaya downloads directory)
- `--overwrite` - Overwrite existing file without confirmation
- `-v, --verbose` - Show himalaya commands being executed
- `--help` - Show help message

**Arguments:**

- `message-id` - Message ID to save (obtained from search results)

**Output formats:**

- **markdown**: Rich format with headers and metadata
- **text**: Plain text with basic headers
- **json**: Raw JSON output from himalaya (envelope + body data)

**Examples:**

```bash
# Save as markdown to current directory
uv run scripts/email-save.py 56873

# Save to specific directory
uv run scripts/email-save.py 56873 --output ~/saved-emails

# Save with date prefix
uv run scripts/email-save.py 56873 --date-prefix

# Save as text format
uv run scripts/email-save.py 56873 --format text

# Save as JSON
uv run scripts/email-save.py 56873 --format json

# Save with attachments
uv run scripts/email-save.py 56873 --download-attachments

# Save with attachments to custom directory
uv run scripts/email-save.py 56873 --download-attachments --attachment-dir ~/attachments
```

## email-read.py

Read and display email content in various formats.

**Usage:**

```bash
uv run scripts/email-read.py <message-id> [options]
```

**Options:**

- `--folder FOLDER` - Folder to search (default: INBOX)
- `--format FORMAT` - Output format: markdown, text, raw, headers, body (default: markdown)
- `-v, --verbose` - Show himalaya commands being executed
- `--help` - Show help message

**Arguments:**

- `message-id` - Message ID to read (obtained from search results)

**Output formats:**

- **markdown**: Rich format with headers, attachments list, and formatted body
- **text**: Plain text format
- **raw**: Raw himalaya output (including <#part> tags)
- **headers**: Email headers only
- **body**: Email body content only

**Examples:**

```bash
# Read as markdown
uv run scripts/email-read.py 56873

# Read raw format
uv run scripts/email-read.py 56873 --format raw

# Read headers only
uv run scripts/email-read.py 56873 --format headers

# Read body only
uv run scripts/email-read.py 56873 --format body
```
