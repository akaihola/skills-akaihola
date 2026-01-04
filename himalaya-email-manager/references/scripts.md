# Script Reference

Detailed documentation for Himalaya Email Manager scripts.

## email-summary.sh

Shows emails from the past 24 hours in INBOX and Sent folders.

**Usage:**
```bash
scripts/email-summary.sh
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

## email-search.sh

Search emails by various criteria with case-insensitive matching.

**Usage:**
```bash
scripts/email-search.sh [options]
```

**Options:**
- `--folder FOLDER` - Folder to search (default: INBOX)
- `--from SENDER` - Filter by sender email/name (case-insensitive)
- `--subject TEXT` - Filter by subject text (case-insensitive)
- `--date-start DATE` - Start date (YYYY-MM-DD)
- `--date-end DATE` - End date (YYYY-MM-DD)
- `--limit N` - Maximum results (default: 20)
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
scripts/email-search.sh --from "spotify.com"

# Search by subject
scripts/email-search.sh --subject "invoice"

# Search by date range
scripts/email-search.sh --date-start "2025-12-17" --date-end "2025-12-31"

# Search in Sent folder
scripts/email-search.sh --folder Sent --limit 10

# Multiple filters (AND logic)
scripts/email-search.sh --from "@newsletter.com" --subject "unsubscribe" --limit 5
```

## email-delete.sh

Delete emails by message ID with safety preview.

**Usage:**
```bash
scripts/email-delete.sh [message-id] [options]
```

**Options:**
- `--folder FOLDER` - Folder to delete from (default: INBOX)
- `--execute` - Actually perform deletion (default: dry-run mode)
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
scripts/email-delete.sh 56838

# Actually delete
scripts/email-delete.sh 56838 --execute

# Delete from specific folder
scripts/email-delete.sh --folder Sent 12345 --execute
```

**WARNING:** Always run in dry-run mode first to verify the correct message!
