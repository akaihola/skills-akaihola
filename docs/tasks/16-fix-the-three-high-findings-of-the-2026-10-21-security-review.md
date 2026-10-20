Steward issue, 2026-10-21 01:30. Goal: agentic-leverage (skills-akaihola is a tier 2 project in `<steward-vault>/Goals.md`; agents load these skills every day). Estimated 1.5 h.

[The security review](../reviews/2026-10-21-security-review.md) ([15]) recommends fixing its three high findings first. Each can be reached in its skill's normal use, and each fix stays within one script:

- **S1:** `read-as-markdown` runs a PDF's file name as shell code. Fix **S5** in the same skill too: it trusts a planted cache index.
- **S2:** the himalaya save script lets an email's attachment names replace files in the project.
- **S3:** `secrets-scan` prints every secret it finds into the agent's transcript. Print each finding's location and kind only.

Each finding's section in the review gives the evidence and a drafted fix. Follow it unless the code shows a simpler one.

Not in scope: the medium findings S4 and S6–S14, and P1 (personal data in the public history), which needs Antti's decision on rewriting public history.

## Constraints and acceptance

- Never print a real secret, open a real mailbox or process real documents. Tests use made-up files and names, hostile ones included: a file name with `$(…)`, `;` or a leading `-`, and an attachment name with `../`.
- Each fixed script has a test that fails before the fix and passes after it.
- Memory: before each command, wait up to 10 minutes for `MemAvailable` of at least 2 GiB; if it doesn't come, start the command anyway when at least 1.5 GiB is available. Stop a running command when `MemAvailable` falls below 1 GiB or swap grows by more than 512 MiB. Run one heavy command at a time.
- No pushes; updating the GitHub copy is Antti's.
- Under each finding this issue fixes, the review gains one line: "Fixed by [N]", with this issue's number.
