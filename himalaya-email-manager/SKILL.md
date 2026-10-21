---
name: himalaya-email-manager
description: Manage email through the configured Himalaya CLI account. Search headers, show summaries, read or save messages and attachments, or preview and execute requested deletions.
---

# Himalaya Email Manager

Resolve the [scripts/ directory](scripts/) from this skill’s installed location.
Use `uv run` with the absolute script path from any working directory. Python
3.13+ and each script’s dependencies are declared in PEP 723 metadata.

The wrappers use a fixed `ACCOUNT` constant, not Himalaya’s default account,
and expose no account-selection flag. Confirm that this configuration fits the
requested mailbox before a live operation. Do not print credentials.

## Choose an operation

| Script | Behaviour |
| --- | --- |
| [scripts/email-summary.py](scripts/email-summary.py) | Show fetched INBOX/Sent envelopes whose dates start with today or yesterday; not a rolling 24-hour window |
| [scripts/email-search.py](scripts/email-search.py) | Filter one fetched page of headers locally by sender, subject and inclusive date range |
| [scripts/email-read.py](scripts/email-read.py) | Display `text` (default), `markdown`, `json` or `raw` |
| [scripts/email_save.py](scripts/email_save.py) | Save `markdown` (default), `text` or `json`; download attachments by default |
| [scripts/email-delete.py](scripts/email-delete.py) | Fetch a preview; delete only with `--execute` |

Read the [script reference](references/scripts.md) for options and examples,
and [troubleshooting](references/troubleshooting.md) for setup failures.

```bash
uv run /path/to/himalaya-email-manager/scripts/email-search.py --from sender@example.org --limit 5
uv run /path/to/himalaya-email-manager/scripts/email-read.py 57039 --format markdown
uv run /path/to/himalaya-email-manager/scripts/email_save.py 57039 --no-download-attachments
uv run /path/to/himalaya-email-manager/scripts/email-delete.py 57039
```

## Limits and side effects

Search defaults to 20 results, capped at 100. `--no-limit` ignores `--limit`
and fetches up to 10,000 envelopes in one page; it does not paginate the
entire mailbox. Filters combine with AND. Body search is not implemented;
use `--date-start` and `--date-end`, not `--since` or `--until`.

Saving puts attachments in a message-ID subdirectory beside the saved email.
Downloads use a private staging directory, sanitized names and collision
suffixes. The script does not perform vision analysis, replace images with
text, or delete attachments after saving. Any such editing is separate work
within the user’s requested scope.

Preview deletions first. Obtain authorization before `--execute`; the script
prompts only in interactive terminals and proceeds without a prompt in
noninteractive use. A deletion preview still reads the live mailbox.
For an offline check, use `--help`, which all five scripts handle before
invoking Himalaya.
