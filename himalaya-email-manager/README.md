# Himalaya Email Manager

Five Python wrappers for email management through the Himalaya CLI. Read the
[skill instructions] for account checks and agent workflow, and the
[script reference] for all options, examples and limitations.

## Setup

Install and configure Himalaya, plus `uv`. The wrappers declare Python 3.13+
and their dependencies in PEP 723 metadata; invoke them with `uv run`.
All five use a fixed `ACCOUNT` constant and expose no account-selection flag.
Confirm that the configured account is the intended mailbox before use.
See [troubleshooting] for setup and connection problems.

## Choose a wrapper

| Wrapper | Behaviour |
| --- | --- |
| [Summary wrapper] | Fetch one default page from each of INBOX and Sent; show envelopes whose date strings start with today or yesterday, rather than a rolling 24-hour window. |
| [Search wrapper] | Filter one page of headers locally by `--from`, `--subject`, `--date-start` and `--date-end`, in `--folder` (default INBOX). Filters combine with AND. |
| [Read wrapper] | Display a message ID using `--format text` (default), `markdown`, `json` or `raw`. |
| [Save wrapper] | Save a message ID using `--format markdown` (default), `text` or `json`. `--output` defaults to the current directory; attachments download by default into `<message-id>-attachments/` beside the saved email. |
| [Delete wrapper] | Read a live preview by message ID; delete only with `--execute`. Confirmation is prompted only in interactive terminals. |

Search defaults to `--limit 20`, capped at 100, over up to 500 fetched headers.
`--no-limit` searches up to 10,000 headers in one page; neither mode paginates
the whole mailbox. Body search is not implemented.

Save accepts `--attachment-dir` for a custom attachment directory and
`--no-download-attachments` to skip downloads. Existing email files prompt
before replacement unless `--overwrite` is enabled.

## Quick start

Run from the repository root, or substitute an absolute script path:

```bash
uv run himalaya-email-manager/scripts/email-summary.py
uv run himalaya-email-manager/scripts/email-search.py --from sender@example.org --limit 5
uv run himalaya-email-manager/scripts/email-read.py 57039 --format markdown
uv run himalaya-email-manager/scripts/email_save.py 57039 --no-download-attachments
uv run himalaya-email-manager/scripts/email-delete.py 57039
```

The deletion example previews only. Obtain authorization before using
`--execute`. For an offline check, all five wrappers support `--help` before
contacting Himalaya.

[skill instructions]: SKILL.md
[script reference]: references/scripts.md
[troubleshooting]: references/troubleshooting.md
[Summary wrapper]: scripts/email-summary.py
[Search wrapper]: scripts/email-search.py
[Read wrapper]: scripts/email-read.py
[Save wrapper]: scripts/email_save.py
[Delete wrapper]: scripts/email-delete.py
