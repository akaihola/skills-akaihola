# Security review, 2026-10-21

Reviewed `main` at `b581e8601543f24f0dcac7116140f555598ab9b1`. Evidence
locations refer to that commit. This report is the only deliverable: nothing
was fixed and the drafted issues have not been filed.

## Summary

- **Credentials:** no live credential is committed in the tree or in the
  history of any ref. The few credential-shaped strings are placeholders,
  test fixtures or a webshop's public search key (see [History scan]).
- **Findings:** 11 findings passed the review threshold (verified, confidence
  8 or more): 3 High and 8 Medium. Another 3 findings below the threshold are
  still worth fixing. 14 issues are drafted below.
- **Privacy:** the public tree and its history contain what looks like a real
  third party's directory record, and several items of the owner's personal
  data ([P1]). It is not a credential, but it is the most sensitive content in
  the repository. Values are withheld here.

The three High findings share one pattern: a script or instruction gives
text from outside, a file name or a secret, a power it should not have.
`read-as-markdown` runs a PDF's file name as shell code ([S1]); the himalaya
save script lets an email's attachment names replace files in the agent's
project ([S2]); and `secrets-scan` prints every real secret it finds into the
agent's transcript ([S3]).

**Recommendation:** file and fix [S1], [S2] and [S3] first, then [P1]. Each
of the first three is reachable in the default flow of its skill, and each fix
is local to one script. [P1] needs the user's decision on rewriting public
history.

## Method

The `security-review` skill reviews the diff of a branch. This issue asks for
the whole tree, so its three-step method was applied to the tree instead:

1. **Identification:** six parallel review passes read every file in their
   area in full, in the order the issue sets. The passes covered the
   credential-handling skills named in the issue, then the repository-changing
   skills, then every other skill with code, then `scripts/`, `tests/`,
   `.github/` and `.claude/`. `android-diagnostics` had a pass of its own
   because of its size.
2. **Verification:** about 40 candidates rated Medium or higher went to eight
   parallel verification passes, batched by file. Each pass tried to disprove
   its candidates with the skill's false-positive rules and gave each a
   confidence from 1 to 10.
3. **Threshold:** findings verified at confidence 8 or more are listed as
   findings. Lower-confidence ones that are still worth fixing get a draft
   below them; the rest are listed as hardening notes or rejected candidates.

The skill's false-positive rules exclude documentation and secrets stored on
disk. The issue asks for both, because agents carry out `SKILL.md` files as
instructions and because secret files written without owner-only permissions
are on its checklist. Those two exclusions therefore did not apply to
instructions in `SKILL.md`, command and reference files, or to file
permissions. Severity combines impact and likelihood:

- **High:** code execution, a credential leak or a silent overwrite reachable
  in the default flow.
- **Medium:** the same kind of impact behind a crafted input or a specific
  workflow, or data loss in a normal workflow.
- **Low:** needs unusual conditions.

All experiments ran offline in a private temporary directory with synthetic
data and stubbed binaries. They included throwaway Git repositories, crafted
directory and file names, synthetic bugreport zips, fake secrets and a stub
`nix-shell`. Nothing contacted a service, device or mailbox. No credential or
secrets file was read and no service was restarted.

A tree-wide search found no `shell=True`, `os.system`, `os.popen`, `eval`,
`exec`, `yaml.load`, `pickle`, `verify=False`, `extractall` or `curl | sh` in
tracked code.

## Coverage

| Area | Directories | Outcome |
| --- | --- | --- |
| Credential skills named in the issue | `t3-start-thread`, `jmap`, `himalaya-email-manager`, `email-mailbox-analyzer`, `asana`, `brave-search`, `gemini-vision`, `nano-banana-image`, `context7-skill` | [S2], [P1]; `t3-start-thread` hardening only; `asana` is design-only with no code. Brave, Gemini and image keys stay in headers or the SDK and are never printed. |
| Repository-changing skills named in the issue | `fleet-audit`, `sync-plugin-cache`, `library`, `rebase-all` | [S6], [S10]; `library` and `sync-plugin-cache` hardening only. |
| Other skills with `scripts/` | `android-diagnostics`, `bauhaus`, `browser-youtube-history`, `clasohlson`, `claude-session-logs`, `commit-organizer`, `conventional-committer`, `discard-whitespace-hunks`, `fonecta-lookup`, `hsl`, `k-rauta`, `kuluttaja`, `mcp-to-skill`, `motonet`, `netrauta`, `pdf-to-markdown`, `pi-session-logs`, `power`, `puuilo`, `read-as-markdown`, `reflect-extensions`, `secrets-scan`, `taloon`, `tokmanni`, `upstream-pr`, `verkkokauppa`, `youtube-frame-analysis`, `youtube-to-markdown`, `youtube-transcription`, `zed-threads` | [S1], [S3], [S4], [S5], [S7], [S9], [S11], [S12], [S13], [S14], [P1]. The ten webshop skills use fixed HTTPS hosts with TLS verification on, write no files and start no processes. |
| Skills with code outside `scripts/`, or none | `ecb-rates`, `processing-scanned-receipts`, `commit`, `learn`, `skill-tiers`, `simplify-skill`, `pandoc-typst-pdf` | [S8]; `ecb-rates` parses XML with `defusedxml`; the rest hardening only or clean. |
| `scripts/`, `tests/` | metadata checker and its test | Clean: `yaml.safe_load`, argument-list `git` calls, no writes. |
| `.github/` | three workflows and the symlink checker | Hardening only: no `pull_request_target`, no secrets, no event text in `run:` steps. |
| `.claude/`, `README.md`, `AGENTS.md` | settings are untracked; symlinks stay in the repository | One Low note on the `/lint` command. |
| Git history | 327 commits on every ref | No live credential ([History scan]). |

## Findings at the review threshold

### S1. read-as-markdown runs PDF file names as shell code

High. Verified, confidence 9.

- **Evidence:**
  - [`read-as-markdown/scripts/read_as_markdown.py:88-91`][ram] falls back
    to `nix-shell -p poppler-utils --run` when `pdftotext` is not on `PATH`.
  - [`read-as-markdown/scripts/read_as_markdown.py:125`][ram] builds that
    `--run` argument as `f"pdftotext -layout '{source}' -"`, a bash command
    string, and [`:142`][ram] makes `pdftotext` the default PDF backend.
- **Impact:** a PDF named `invoice'$(…)'.pdf` runs any command as the agent
  account. The payload needs no `/`, and directory names in the path inject
  too. A legitimate name containing `'` also breaks conversion.
- **Likelihood:** high where `pdftotext` is not on `PATH`, which is the case
  on the agent account. PDF names come from downloads, email attachments and
  unpacked archives, and reading received PDFs is the skill's main use.
- **Verification:** a stub `nix-shell` that runs its `--run` string with
  `bash -c`, given `invoice'$(touch MARKER)'.pdf`, created the marker.
- **Draft issue** (also covers [S5]):
  - **Title:** Run pdftotext without a shell and confine read-as-markdown's
    cache.
  - **Work:**
    - Build no shell string: call `pdftotext` through an argument list, for
      example a `nix shell … -c pdftotext -layout -- PATH -` form, or
      `shlex.quote` the path. Pass `--` before the path.
    - Store cache index entries relative to the cache folder and reject any
      entry that resolves outside it, including `/proc`.
    - Refuse a cache folder that is a symlink, and stop letting a `.claude/`
      found next to the document choose the cache location.
  - **Acceptance:**
    - Tests convert files whose names contain `'`, `$(…)` and backticks, and
      run nothing.
    - A planted `index.json` that points outside the cache is ignored.
    - A symlinked `.cache` is refused.

Fixed by [16].

### S2. Email attachments silently replace files in the project

High. Verified, confidence 8.

- **Evidence:**
  - [`himalaya-email-manager/scripts/email_save.py:695-703`][email_save]
    downloads attachments by default. [`:608`][email_save] saves to the
    current directory by default, and [`:627`][email_save] puts attachments
    next to the saved email.
  - [`himalaya-email-manager/scripts/email_save.py:536-541`][email_save]
    takes each attachment path from himalaya's log and keeps the sender's
    base name unsanitised. [`:549-550`][email_save] then calls
    `shutil.move` onto `attachment_dir / old_path.name` with no existence
    check.
  - The moves run at [`:745`][email_save], before the overwrite prompt at
    [`:755`][email_save], so declining that prompt does not undo them.
  - [`himalaya-email-manager/SKILL.md:10`][himalaya-skill] keeps the agent in
    its project directory instead of the skill directory.
- **Impact:** an attachment named `CLAUDE.md` or `AGENTS.md` becomes standing
  agent instructions. One named `conftest.py`, `Makefile` or
  `.pre-commit-config.yaml` runs code at the next test, build or commit. From
  the home directory, `.bashrc` works the same way.
- **Likelihood:** default path of every "save this email". The sender only
  chooses a file name.
- **Verification:** a simulated himalaya log listing `CLAUDE.md` and
  `conftest.py` replaced the project's copies without any message.
- **Related, below the threshold (confidence 4):**
  - Attachment names keep `$`, backticks and `;`, and
    [`himalaya-email-manager/SKILL.md:72-78`][himalaya-skill] then has the
    agent edit and delete those files.
  - [`jmap/sync_emails.py:88-89`][sync_emails] keeps the same characters, and
    [`:200-203`][sync_emails] stores names such as `CLAUDE.md` inside the
    per-email archive folder.
- **Draft issue:**
  - **Title:** Save email attachments into a fresh folder without
    overwriting.
  - **Work:**
    - Download into a new per-run temporary directory and move only its
      entries, instead of parsing paths from himalaya's log.
    - Store attachments in a new `<output>/<id>-attachments/` folder and
      never overwrite: create exclusively, or add a suffix on collision.
    - Restrict names to a safe character set and strip leading dots.
    - Apply the same name rule in `jmap/sync_emails.py`.
  - **Acceptance:**
    - Tests with attachments named `CLAUDE.md`, `.bashrc`, `$(x).pdf` and
      `../x` leave every existing file untouched.
    - Those attachments are stored under sanitised names in the attachment
      folder.

Fixed by [16].

### S3. secrets-scan prints every secret it finds

High. Verified, confidence 9.

- **Evidence:**
  - [`secrets-scan/scripts/scan.py:91-100`][scan] reads each flagged line,
    and [`:277`][scan] and [`:293`][scan] keep it as `line_content`.
  - [`secrets-scan/scripts/scan.py:401-404`][scan] prints up to 200
    characters of it in the Markdown report, under a comment that says the
    cut avoids echoing secrets; 200 characters holds any normal token.
  - [`secrets-scan/scripts/scan.py:480-481`][scan] prints the full line with
    `--json`.
  - [`secrets-scan/SKILL.md:119-120`][secrets-skill],
    [`:144`][secrets-skill] and
    [`secrets-scan/references/classifying-findings.md:16`][classifying] tell
    the agent to read the flagged line itself.
- **Impact:** every real finding, the case the tool exists for, puts the
  credential into model traffic, the session log and any write-up. The script
  also undoes secretlint's own masking, and `--all-files` adds untracked
  files such as `.env`.
- **Likelihood:** every true positive.
- **Verification:** a synthetic 40-character GitHub-style token in a scratch
  repository appeared twice in the Markdown report and in full in the JSON.
- **Related, from the identification pass only:**
  - [`secrets-scan/scripts/scan.py:112-119`][scan] does not pass
    `--no-verify`. According to the detect-secrets source in the local
    package cache, it then checks found credentials against vendor APIs.
  - Both scanners run unpinned, and the placeholder check (`:64-85`) matches
    the whole line, so a real key on a line with a `TODO:` is cleared.
  - [`secrets-scan/SKILL.md:173`][secrets-skill] uses the public Tokmanni
    search key as its "before" example, which scanners flag.
- **Draft issue:**
  - **Title:** Mask secret values in secrets-scan output.
  - **Work:**
    - Report file, line, detector type, variable name, length and a hash
      instead of `line_content`, in both Markdown and JSON.
    - Reword `SKILL.md` and `references/classifying-findings.md` so the agent
      inspects the surrounding context, not the value.
    - Pass `--no-verify` by default, pin both scanners, match placeholders
      against the value rather than the line, and replace the Tokmanni key
      example with a synthetic one.
  - **Acceptance:**
    - A test with a synthetic token finds no substring of it in either output
      format.
    - Classification results are unchanged.
    - No instruction in the skill tells the agent to read the value.

Fixed by [16].

### S4. android-diagnostics passes zip text to the shell

Medium. Verified, confidence 8.

- **Evidence:**
  - [`android-diagnostics/scripts/androiddiag/perf.py:240`][perf] captures
    package names with `^Package: (\S+)`, and
    [`:75-80`][perf], [`:599-603`][perf] and [`:667-670`][perf] build the
    follow-up `adb_ro.py … -- dumpsys gfxinfo {package} framestats` without
    quoting.
  - [`android-diagnostics/scripts/androiddiag/source.py:245`][source] carries
    raw zip member names into evidence origins. These come from the wildcard
    patterns at
    [`android-diagnostics/scripts/androiddiag/catalog.py:416`][catalog] and
    [`:467`][catalog], and become finding refs at
    [`android-diagnostics/scripts/androiddiag/logs.py:674`][logs],
    [`:691`][logs] and [`:920`][logs].
  - [`android-diagnostics/SKILL.md:188-189`][android-skill] tells the agent to
    run `show_ref.py WORKDIR 'REF'`, and [`:212-213`][android-skill] makes
    opening the evidence of every high-severity finding mandatory.
    [`android-diagnostics/references/domains.md:21`][domains] and
    [`:48`][domains] give subagents the same template.
  - A weaker path puts a process's first argument word into a `grep`
    follow-up:
    [`android-diagnostics/scripts/androiddiag/cpu.py:1026-1027`][cpu],
    [`:1190`][cpu] and [`:1218`][cpu]. That follow-up is copied into the
    bottom line by
    [`android-diagnostics/scripts/androiddiag/budget.py:1680-1682`][budget].
- **Impact:** arbitrary commands on the host as the agent account, possibly
  outside the sandbox. The host shell expands `;` and `$(…)` before
  `adb_ro.py` checks anything, and `${IFS}` gets past the `\S+` pattern.
- **Likelihood:** needs a crafted bugreport zip from someone else, which is a
  supported input ("a bugreport zip taken elsewhere"). A normal phone cannot
  produce such package or tombstone names. The process-name path is open to
  any app with a native child process.
- **Verification:** a synthetic zip with a crafted graphicsstats package and
  crafted tombstone member names produced two high findings. Their refs and
  follow-ups carried the payload into `analysis.json` and `report.md`, and
  pasting them into the `SKILL.md` template created marker files.
- **Related, below the threshold:**
  - Phone text reaches the agent with no instruction to treat it as data
    (confidence 3 as a separate finding).
  - `str.splitlines()` lets a log line forge a service block
    (confidence 6).
- **Draft issue:**
  - **Title:** Keep phone and zip text out of android-diagnostics shell
    commands.
  - **Work:**
    - Check package and process names against Android's package-name
      grammar, and `shlex.quote` every value put into a follow-up.
    - Make evidence refs index-based or sanitise member names, and let
      `show_ref.py` take a finding ID and evidence index.
    - State in `SKILL.md` and the subagent prompt that report and dump text
      is data, not instructions.
    - Split dump text on `\n` only.
  - **Acceptance:**
    - With a synthetic zip carrying crafted names, no follow-up or ref
      contains shell metacharacters.
    - `show_ref.py` works by finding ID.
    - The `SKILL.md` template no longer pastes raw refs.

### S5. read-as-markdown trusts a planted cache index

Medium. Verified, confidence 8.

- **Evidence:**
  - [`read-as-markdown/scripts/read_as_markdown.py:152-159`][ram] takes the
    nearest ancestor holding `.claude/` as the workspace root.
  - [`:213-221`][ram] loads `index.json` from there, and
    [`:276-281`][ram] accepts any absolute path it lists.
  - [`:384-399`][ram] copies that file into the cache, and
    [`:457-465`][ram] returns its text as the document's content.
  - Only a cache miss adds `.cache/` to `.gitignore` ([`:454`][ram]).
- **Impact:** a cloned repository or unpacked archive can make the agent read
  any local file into its context and logs. Pointing the index at
  `/proc/self/environ` returns the process environment, where several skills
  keep their API keys. The copy also lands, mode 0644, inside the attacker's
  folder, where a later commit could carry it.
- **Likelihood:** needs the user to read a PDF inside a crafted folder.
- **Verification:** a crafted folder returned a synthetic secret file with
  `cached: true`, and `/proc/self/environ` returned a synthetic API key from
  the environment.
- **Draft issue:** covered by [S1].

Fixed by [16].

### S6. rebase-all's undo rolls back other tasks' commits

Medium. Verified, confidence 9 for `restore` and 7 for `rewrite-refs`.

- **Evidence:**
  - [`rebase-all/scripts/rebase_all.py:455-458`][rebase_all] snapshots every
    branch.
  - `restore` ([`:463-488`][rebase_all]) resets every listed branch whose tip
    moved, including `main` and branches the run never touched. It uses
    `reset --hard` in that branch's worktree ([`:482`][rebase_all]) or
    `update-ref` with no expected old value ([`:484`][rebase_all]).
  - [`rebase-all/SKILL.md:29`][rebase-skill] keeps the snapshot at a fixed
    shared `/tmp` path, and [`:32-33`][rebase-skill] calls `restore` the undo
    button. [`:45`][rebase-skill] and [`:137`][rebase-skill] append the hash
    map across runs.
  - [`rebase-all/scripts/rebase_all.py:292-293`][rebase_all] rebases a
    branch in place in whichever worktree holds it.
  - `rewrite-refs` ([`:552-614`][rebase_all]) has no dirty check. It runs
    `git add` ([`:601`][rebase_all]) and then `git commit --no-verify`
    ([`:612`][rebase_all]), which commits that worktree's whole index.
- **Impact:** the documented undo silently drops other tasks' merges on
  `main` and live agents' commits, which only the reflog can then recover.
  `rewrite-refs` commits another agent's staged work and skips its
  pre-commit hooks, such as secret or privacy checks.
- **Likelihood:** the pacer keeps many live task worktrees per repository,
  and the skill itself expects branches to move during a run.
- **Verification:**
  - In throwaway repositories, `restore` after an unrelated merge to `main`
    and a commit on a live task branch reported "2 restored", and both
    commits left their branches.
  - `rewrite-refs` committed another worktree's staged file and edit under
    "docs: update commit hash references" and skipped a blocking hook.
- **Draft issue:**
  - **Title:** Limit rebase-all to the branches and changes it owns.
  - **Work:**
    - Restore only refs this run rewrote, with
      `update-ref <ref> <new> <expected-old>`, and refuse when the tip is not
      the run's own result.
    - Skip branches checked out in other worktrees unless
      `--include-worktree` is given.
    - Check for staged and unstaged changes immediately before
      `rewrite-refs`, commit only the rewritten paths, and drop
      `--no-verify`.
    - Keep the snapshot and map in a fresh `mktemp -d` per run.
  - **Acceptance:** tests on throwaway repositories show all of these:
    - A commit on `main` made after the snapshot survives `restore`.
    - Another worktree's branch is skipped by default.
    - An unrelated staged file there stays uncommitted, and hooks run.

### S7. reflect-extensions prints whole config files

Medium. Verified, confidence 8.

- **Evidence:**
  - [`reflect-extensions/commands/reflect-extensions.md:59`][reflect-cmd]
    runs `jq '.hooks // .' "$f" || cat "$f"` on the project and user
    `settings.json`. That prints the whole file when there is no `hooks` key
    or when `jq` fails.
  - [`:63`][reflect-cmd] runs `cat .mcp.json`, printing MCP `env` and
    `headers` verbatim.
  - The same line already reduces another config to its server names, which
    is the safe pattern.
- **Impact:** settings `env` values and MCP tokens enter the prompt, the
  provider and the transcript on every run. These are pre-run `!` commands,
  so the model never chooses to run them.
- **Likelihood:** the user must invoke the command
  (`disable-model-invocation: true`). Project settings often have no `hooks`
  key, and the plugin ships through the repository's marketplace.
- **Verification:** with fake settings files, an `env` value was printed
  whenever `hooks` was missing or null.
- **Related, from the identification pass only:**
  - [`reflect-extensions/scripts/capture_learning.py:69-77`][capture_learning]
    misses `Bearer` tokens and `…_API_KEY=` values when redacting captured
    prompts, and writes them with mode 0644 (synthetic tests).
  - Backups of edited configs are written as `.bak` files next to the
    originals, inside repositories.
- **Draft issue:**
  - **Title:** Print only names from config files in reflect-extensions.
  - **Work:**
    - List MCP server names and hook events, matchers and command names
      only, with no `cat` fallback.
    - Fix the capture redaction patterns and write capture files with mode
      0600.
    - Keep backups outside repositories.
  - **Acceptance:**
    - With synthetic configs holding secrets, the pre-run commands and
      captured prompts contain no secret value.
    - Hooks and servers are still listed.

### S8. Receipt reruns overwrite corrected results

Medium. Verified, confidence 8.

- **Evidence:**
  - [`processing-scanned-receipts/process_receipts.py:238`][receipts] keys
    the OCR cache by the current file name, so [`:313`][receipts] picks up
    already-renamed PDFs again.
  - `unique_name` ([`:222-228`][receipts]) only avoids clashes within one
    batch.
  - [`:363-369`][receipts] writes, copies and renames with no existence
    check.
  - [`processing-scanned-receipts/SKILL.md:33`][receipts-skill] presents
    reruns as normal, and [`:53-72`][receipts-skill] asks the user to correct
    `.txt` files by hand.
  - [`process_receipts.py:216`][receipts] uses the OCR's `date` unsanitised
    in file names.
- **Impact:** hand corrections and receipt PDFs (financial records) are lost
  without warning. A crafted receipt image can steer `date` to `../` and
  place files in a sibling directory.
- **Likelihood:** a normal, documented workflow.
- **Verification:** with stubbed `pdfimages` and `llm`:
  - A rerun discarded a hand edit.
  - A user-renamed undated receipt was replaced by a new scan with the same
    payee.
  - A `../outside/` date wrote outside the target folder.
- **Overlap:** the completed [dry-run task][task-11] fixed preview side
  effects, not reruns.
- **Draft issue:**
  - **Title:** Never overwrite receipts on rerun.
  - **Work:**
    - Skip PDFs that already carry the `YYYY-MM-DD …` name, or key the cache
      by content hash.
    - Refuse to overwrite any `.txt`, `.jpg` or `.pdf`; add a suffix
      instead.
    - Check `date` against `^\d{4}-\d{2}-\d{2}$`, check that every
      destination stays in the target folder, and strip `$`, backticks and
      control characters in `_sanitize`.
  - **Acceptance:**
    - A rerun leaves hand-edited files unchanged.
    - Colliding names produce distinct files.
    - A `../` date is rejected.

### S9. discard-whitespace-hunks discards meaningful changes

Medium. Verified, confidence 9.

- **Evidence:**
  - [`discard-whitespace-hunks/scripts/discard_ws_hunks.py:103`][dwh] makes
    the dry run opt-in.
  - [`:108-118`][dwh] reverts files with no `git diff -w` difference using
    `git checkout --`.
  - [`:90-93`][dwh] treats a hunk as whitespace-only when its text matches
    with all whitespace removed. [`:166`][dwh] reverse-applies such hunks,
    and [`:169`][dwh] deletes the patch, so no backup remains.
  - [`discard-whitespace-hunks/SKILL.md:24`][dwh-skill] counts changes of
    indentation level as whitespace.
- **Impact:** unstaged edits are not in Git's object store, so the loss is
  permanent. Affected changes include a Python statement moved out of a
  block, spaces inside string literals, Makefile tabs and YAML nesting.
- **Likelihood:** the user invokes the skill on their own tree. Such changes
  are common in Python and YAML repositories.
- **Verification:** a default run in a throwaway repository:
  - reverted a dedent that moved a call out of an `if`;
  - reverted `"hello world"` → `"helloworld"`;
  - in a mixed file, left the edit half applied.
- **Draft issue:**
  - **Title:** Make discard-whitespace-hunks preview by default and keep a
    backup.
  - **Work:**
    - Default to a dry run, with `--apply` to act.
    - Record `git stash create` before applying and print its hash.
    - Treat indentation and in-string whitespace as meaningful in Python,
      YAML and Makefiles.
    - Resolve paths from the repository root.
  - **Acceptance:**
    - A default run changes nothing.
    - `--apply` prints a recoverable hash.
    - A Python dedent hunk is kept.

### S10. fleet-audit builds a sed script from directory paths

Medium. Verified, confidence 8.

- **Evidence:**
  - [`fleet-audit/scripts/audit.py:49`][audit] runs `sed "s|^$1/||"`, where
    `$1` is a skills directory discovered under the home directory
    ([`:90-92`][audit], [`:107`][audit]).
  - The last directory name must match a public skill name
    ([`:55`][audit], [`:100`][audit]), so the injection sits in a parent
    directory's name.
  - Virtual environments are excluded from file hashing but not from
    discovery.
- **Impact:** a directory name such as `x|y|;e CMD #` ends the substitution,
  and GNU sed's `e` command then runs a command. That happens as each audited
  account, whether the audit runs locally, over SSH or from cron.
- **Likelihood:** low. A crafted directory name with a matching
  `.claude/skills/<skill>/` copy must exist within the search depth, for
  example from a cloned repository, an archive or package data.
- **Verification:** such a directory made GNU sed 4.10 create a marker file,
  and `git clone` kept the crafted path.
- **Related, from the identification pass only:**
  - `git status` in discovered clones ([`:82`][audit]) honours a planted
    `core.fsmonitor`.
  - Tab-separated records can be forged with newlines.
  - The SSH host is not preceded by `--`.
- **Draft issue:**
  - **Title:** Stop fleet-audit from building sed scripts from paths.
  - **Work:**
    - List files with `find "$1/" -type f -printf '%P\n'`, or change into
      the directory first.
    - Run `git -c core.fsmonitor= status`.
    - Separate records with NUL, and pass `--` before the SSH host.
  - **Acceptance:** a test directory whose name contains `|`, `;e` and a
    newline is audited without running anything, and is reported literally.

### S11. android-diagnostics analysis output is not private

Medium on hosts with other local users, Low otherwise. Verified,
confidence 8.

- **Evidence:**
  - [`android-diagnostics/scripts/analyze.py:244`][analyze] creates the
    `--bugreport` workdir with `exist_ok=True`, and [`:261`][analyze] writes
    with `write_text`.
  - [`:281-282`][analyze] keeps an existing zip link, and
    [`android-diagnostics/scripts/androiddiag/source.py:318-320`][source]
    analyses the first `bugreport*.zip` it finds there.
  - [`android-diagnostics/scripts/report.py:876-877`][report] also uses
    `write_text`.
  - [`android-diagnostics/references/collection.md:323`][collection]
    suggests a predictable `/tmp` workdir.
- **Impact:**
  - `analysis.json` (peer MAC and IP addresses, the app list, raw evidence
    lines) and the report are readable by other local users.
  - A user who creates the workdir first can plant a zip, which feeds
    [S4], or plant an `analysis.json` symlink that the victim's run follows
    and overwrites.
- **Likelihood:** needs another local account and the zip-only flow. The
  `collect.py` flow is protected by its 0700 workdir.
- **Verification:**
  - Under umask 022 the workdir came out 0755 and the files 0644.
  - A planted symlink in a pre-created directory was followed.
- **Overlap:** a gap left by the completed
  [capture-protection task][task-1], which covered `collect.py`,
  `adb_ro.py` and `sample_live.py` but not analysis or reports.
- **Draft issue:**
  - **Title:** Write android-diagnostics analysis and reports privately.
  - **Work:**
    - Use `private_directory` and `write_private` from
      [`storage.py`][storage] in `analyze.py` and `report.py`, including for
      `--output`.
    - Refuse a non-empty or foreign-owned `--bugreport` workdir, and update
      the suggestion in `collection.md`.
  - **Acceptance:**
    - Under umask 022, the workdir is 0700 and outputs are 0600.
    - A pre-created foreign directory is refused.
    - A symlinked `analysis.json` is not followed.

## Lower-confidence findings worth fixing

### S12. mcp-to-skill puts credentials in versioned config

Medium. Verified, confidence 7 for credentials and 6 for server text.

- **Evidence:**
  - [`mcp-to-skill/scripts/mcp_to_skill.py:159-164`][mcp_to_skill] writes
    the whole server config, `env` included, to `mcp-config.json` with mode
    0644. [`convert_mcp_to_skill.py:106-111`][convert_mcp] writes a temporary
    copy the same way.
  - The [example configs][mcp-examples] put tokens and passwords in `env`.
  - [`executor.py.template:25-31`][executor-template] passes `env` unchanged.
    The local MCP SDK hands a stdio server only `HOME`, `LOGNAME`, `PATH`,
    `SHELL`, `TERM` and `USER`, so a literal value in the file is the only
    way to give a server its token.
  - [`mcp-to-skill/SKILL.md:89`][mcp-skill] copies the generated directory
    into the skills folder, [`:205`][mcp-skill] says "Keep MCP configurations
    in version control", and [`:206`][mcp-skill]'s environment-variable
    advice has no effect.
  - This repository already commits one generated config,
    [`context7-skill/mcp-config.json`][context7-config]. Its `env` is empty.
  - [`mcp_to_skill.py:99-103`][mcp_to_skill] and [`:124-131`][mcp_to_skill]
    copy server-written tool descriptions verbatim into the generated
    `SKILL.md` ([`SKILL.md.template:31`][skill-template]).
- **Impact:** following the documented flow for a server that needs a token
  commits that token to a public repository. A remote or compromised server's
  descriptions become trusted skill instructions for every later session.
- **Likelihood:** needs a conversion with a token, then a commit.
- **Draft issue:**
  - **Title:** Keep MCP credentials and server text out of generated skills.
  - **Work:**
    - Store only environment variable names in the config, and have the
      executor read `os.environ` at run time.
    - Write configs with mode 0600, drop the version-control advice, and add
      a secret check or ignore rule for `mcp-config.json`.
    - Put server descriptions in a fenced, truncated data block with control
      characters stripped, and fix the template's missing opening `---`.
  - **Acceptance:**
    - Converting a synthetic config with a token leaves the token out of
      every generated file.
    - Descriptions appear only inside the data block.

### S13. Transcription and watch history use shared /tmp

Low. Verified, confidence 7 for transcription and 6 for watch history.

- **Evidence:**
  - [`youtube-transcription/scripts/transcribe_video.py:28`][transcribe]
    downloads to `/tmp/<id>.<ext>`. [`:36-39`][transcribe] then uploads the
    newest `*.mp3` anywhere in `/tmp`, and [`:93-94`][transcribe] writes
    `/tmp/transcript.txt` with mode 0644.
  - [`youtube-transcription/SKILL.md:77`][transcription-skill] files that
    transcript into notes.
  - [`browser-youtube-history/SKILL.md:81-84`][byh-skill],
    [`:105-110`][byh-skill], [`:130`][byh-skill] and the
    [README][byh-readme] send dumps of the logged-in activity page to fixed
    `/tmp` names.
  - [`find_youtube_history.py:130`][find_history] and
    [`find_video_details.py:99`][find_details] write with the default mode.
- **Impact:**
  - When `/tmp/<id>.mp3` already exists, the download is skipped. A newer
    unrelated or planted mp3 is then uploaded to AssemblyAI and filed as the
    transcript.
  - Private watch history and transcripts of private recordings are readable
    by the other login accounts on the host.
- **Likelihood:** needs a stale file or another local account. Sandboxed runs
  cannot write to `/tmp`.
- **Draft issue:**
  - **Title:** Keep transcription and watch-history files in private per-run
    folders.
  - **Work:**
    - Use `mkdtemp` per run, and take the real output path from yt-dlp
      (`--print after_move:filepath`).
    - Write outputs with mode 0600, or to a path the caller chooses.
    - Default history dumps to a 0700 folder, and remove the `/tmp` advice
      from both skills.
  - **Acceptance:**
    - A newer unrelated mp3 in `/tmp` is ignored.
    - Every output is 0600 inside a 0700 folder.

### S14. conventional-committer double-quotes commit messages

Low. Verified, confidence 6.

- **Evidence:**
  - [`conventional-committer/SKILL.md:157-163`][cc-skill] gives
    `git commit -m "<subject>" -m "<body>"` as the template, and
    [`:146`][cc-skill] asks the agent to imitate recent commits.
  - Six commit bodies in history contain backticked commands.
  - [`commit/SKILL.md:106`][commit-skill] already uses the safe
    `git commit -F- <<'COMMIT_EOF'`.
- **Impact:** bash runs any backticked command or `$(…)` in a body before
  committing. A quoted `` `git add -A` `` would sweep untracked files into the
  commit.
- **Likelihood:** no attacker is needed. The skill can be invoked by the model,
  and it is invoked whenever someone says "commit" in this repository.
- **Draft issue:**
  - **Title:** Pass conventional-committer messages through a quoted heredoc.
  - **Work:**
    - Replace the `-m` template with `git commit -F - <<'EOF'`.
    - Optionally add `.env`, key and token patterns to the root
      [`.gitignore`][gitignore], because the skill's "commit everything"
      path runs `git add -A`.
  - **Acceptance:**
    - No double-quoted message template remains.
    - A body containing backticks is committed verbatim.

## Privacy findings

### P1. Personal data in the public tree and history

The repository's [`AGENTS.md`][agents-md] forbids personal data in public
material. The values are withheld here, and each location gives the kind of
data only.

- **Third party:** [`fonecta-lookup/references/fonecta-api.md:99-104`][fonecta-api]
  and [`:114-117`][fonecta-api] show what looks like a real person's directory
  record, not placeholders. It has a full name, a mobile number, an employer
  and a business ID whose check digit is valid. Added in `b479cf6`.
- **Owner:**
  - [`fonecta-lookup/scripts/fonecta_lookup.py:103`][fonecta_lookup]
    hard-codes the owner's first name as its login check; added in `b479cf6`.
  - [`kuluttaja/references/api.md:92`][kuluttaja-api] has the owner's
    personal email address. It was added in `deab7d3`, after the earlier PII
    cleanup in `e45db23`.
  - [`email-mailbox-analyzer/README.md:28`][analyzer-readme] has a personal
    email address and the mail provider's host. [`:52`][analyzer-readme] has
    a real mail-client profile ID, which is also hard-coded in
    [`email-mailbox-analyzer.sh:80`][analyzer-sh].
  - [`jmap/SKILL.md:12`][jmap-skill], [`:33`][jmap-skill] and
    [`jmap/sync_emails.py:22`][sync_emails] use the owner's surname as the
    account ID.
- **Message content:**
  - [`himalaya-email-manager/references/scripts.md:32-34`][himalaya-scripts-ref]
    shows real-looking inbox subjects and sender organisations.
  - [`himalaya-email-manager/references/troubleshooting.md:67`][himalaya-troubleshooting]
    and [`:86`][himalaya-troubleshooting] name the provider host.
  - [`jmap/sync_emails.py:42`][sync_emails] and [`:44`][sync_emails] use a
    real-looking correspondent's name and domain as examples.
- **History:** the introducing commits are on the public `origin/main`.
  Editing the files removes the data from the tree but not from history.
- **Overlap:** the completed [example-sanitising task][task-12] cleaned other
  skills' examples and missed these.
- **Draft issue:**
  - **Title:** Replace personal data in skill references with synthetic
    examples.
  - **Work:**
    - Replace every listed value with RFC 2606 domains and obvious
      placeholder names, numbers and IDs.
    - Make the analyzer's profile path an argument, and move the Fonecta
      login check to a page element that names no one.
    - Record the user's decision on rewriting public history, at least for
      the third party's record.
  - **Acceptance:**
    - None of the listed values remains in the tree, and the `AGENTS.md`
      pre-commit checklist passes.
    - The history decision is recorded.

**Recommendation:** treat the third party's record as the priority. Of all the
values, it is the one that belongs to someone who never chose to be in the
repository.

## Hardening notes without drafted issues

These are real but either fell below the threshold or are hardening, not a
vulnerability. They can ride along with the drafts above or wait.

- **t3-start-thread:** none of these crosses a trust boundary today (verified,
  confidence 2 to 3).
  - [`start_thread.py:94-107`][start_thread] mints a session with T3's
    administrative default scopes and never revokes it.
  - [`:212-213`][start_thread], [`:456`][start_thread] and
    [`:552`][start_thread] send cross-thread messages as the user, where T3's
    native tool records agent provenance.
  - The helper skips the native tool's runtime-mode escalation check when
    starting threads.
  - Narrow `--scope` and revocation, plus agent provenance, would be cheap
    hardening.
- **Mail skills:**
  - [`email-delete.py`][email-delete] prompts only on a terminal; `--execute`
    is the consent, and the "(interactive mode only)" wording in `SKILL.md`
    is ambiguous.
  - The troubleshooting reference prints the himalaya config, which holds no
    secret when the keyring is used.
  - [`email-mailbox-analyzer.sh:62`][analyzer-sh] runs a third-party tool
    unpinned from Git with IMAP credentials (confidence 4).
  - [`email-mailbox-analyzer.sh:49`][analyzer-sh] and `:115-116` pair one
    account's username with another account's host, so a username is sent to
    the wrong server. This is a functional bug, confidence 9 in the
    identification pass.
- **Committing skills:**
  - Library [`push`][library-push] commits without a pathspec in the shared
    checkout, so another session's staged changes go out with it
    (confidence 4).
  - [`commit-organizer`][co-skill] has no secret check before its
    "status empty" completion (confidence 3).
  - [`learn`][learn-skill] pre-approves all tools and writes global
    instructions without approval; it is user-invoked (confidence 3).
  - Library [`use`][library-use] would clone and install remote skills
    unpinned, but the [catalog][library-yaml] has no remote sources today.
- **Credentials in commands:**
  - [`fonecta-lookup/SKILL.md:40`][fonecta-skill] and `:49` show the password
    inline in the command (confidence 4).
  - [HSL scripts][hsl-scripts] fall back to a generic `API_KEY` variable and
    send it to Digitransit. This relies on the environment, which the
    skill's false-positive rules treat as trusted.
- **Session readers:** the [session-log readers][claude-logs] and
  [`read_zed_threads.py`][zed] reprint old transcripts with no redaction.
  That is their purpose and the data was already logged (confidence 3). The
  Zed reader also opens Zed's database read-write ([`:238`][zed]).
- **Downloaded media:**
  - [`yt_frame_analysis.py:99-108`][yt-frame] passes the URL to yt-dlp
    without `--`; argparse blocks a leading `-` today.
  - [`pdf-to-markdown/scripts/convert.py`][pdf-convert] leaves the uploaded
    PDF on the Gemini Files API if a run fails.
  - [`kuluttaja/scripts/extract.py`][kuluttaja-extract] `--search` writes
    article files into the current directory and overwrites them.
- **android-diagnostics:**
  - [`redact.py`][redact] misses names in free text and dictionary keys
    (confidence 6).
  - [`perfetto_sql.py`][perfetto] downloads a native binary without asking
    (confidence 5).
  - [`readonly.py`][readonly] checks paths with `fnmatch`, which ignores
    POSIX bracket classes the phone shell may expand (confidence 3,
    unverified on a device).
- **Repository:**
  - The [workflows] have no `permissions:` block and pin actions by tag.
    Nothing untrusted reaches them.
  - [`.claude/commands/lint.md:9`][lint-cmd] passes `$ARGUMENTS` unquoted.

## Rejected candidates

- **Email guardrails:** the instruction to "delete" removes only the local
  attachment copies the skill just made. Mailbox deletion is dry-run by
  default and asks the user first.
- **JMAP proxy without authentication:** the open listener is outside this
  repository; the skill is only its client.
- **Shell quoting in `SKILL.md` command templates:** the placeholders come
  from the user's own request, and single-quoting JSON is correct.
- **Unpinned context7 server:** same trust class as the repository's other
  unpinned dependencies.
- **Untrusted-text rule in android-diagnostics:** has no exploit of its own;
  its concrete form is [S4].

## History scan

The scan ran `git log --all -p` across all 327 commits on every ref: local and
remote-tracking branches, and T3 checkpoint refs. It matched patterns for AWS,
GitHub, Google, Slack, OpenAI-style, Anthropic, Brave, Context7 and Asana
tokens, private-key headers, JWTs, credentials embedded in URLs, bearer
tokens, key-like assignments and long hex strings. Every match was masked
before printing and classified by shape. A second check listed every file name
ever added that looks like a credential file.

- **Public key:** [`tokmanni/scripts/search.py:25`][tokmanni-search] holds
  Tokmanni's Klevu search key, which the shop's own pages send to every
  browser. [`secrets-scan/SKILL.md:173`][secrets-skill] reuses it as an
  example ([S3]).
- **Test fixtures:** [`reflect-extensions/tests/test_capture_learning.py`][test-capture]
  contains private-key header lines only, used to test redaction.
- **Placeholders:**
  - [`mcp-to-skill/assets/examples/postgres-mcp.json:7`][postgres-example]
    and [`secrets-scan/references/classifying-findings.md:60-61`][classifying]
    hold placeholder connection strings.
  - `credentials-check/references/detect_secrets_cli.md`, removed since
    commit `4768d9eec8`, and `classifying-findings.md` at `de8fed306c` held
    the same allowlisted placeholder.
  - [`pdf-to-markdown/examples/yhteisoohjautuvuus/config.toml:3`][pdf-config]
    holds a three-character placeholder.
- **Not a secret:**
  [`android-diagnostics/scripts/androiddiag/battery_history.py:311`][battery_history]
  holds an Android event name.
- **File names:** no `.env`, key, token, cookie or credential file was ever
  added.

The area passes repeated per-area history checks and found the same
placeholders.

**Limits:**
- Binary files were not scanned.
- A password stored under a name that looks nothing like a key would not
  match.

[History scan]: #history-scan
[P1]: #p1-personal-data-in-the-public-tree-and-history
[S1]: #s1-read-as-markdown-runs-pdf-file-names-as-shell-code
[S2]: #s2-email-attachments-silently-replace-files-in-the-project
[S3]: #s3-secrets-scan-prints-every-secret-it-finds
[S4]: #s4-android-diagnostics-passes-zip-text-to-the-shell
[S5]: #s5-read-as-markdown-trusts-a-planted-cache-index
[S6]: #s6-rebase-alls-undo-rolls-back-other-tasks-commits
[S7]: #s7-reflect-extensions-prints-whole-config-files
[S8]: #s8-receipt-reruns-overwrite-corrected-results
[S9]: #s9-discard-whitespace-hunks-discards-meaningful-changes
[S10]: #s10-fleet-audit-builds-a-sed-script-from-directory-paths
[S11]: #s11-android-diagnostics-analysis-output-is-not-private
[S12]: #s12-mcp-to-skill-puts-credentials-in-versioned-config
[S13]: #s13-transcription-and-watch-history-use-shared-tmp
[S14]: #s14-conventional-committer-double-quotes-commit-messages

[agents-md]: ../../AGENTS.md
[analyze]: ../../android-diagnostics/scripts/analyze.py
[analyzer-readme]: ../../email-mailbox-analyzer/README.md
[analyzer-sh]: ../../email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh
[android-skill]: ../../android-diagnostics/SKILL.md
[audit]: ../../fleet-audit/scripts/audit.py
[battery_history]: ../../android-diagnostics/scripts/androiddiag/battery_history.py
[budget]: ../../android-diagnostics/scripts/androiddiag/budget.py
[byh-readme]: ../../browser-youtube-history/README.md
[byh-skill]: ../../browser-youtube-history/SKILL.md
[capture_learning]: ../../reflect-extensions/scripts/capture_learning.py
[catalog]: ../../android-diagnostics/scripts/androiddiag/catalog.py
[cc-skill]: ../../conventional-committer/SKILL.md
[classifying]: ../../secrets-scan/references/classifying-findings.md
[claude-logs]: ../../claude-session-logs/scripts/
[co-skill]: ../../commit-organizer/SKILL.md
[collection]: ../../android-diagnostics/references/collection.md
[commit-skill]: ../../commit/SKILL.md
[context7-config]: ../../context7-skill/mcp-config.json
[convert_mcp]: ../../mcp-to-skill/scripts/convert_mcp_to_skill.py
[cpu]: ../../android-diagnostics/scripts/androiddiag/cpu.py
[domains]: ../../android-diagnostics/references/domains.md
[dwh]: ../../discard-whitespace-hunks/scripts/discard_ws_hunks.py
[dwh-skill]: ../../discard-whitespace-hunks/SKILL.md
[email-delete]: ../../himalaya-email-manager/scripts/email-delete.py
[email_save]: ../../himalaya-email-manager/scripts/email_save.py
[executor-template]: ../../mcp-to-skill/assets/templates/executor.py.template
[find_details]: ../../browser-youtube-history/scripts/find_video_details.py
[find_history]: ../../browser-youtube-history/scripts/find_youtube_history.py
[fonecta-api]: ../../fonecta-lookup/references/fonecta-api.md
[fonecta-skill]: ../../fonecta-lookup/SKILL.md
[fonecta_lookup]: ../../fonecta-lookup/scripts/fonecta_lookup.py
[gitignore]: ../../.gitignore
[himalaya-scripts-ref]: ../../himalaya-email-manager/references/scripts.md
[himalaya-skill]: ../../himalaya-email-manager/SKILL.md
[himalaya-troubleshooting]: ../../himalaya-email-manager/references/troubleshooting.md
[hsl-scripts]: ../../hsl/scripts/
[jmap-skill]: ../../jmap/SKILL.md
[kuluttaja-api]: ../../kuluttaja/references/api.md
[kuluttaja-extract]: ../../kuluttaja/scripts/extract.py
[learn-skill]: ../../learn/SKILL.md
[library-push]: ../../library/cookbook/push.md
[library-use]: ../../library/cookbook/use.md
[library-yaml]: ../../library/library.yaml
[lint-cmd]: ../../.claude/commands/lint.md
[logs]: ../../android-diagnostics/scripts/androiddiag/logs.py
[mcp-examples]: ../../mcp-to-skill/assets/examples/
[mcp-skill]: ../../mcp-to-skill/SKILL.md
[mcp_to_skill]: ../../mcp-to-skill/scripts/mcp_to_skill.py
[pdf-config]: ../../pdf-to-markdown/examples/yhteisoohjautuvuus/config.toml
[pdf-convert]: ../../pdf-to-markdown/scripts/convert.py
[perf]: ../../android-diagnostics/scripts/androiddiag/perf.py
[perfetto]: ../../android-diagnostics/scripts/perfetto_sql.py
[postgres-example]: ../../mcp-to-skill/assets/examples/postgres-mcp.json
[ram]: ../../read-as-markdown/scripts/read_as_markdown.py
[readonly]: ../../android-diagnostics/scripts/androiddiag/readonly.py
[rebase-skill]: ../../rebase-all/SKILL.md
[rebase_all]: ../../rebase-all/scripts/rebase_all.py
[receipts]: ../../processing-scanned-receipts/process_receipts.py
[receipts-skill]: ../../processing-scanned-receipts/SKILL.md
[redact]: ../../android-diagnostics/scripts/androiddiag/redact.py
[reflect-cmd]: ../../reflect-extensions/commands/reflect-extensions.md
[report]: ../../android-diagnostics/scripts/report.py
[scan]: ../../secrets-scan/scripts/scan.py
[secrets-skill]: ../../secrets-scan/SKILL.md
[skill-template]: ../../mcp-to-skill/assets/templates/SKILL.md.template
[source]: ../../android-diagnostics/scripts/androiddiag/source.py
[start_thread]: ../../t3-start-thread/scripts/start_thread.py
[storage]: ../../android-diagnostics/scripts/androiddiag/storage.py
[sync_emails]: ../../jmap/sync_emails.py
[task-1]: ../tasks/1-protect-android-diagnostics-captures-from-other-local-users.md
[task-11]: ../tasks/11-make-receipt-dry-run-use-cached-metadata-without-side-effects.md
[task-12]: ../tasks/12-sanitize-skill-examples-and-check-secrets-without-printing-them.md
[test-capture]: ../../reflect-extensions/tests/test_capture_learning.py
[tokmanni-search]: ../../tokmanni/scripts/search.py
[transcribe]: ../../youtube-transcription/scripts/transcribe_video.py
[transcription-skill]: ../../youtube-transcription/SKILL.md
[workflows]: ../../.github/workflows/
[yt-frame]: ../../youtube-frame-analysis/scripts/yt_frame_analysis.py
[zed]: ../../zed-threads/scripts/read_zed_threads.py

[16]: ../tasks/16-fix-the-three-high-findings-of-the-2026-10-21-security-review.md
