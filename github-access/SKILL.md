---
name: github-access
description: Diagnose GitHub repository read/write permission failures in the GitHub connector or gh CLI.
---

# GitHub repository access

On 2026-11-06, the GitHub connector could read three public repositories but
its README updates returned HTTP 403 `Resource not accessible by integration`.
The authenticated `gh` personal access token could read the same repositories,
but a README update returned HTTP 403 `Resource not accessible by personal
access token`. Its About-description updates for the three repositories also
returned HTTP 403. A successful read or reported repository push permission did
not establish that either credential could write those files or metadata.

Check the specific credential's repository selection and permissions with its
owner when a write is rejected. Never ask for a token in chat. After access is
changed, retry only the authorized operation and verify the result. Topic writes
were not tested in that session.

Verified 2026-11-10: a private repository migration rejected by GitHub's
email-privacy push restriction succeeded after replacing the owner's author
and committer email metadata with the account's numeric-ID GitHub noreply
address. Preserve the original history in a local bundle before rewriting an
unpublished copy with `git filter-repo --mailmap`. Compare every rewritten
commit's tree with its original, check both email headers, and push ordinary
branches only. The verified migration kept all 31 commit trees identical and
needed no change to the account's email-privacy setting. Rewriting metadata
changes commit IDs; this observation does not authorize rewriting published
history.

Verified 2026-11-11: separate SSH aliases and deploy keys for each service
account let an older Git/SSH installation read its private GitHub code
repositories while granting write permission only to its backup repository.
The migration tested reads and a real fast-forward backup push before changing
origins, and recorded unchanged application commit IDs. A later automatic
backup commit reached GitHub after the manual migration push; that later
commit verified scheduled operation as well as the one-time transfer.
