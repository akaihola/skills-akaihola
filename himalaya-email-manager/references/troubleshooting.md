# Troubleshooting

Common issues and solutions for Himalaya Email Manager.

## Connection Errors

If you see connection errors when running scripts:

```bash
# Test connection
nix-shell -p himalaya --run "himalaya account list"

# List folders
nix-shell -p himalaya --run "himalaya folder list"

# View account details
cat ~/.config/himalaya/config.toml
```

## Password Issues

Himalaya uses the system keyring for authentication. If you're prompted for password or see authentication errors:

1. Ensure your system keyring is unlocked
2. Check that the credentials are stored correctly in the keyring
3. You may need to re-enter your password through Himalaya

## No Results Found

If searches return no results:

- Verify the folder name is correct (INBOX, Sent, Drafts, Archive, Trash, Junk)
- Check date format (must be YYYY-MM-DD)
- Try a broader search with fewer filters
- Ensure the email exists in the specified folder

## Message ID Not Found

If email-delete.sh reports "Message ID not found":

- Verify the message ID is correct (copy from search results)
- Check you're searching in the correct folder with --folder
- The email may have been moved or deleted already

## Date Format Errors

If date filters don't work:

- Dates must be in YYYY-MM-DD format (ISO 8601)
- Example: "2025-12-31" (not "12/31/2025" or "31-12-2025")
- Ensure --date-start is earlier than --date-end

## Permission Errors

If you see permission denied errors:

```bash
# Make scripts executable
chmod +x scripts/*.sh
```

## IMAP Server Issues

If IMAP server is slow or unresponsive:

- Check your internet connection
- Verify mail.gandi.net is accessible
- Try the connection test commands above
- The issue may be temporary server-side

## Script Execution Issues

If scripts don't run:

1. Verify Nix is installed and working
2. Test: `nix-shell -p himalaya --run "himalaya --help"`
3. Check that all scripts have the shebang line `#!/usr/bin/env bash`
4. Ensure jq is available (Nix package)

## Technical Context

This skill uses:
- **Himalaya v1.1.0** - Rust-based IMAP CLI tool
- **jq** - JSON parsing and formatting
- **Nix** - Package management
- **IMAP protocol** - Direct server communication (mail.gandi.net)

All operations are performed directly on the IMAP server, ensuring:
- Real-time access to emails
- Immediate synchronization with other clients (Thunderbird, webmail)
- No risk of local file corruption
- Fast server-side search
