# Himalaya troubleshooting

## Check installation before contacting a mailbox

All five wrappers support `--help` without invoking Himalaya. They require
Python 3.13+ and the dependencies declared in each script.

```bash
himalaya --help
himalaya attachment download --help
uv run himalaya-email-manager/scripts/email_save.py --help
```

Attachment saving needs the `-d` destination option. Inspect the installed
command’s help rather than assuming compatibility from a version label.
Commands here run from the repository root; use an absolute script path elsewhere.
Running via `uv run` does not require executable permission on the Python file.

## Configuration and authentication

The wrappers pass a fixed `ACCOUNT` constant to Himalaya. They do not select
Himalaya’s default account or expose an `--account` flag. Inspect the constant
in the relevant [script] privately and confirm that it names the intended
configured account.

Authentication belongs to Himalaya’s configuration. Do not assume that every
installation uses a keyring or a particular IMAP host. Check the configured
credential mechanism without printing its value or dumping the entire
configuration. Report credential problems by file and line only.

After authorization for mailbox access, `himalaya account list` can help
identify configured accounts and `himalaya folder list --account ACCOUNT`
can check the selected account’s folders.

## Missing search results or messages

Search filters run locally over one fetched page (500 envelopes normally,
10,000 with `--no-limit`). A missing result does not prove that the message is
absent from the mailbox. Summary also uses one default page per folder and
matches today/yesterday date prefixes.

Check the folder, the numeric message ID, sender/subject spelling, and ISO
date bounds. Dates are compared as text; supply `YYYY-MM-DD`.
The script does not implement body search, `--since`, or `--until`.

## Saving and reading

Use `text`, `markdown`, `json` or `raw` for reading; `headers` and `body`
are not accepted formats. Saving supports `markdown`, `text` and `json`.
See the [script reference] for attachment destinations and filename rules.

Saving creates local files and may prompt before overwriting an email.
Deletion with `--execute` proceeds without a confirmation prompt in a
noninteractive terminal; authorization must already be established.

[script]: ../scripts/
[script reference]: scripts.md
