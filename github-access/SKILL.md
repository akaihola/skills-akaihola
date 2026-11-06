---
name: github-access
description: Diagnose GitHub repository read/write permission failures in the GitHub connector or gh CLI.
---

# GitHub repository access

On 2026-11-06, the GitHub connector could read three public repositories but
its README updates returned HTTP 403 `Resource not accessible by integration`.
The authenticated `gh` personal access token could read the same repositories,
but a README update returned HTTP 403 `Resource not accessible by personal
access token`. A successful read or reported repository push permission did not
establish that either credential could write those files.

Check the specific credential's repository selection and permissions with its
owner when a write is rejected. Never ask for a token in chat. After access is
changed, retry only the authorized operation and verify the result. Topic and
About-description writes were not tested in that session.
