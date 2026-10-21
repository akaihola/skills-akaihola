# Himalaya script reference

Commands below run from the repository root; substitute the absolute script
path when the skill is installed elsewhere. All scripts require Python 3.13+;
`uv run` resolves their inline dependencies. They invoke Himalaya with a
fixed `ACCOUNT` constant and have no account override or credential environment
variable of their own.

## Summary

[himalaya-email-manager/scripts/email-summary.py] fetches one default page
from each of INBOX and Sent. It selects date strings starting with today or
yesterday and prints Rich tables with dates, senders, subjects and IDs.
It does not calculate an exact 24-hour cutoff or fetch subsequent pages.

```bash
uv run himalaya-email-manager/scripts/email-summary.py --help
uv run himalaya-email-manager/scripts/email-summary.py
uv run himalaya-email-manager/scripts/email-summary.py --verbose
```

The only operation option is `--verbose / --no-verbose` (default off);
there is no short `-v` for this script.

## Search

[himalaya-email-manager/scripts/email-search.py] applies filters locally
after fetching envelopes, preserving server order.

| Option | Default and behaviour |
| --- | --- |
| `--folder` | `INBOX` |
| `--from` | Case-insensitive substring in sender name or address |
| `--subject` | Case-insensitive subject substring |
| `--date-start`, `--date-end` | Inclusive comparisons against the first ten date characters; supply ISO `YYYY-MM-DD` |
| `--limit` | 20, capped at 100; one page of up to 500 envelopes is searched |
| `--no-limit` | Ignore the numeric limit; search one page of up to 10,000 envelopes |
| `-v`, `--verbose` | Show Himalaya commands |

```bash
uv run himalaya-email-manager/scripts/email-search.py --from sender@example.org --limit 5
uv run himalaya-email-manager/scripts/email-search.py --date-start 2030-01-01 --date-end 2030-01-31
uv run himalaya-email-manager/scripts/email-search.py --folder Sent --no-limit
```

Filters combine with AND. No body search or pagination loop is implemented.

## Read

[himalaya-email-manager/scripts/email-read.py] requires a numeric message ID.

| Option | Default and behaviour |
| --- | --- |
| `--folder`, `-f` | `INBOX` |
| `--format` | `text`; also `markdown`, `json`, `raw` |
| `--preserve-html` | Accepted flag, default off; see the limitation below |
| `-v`, `--verbose` | Show parsing details |

```bash
uv run himalaya-email-manager/scripts/email-read.py 57039 --format markdown
uv run himalaya-email-manager/scripts/email-read.py 57039 --folder Sent --format raw
```

Text and Markdown are displayed in Rich panels. JSON contains `folder`,
`envelope`, `mime_parts` and the `preserve_html` flag. Raw displays the body
returned by Himalaya. Status messages also go to stdout, so JSON mode is not
a clean machine-readable stream. `headers` and `body` are not format choices.

The implementation always converts HTML for text/Markdown. JSON already
includes the parsed MIME parts, and raw output already preserves the raw body;
`--preserve-html` changes the JSON flag but not the selected body content.

## Save

[himalaya-email-manager/scripts/email_save.py] requires a numeric message ID.

| Option | Default and behaviour |
| --- | --- |
| `--folder`, `-f` | `INBOX` |
| `--output`, `-o` | Current directory; accepts a directory or filename |
| `--format` | `markdown`; also `text`, `json` |
| `--date-prefix` | Off; prefix the sanitized subject with the message date in the local timezone |
| `--download-attachments / --no-download-attachments` | Enabled |
| `--attachment-dir` | A `<message-id>-attachments/` directory beside the saved email |
| `--overwrite / --no-overwrite` | Off; existing email files prompt unless overwrite is enabled |
| `-v`, `--verbose` | Show Himalaya commands |

```bash
uv run himalaya-email-manager/scripts/email_save.py 57039 --output ./saved-emails --date-prefix
uv run himalaya-email-manager/scripts/email_save.py 57039 --format json --no-download-attachments
uv run himalaya-email-manager/scripts/email_save.py 57039 --attachment-dir ./attachments
```

The default filename is `<message-id>.<ext>`. With a parseable date and
`--date-prefix`, it becomes `YYYY-MM-DD-<sanitized-subject>.<ext>`;
unparseable dates fall back to the message ID. Spaces and emojis remain,
slashes become dashes, null bytes are removed, and the subject is truncated
to 200 characters.

An existing directory, or a nonexistent output path without a suffix, is
treated as a directory. Other output paths are treated as filenames.
JSON files contain `folder`, `envelope` and `body`.

Attachment downloads require Himalaya’s `attachment download -d PATH`
support. The helper stages downloads privately, copies regular files with
sanitized names, and adds collision suffixes without overwriting existing
attachments. It does not analyze images or remove downloaded attachments.

## Delete

[himalaya-email-manager/scripts/email-delete.py] requires a numeric message ID.
Options are `--folder` (default `INBOX`), `--execute` (default off), and
`-v / --verbose`.

```bash
# Preview first; this still reads the live mailbox.
uv run himalaya-email-manager/scripts/email-delete.py 57039
# Run only after the user has authorized deletion.
uv run himalaya-email-manager/scripts/email-delete.py 57039 --execute
```

The helper fetches the message, prints a preview, and calls
`himalaya envelope delete` only with `--execute`. The confirmation prompt
exists only when stdin is interactive.

## Offline checks

Every script supports `--help` before contacting Himalaya. Save tests mock
mailbox calls; the shared security tests also cover attachment handling:

```bash
uv run --no-project --with pytest --with typer --with rich pytest himalaya-email-manager/tests tests/test_security_boundaries.py -q
```

[himalaya-email-manager/scripts/email-summary.py]: ../scripts/email-summary.py
[himalaya-email-manager/scripts/email-search.py]: ../scripts/email-search.py
[himalaya-email-manager/scripts/email-read.py]: ../scripts/email-read.py
[himalaya-email-manager/scripts/email_save.py]: ../scripts/email_save.py
[himalaya-email-manager/scripts/email-delete.py]: ../scripts/email-delete.py
