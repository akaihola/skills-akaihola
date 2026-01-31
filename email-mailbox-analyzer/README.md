# Email Mailbox Analyzer Skill

## Description
This skill analyzes email mailbox usage by extracting IMAP server configurations from Thunderbird and running the `imapdu` tool to generate detailed usage reports.

## Features
- Automatically extracts IMAP server settings from Thunderbird's `prefs.js`
- Runs `imapdu` analysis for each configured email account
- Generates CSV reports with mailbox statistics
- Sorts results by mailbox size
- Creates timestamped output directories for easy organization

## Requirements
- `uvx` (for running imapdu)
- Thunderbird with IMAP accounts configured
- Bash shell

## Usage

### Basic Usage
```bash
./email-mailbox-analyzer
```

### Manual Usage (as requested)
If you want to run the specific command mentioned:
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

## Notes
- The script automatically detects all IMAP accounts configured in Thunderbird
- Results are sorted by total bytes (column 3) in ascending order
- Each run creates a new timestamped directory in your home folder
- The script skips non-IMAP servers like "Local Folders" and "smart mailboxes"

## Troubleshooting
- If you get permission errors, ensure you have read access to `~/.thunderbird/av60ft8s.default-release/prefs.js`
- If `imapdu` fails, check your internet connection and IMAP server availability
- For authentication issues, ensure your Thunderbird passwords are up to date