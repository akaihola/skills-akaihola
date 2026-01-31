---
name: email-mailbox-analyzer
description: "Analyzes email mailbox usage by extracting IMAP configurations and running imapdu to generate detailed usage reports. Use this skill when you need to analyze email storage, identify large mailboxes, and generate CSV reports."
---

# Email Mailbox Analyzer

This skill provides a tool for analyzing email mailbox usage and generating detailed reports.

## Tool

### email-mailbox-analyzer

Analyzes email mailbox usage by extracting IMAP server configurations from Thunderbird and running the `imapdu` tool to generate detailed usage reports.

## When to Use This Skill

Use this skill when you need to:

- Analyze email storage usage across multiple accounts
- Identify large mailboxes that consume significant storage
- Generate CSV reports with mailbox statistics

## Features

- Automatically extracts IMAP server settings from Thunderbird's `prefs.js`
- Runs `imapdu` analysis for each configured email account
- Generates CSV reports with mailbox statistics
- Sorts results by mailbox size for easy identification
- Creates timestamped output directories for organized results

## Requirements

- `uvx` (for running imapdu)
- Thunderbird with IMAP accounts configured
- Bash shell

## Usage

### Basic Usage

To analyze all configured IMAP accounts:

```bash
./email-mailbox-analyzer
```

### Manual Usage

To run a specific analysis command:

```bash
uvx git+https://github.com/cpackham/imapdu --user antti16@kaihola.fi --csv --no-human-readable mail.gandi.net | sort -t, -k3 -n
```

## Output Format

The tool generates CSV files with the following columns:

- `count`: Number of messages in the folder
- `path/to/folder`: Folder path
- `total-bytes`: Total size of all messages in bytes
- `largest-message-bytes`: Size of the largest message in bytes

## Example Output

```
count,path/to/folder,total-bytes,largest-message-bytes
123,INBOX,4567890,123456
45,Sent,2345678,98765
```

## Implementation Details

### Scripts

The skill includes a main script that:

1. Extracts IMAP server configurations from Thunderbird's `prefs.js`
2. Identifies all IMAP accounts (skipping local folders and smart mailboxes)
3. Runs `imapdu` analysis for each account
4. Processes and sorts CSV output by mailbox size
5. Creates timestamped output directories for results

### Configuration

The script automatically detects Thunderbird's configuration at:

```
~/.thunderbird/av60ft8s.default-release/prefs.js
```

### Error Handling

The script includes error handling for:

- Missing Thunderbird configuration files
- Failed IMAP connections
- Authentication issues
- Missing dependencies

## Troubleshooting

- **Permission errors**: Ensure read access to `~/.thunderbird/av60ft8s.default-release/prefs.js`
- **Connection issues**: Check internet connection and IMAP server availability
- **Authentication problems**: Ensure Thunderbird passwords are up to date
- **Missing dependencies**: Install `uvx` before running the script

## Notes

- Results are sorted by total bytes (column 3) in ascending order
- Each run creates a new timestamped directory in the home folder
- The script automatically skips non-IMAP servers like "Local Folders" and "smart mailboxes"
