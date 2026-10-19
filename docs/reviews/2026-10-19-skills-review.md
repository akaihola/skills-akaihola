# Skills review, 2026-10-19

Reviewed `main` at `6e32698a475dfceb6e1277efff50edbc4a8f8f00`.
All evidence locations below refer to that commit, not installed skill copies.
The only implementation deliverable is this report. Drafts have not been filed.

## Inventory and method

The inventory contains every tracked `SKILL.md`: 48 source skills, counting
`context7-skill` once under its directory name even though its frontmatter name
is `context7`. Discovery symlinks are not additional skills. Reflection is a
command/hook plugin without a `SKILL.md`; its tests were also checked.

Description lengths use YAML-decoded text, counting Unicode characters and
whitespace-separated words. Body lengths include frontmatter and count lines,
words and UTF-8 bytes. These are reproducible size measurements, not tokenizer
counts. In the references column, `R/` means that skill's `references/`, `C/`
means `cookbook/`. Listed files are the references the instructions actually
name, including plain-code pointers. Cross-skill routing and caller configuration are described in the review
column rather than counted as bundled reference files. They are conditional unless stated
otherwise; a pointer does not prove a file is loaded on every invocation.
All named repository reference files resolve. The library frontmatter error
required parsing its description independently of its invalid argument hint.
Example inputs, generated output, user configuration and external tools were distinguished from bundled files.

Applied writing-for-agents to descriptions and instructions: one trigger per
distinct branch, positive steps, checkable completion, one source of truth, and
conditional disclosure. Applied honey-review to script structure, preserving
validation, error handling, authentication and tests. Findings distinguish
observed defects from proposed cuts and unverified external compatibility.
No service, browser, credential scanner, messaging or thread operation was run.

| Skill directory | Description chars / words | SKILL lines / words / bytes | Named references | Review and offline result |
| --- | ---: | ---: | --- | --- |
| `android-diagnostics` | 621 / 98 | 293 / 2335 / 15468 | `R/collection.md`; `R/domains.md`; `R/experiments.md`; `R/followups.md`; `R/interpretation.md`; `R/vendor-notes.md` | Concrete symptoms; keep read-only/evidence rules. Disclose JSON schema and optional tooling, D12. 7 help passes; 948 tests pass. |
| `asana` | 226 / 38 | 55 / 227 / 1731 | README.md | Live-operation trigger advertises a design-only skill. D4. No scripts or tests. |
| `bauhaus` | 285 / 42 | 51 / 209 / 1736 | `R/api.md` | Store-specific; redundant trigger synonyms, D10. Help passes; no tests. |
| `brave-search` | 376 / 58 | 59 / 487 / 3670 | `R/brave_search_examples.md`; `R/brave_summarizer_workflow.md`; `R/brave_web_search_params.md` | Generic search trigger competes with native search; D9. Help passes; no tests. |
| `browser-youtube-history` | 471 / 76 | 146 / 776 / 5555 | README.md | Good private-history/public-URL boundary. Resolve helper paths from skill location, D8. 2 help passes; no tests. |
| `clasohlson` | 360 / 52 | 108 / 395 / 3098 | `R/api.md` | Store-specific; body repeats CLI/API reference, D10. Help passes; no tests. |
| `claude-session-logs` | 542 / 79 | 186 / 960 / 7350 | None | Useful cross-agent boundary; long samples/schema can be conditional, D12. 2 help passes; no tests. |
| `commit` | 120 / 17 | 132 / 742 / 4964 | None | User-invoked; overlaps conventional-committer. D5. No helper CLI. |
| `commit-organizer` | 107 / 16 | 72 / 689 / 4491 | TRIAGE.md; `examples/commit-organizer.yml` | User-invoked with clear single-commit exclusion; points to disabled commit skill. D5. 3 help passes; no tests. |
| `context7-skill` | 319 / 44 | 161 / 749 / 5079 | `examples/test_skill.py` | Named service but generic library-docs trigger; static schemas and unsupported savings claims. D11. Help passes; example is live, not an offline test. |
| `conventional-committer` | 367 / 54 | 190 / 1534 / 10316 | None | Duplicates commit workflow and repeatedly reconstructs full context. D5. Help passes; no tests. |
| `discard-whitespace-hunks` | 502 / 76 | 92 / 463 / 3128 | None | Concrete operation; trim synonymous description. Manual parser has no help branch, D7. No tests. |
| `ecb-rates` | 132 / 20 | 31 / 154 / 936 | None | Fixed historical default and undocumented command alias, D6. Help unsupported; no tests. |
| `email-mailbox-analyzer` | 224 / 33 | 113 / 460 / 3390 | None | Purpose concrete; advertised profile discovery/override missing in script. D3. Help unsupported; no tests. |
| `fleet-audit` | 397 / 64 | 88 / 742 / 4607 | `R/fleet.example.toml` | Concrete anomaly-only contract, distinct from cache sync. Help passes; no tests. Target endpoints intentionally not exercised. |
| `fonecta-lookup` | 268 / 39 | 99 / 616 / 4411 | `R/fonecta-api.md` | Concrete country/subscription boundary; login details already in reference. Help passes; no tests. Live selectors unverified. |
| `gemini-vision` | 294 / 40 | 100 / 446 / 3561 | None | Generic image trigger can cause unnecessary paid remote analysis, D9. Help blocked by offline dependency cache; no tests. |
| `himalaya-email-manager` | 163 / 23 | 176 / 804 / 6840 | None | Backend named; omit generic natural-language promise and clarify save/read/delete branches, D9. 5 help passes; 32 tests pass. |
| `hsl` | 257 / 36 | 138 / 671 / 4664 | `R/api.md` | Region clear; duplicate routing prose and historical auth/scaffold notes, D12. 3 help passes; no tests. |
| `jmap` | 302 / 42 | 80 / 394 / 2947 | None | Description names wrong repository; account/tunnel assumptions are environment-specific. D13. Help passes; no tests. |
| `k-rauta` | 334 / 50 | 39 / 163 / 1306 | `R/api.md` | Good price limitation; redundant synonyms, D10. Help passes; no tests. |
| `kuluttaja` | 442 / 60 | 145 / 628 / 4817 | `R/api.md` | Public/paywall distinction useful; referenced browser fallback absent; dead helper. D14. Help blocked by offline dependency cache; no tests. |
| `learn` | 100 / 15 | 107 / 798 / 5237 | None | User-invoked, exhaustive completion criteria. No confirmed stale helper/reference; no CLI or tests. |
| `library` | 269 / 41 | 122 / 724 / 5493 | `C/add.md`; `C/install.md`; `C/list.md`; `C/push.md`; `C/remove.md`; `C/search.md`; `C/sync.md`; `C/use.md` | Conditional cookbook routing is good; bare library/agentic-management trigger too broad. D9/D13. Invalid YAML, D19. No CLI or tests. |
| `mcp-to-skill` | 173 / 30 | 217 / 715 / 5140 | `R/async_context_manager_fix.md`; `R/context_optimization.md`; `R/converter_details.md`; `R/mcp_basics.md` | Concrete conversion purpose; unsupported percentage promise and repetitive instruction body. D11. 2 help passes; 7 tests pass, 4 integration tests excluded. |
| `motonet` | 289 / 42 | 106 / 377 / 2818 | `R/api.md` | Store-specific; repeated CLI/API schema, D10. Help passes; no tests. |
| `nano-banana-image` | 221 / 30 | 117 / 386 / 3335 | None | Generic generation/edit trigger may override configured image tools, D9. Help blocked by offline dependency cache; no tests. |
| `netrauta` | 295 / 42 | 38 / 148 / 1204 | `R/api.md` | Compact body, distinct store target; simplify synonyms, D10. Help passes; no tests. |
| `pandoc-typst-pdf` | 614 / 97 | 201 / 926 / 6766 | None | Concrete engine/output boundary; basic command omits font later called mandatory, D15. External CLI availability checked below; no tests. |
| `pdf-to-markdown` | 256 / 34 | 99 / 440 / 3052 | None | Overlaps local document reading; specify section/image conversion and remote upload, D9. Help unsupported; dependencies absent; no tests. |
| `pi-session-logs` | 483 / 74 | 172 / 867 / 7252 | None | Pi/CCM scope concrete; checkout-name typo breaks examples, D8. 2 help passes; no tests. |
| `power` | 274 / 42 | 172 / 655 / 5397 | `R/api.md` | Description misses store-stock branch; long field tables can be disclosed, D10. 2 help passes; no tests. |
| `processing-scanned-receipts` | 143 / 20 | 112 / 602 / 4315 | None | Concrete batch trigger; identifying examples and misleading preview. D2/D18. Help passes; no tests. |
| `puuilo` | 278 / 42 | 48 / 188 / 1507 | `R/api.md` | Compact store-specific body; redundant synonyms, D10. Help passes; no tests. |
| `read-as-markdown` | 432 / 73 | 125 / 541 / 4089 | None | Clear reading/creation distinction; distinguish local extraction from remote PDF conversion, D9. Help passes; no tests. |
| `rebase-all` | 355 / 58 | 150 / 1023 / 6507 | None | Concrete multi-branch scope; after-base-moves clause overtriggers; add offline stack fixtures, D16. Help passes; no tests. |
| `secrets-scan` | 489 / 73 | 276 / 1210 / 10147 | `R/classifying-findings.md` | Concrete scan purpose; long plugin/CLI tables duplicate help. D12. Help passes; no tests. Scanner runs intentionally excluded. |
| `simplify-skill` | 597 / 96 | 162 / 1406 / 8574 | None | Clear behavioural review scope, distinct from rewriting; description repeats synonym lists. D9. No CLI/tests; preserve workload questions. |
| `sync-plugin-cache` | 583 / 96 | 54 / 362 / 2573 | external memory note, availability unverified | Concrete cache operation; description repeats implementation and checkout assumptions. D9/D13. No CLI/tests; cache mutation excluded. |
| `t3-start-thread` | 200 / 33 | 180 / 1274 / 8984 | 4 pinned V1 upstream source/doc links, historical and unverified | Delegation and ordinary thread creation conflated; repair routing first. D1. Help passes; 83 tests pass. |
| `taloon` | 287 / 42 | 38 / 148 / 1198 | `R/api.md` | Compact body, distinct store target; simplify synonyms, D10. Help passes; no tests. |
| `tokmanni` | 294 / 42 | 112 / 393 / 3026 | `R/api.md` | Store-specific; repeated CLI/API schema, D10. Help passes; no tests. |
| `upstream-pr` | 68 / 12 | 302 / 1275 / 8559 | None | Every fork triggers a 302-line contribution workflow with fixed integration policy. D17. Shell syntax passes; help unsupported; no tests. |
| `verkkokauppa` | 324 / 42 | 117 / 410 / 3254 | `R/api.md` | Store-specific; repeated CLI/API schema, D10. Help passes; no tests. |
| `youtube-frame-analysis` | 366 / 55 | 114 / 611 / 4939 | None | Good visual/transcript split; unconditional capability injunction belongs outside description, D9. Help blocked by offline dependency cache; no tests. |
| `youtube-to-markdown` | 437 / 64 | 109 / 659 / 4465 | None | Useful free-caption preference and paid fallback; scripts exist. 2 help passes; no tests. Hints branch can be conditional, D12. |
| `youtube-transcription` | 492 / 68 | 237 / 779 / 6347 | `R/assemblyai_options.md` | Good caption/local-audio split; secret-printing troubleshooting and identifying examples. D2. Help unsupported; SDK unavailable; no tests. |
| `zed-threads` | 252 / 42 | 71 / 279 / 2052 | None | Concrete local reader; manual parser reads database before options, D7. Help unsafe to probe; no tests. |

Totals: descriptions 15,680 characters / 2,362 words; SKILL files 6,112 lines / 31,840 words / 230,295 bytes. User-invoked skills with `disable-model-invocation: true`: commit, commit-organizer, learn. Their descriptions are human-facing in harnesses that honor this field.

## Ranked findings and issue drafts

Order reflects avoided wrong actions and wasted work per agent hour, then
recurring context savings. It is a judgement, not a measured financial return.
Each draft is scoped to roughly one agent hour and remains a proposal.

Do **D1, D18 and D2 first**. D1 fixes the coordination path used on every
steward run. D18 makes a preview stop before paid OCR and writes. D2 removes
identifying examples and an instruction to print a secret from reusable public
instructions. These change behaviour or exposure immediately; token-only cuts
come later.

Duplicate check covered every section of `TASKS.md`, `BACKLOG.md` and
`library/BACKLOG.md`. There are no other active tracker issues. Completed but
unaccepted [6], [7] and [8] cover T3 protocol/settlement and acceptance evidence,
not D1's delegation routing. D13 overlaps an existing JMAP idea and is marked
for amendment there. The library list/search/status ideas overlap the broader
inventory tooling opportunity; they should absorb that work rather than gain
another draft. None of the Android drafts repeats completed [1] through [5].

### D1. Route T3 delegation through child-task orchestration

Evidence: `t3-start-thread/SKILL.md:3` includes delegation in its trigger;
`t3-start-thread/SKILL.md:107` routes handoff through `start`;
`t3-start-thread/scripts/start_thread.py:523` exposes ordinary thread actions,
not a delegated-task action. The skill itself distinguishes a harness subagent
at `t3-start-thread/SKILL.md:9`, but never gives that branch a child-task path.
The current session's T3 contract explicitly distinguishes delegated tasks from
top-level conversations. This is an instruction mismatch, not a failed live probe.

Draft title: **Separate T3 child-task delegation from top-level launches.**
Work: introduce an explicit intent decision before helper commands; route
subagent requests through live orchestration capabilities/delegate_task and
reserve `start` for explicitly requested ordinary threads. Keep the helper's
protocol and interruption recovery rules. Acceptance: synthetic requests for a
subagent, a new conversation and a follow-up each select the correct operation;
no live launch needed; all 83 helper tests still pass. Benefit: prevents the
wrong kind of conversation and its coordination overhead. Estimate: 1 hour.
Overlap: adjacent to completed [6]/[7], not a duplicate.

### D18. Make receipt preview stop before OCR and writes

Evidence: `processing-scanned-receipts/SKILL.md:41` promises a write-free
preview. `processing-scanned-receipts/process_receipts.py:282` creates the
work directory, `processing-scanned-receipts/process_receipts.py:296` submits
OCR work, and `processing-scanned-receipts/process_receipts.py:326` checks
`dry_run` only afterward. `processing-scanned-receipts/process_receipts.py:116`
invokes the paid OCR CLI. This was traced statically; no receipts were processed.

Draft title: **Make receipt dry-run use cached metadata without side effects.**
Work: check preview mode before directory creation or extraction; use existing
metadata to show renames and report cache misses explicitly. Acceptance: with
synthetic cached and uncached inputs, dry-run performs no subprocess calls,
creates no files and preserves source hashes; normal processing still works
with mocked OCR. Benefit: previews become safe cost-free checks. Estimate:
1 hour. Overlap: none.

### D2. Replace identifying examples and secret-printing guidance

Evidence: `processing-scanned-receipts/SKILL.md:22`,
`processing-scanned-receipts/SKILL.md:77` and
`processing-scanned-receipts/SKILL.md:100` contain person/business/travel
examples. `youtube-transcription/SKILL.md:143` tells the agent to echo its API
key, and `youtube-transcription/SKILL.md:188` embeds named-person examples.
`claude-session-logs/SKILL.md:54` and `claude-session-logs/SKILL.md:66` include
conversation-like samples. Their provenance is unverified; replace them with
clearly synthetic material. The repository's `AGENTS.md:5` requires protection
of personal information. Identifying values are deliberately not repeated here.

Draft title: **Sanitize skill examples and check secrets without printing them.**
Work: replace identifying content with generic synthetic fixtures and reserved
example domains; replace key echoing with a presence-only check; review the
adjacent references/scripts for the same examples. Acceptance: no copied
personal or message content in changed examples, no command prints a credential,
and a before/after diff passes the repository privacy review. Benefit: prevents
examples and troubleshooting from propagating private content. Estimate:
1 hour. Overlap: none; a current-tree cleanup, not a history rewrite.

### D19. Quote the library argument hint so frontmatter parses

Evidence: `library/SKILL.md:4` contains two unquoted bracketed expressions.
`yaml.safe_load` rejects this frontmatter with `ParserError`; the other 47
frontmatters parse. The description still can be measured independently, but a
strict loader cannot parse the complete metadata.

Draft title: **Repair library frontmatter and validate all skill metadata.**
Work: quote the hint; add a small offline metadata check covering every tracked
skill with useful path-specific failures. Acceptance: all 48 frontmatters parse,
required names/descriptions are strings, and an invalid synthetic hint fails.
Benefit: restores strict-loader compatibility and detects this class of breakage
before discovery. Estimate: 1 hour. Overlap: none.

### D4. Stop discovering Asana as an implemented operational skill

Evidence: `asana/SKILL.md:3` advertises task creation and updates, while
`asana/SKILL.md:8` says implementation does not exist. The three scripts named
at `asana/SKILL.md:17` are absent. This is a known design, not a missing
runtime dependency.

Draft title: **Move the unimplemented Asana workflow out of automatic discovery.**
Work: retain the design in its README; make the discoverable entry explicit
about design-only status or remove it from operational skill registration.
Acceptance: an Asana task query cannot lead an agent to run absent scripts;
the architecture remains available for explicit planning. Benefit: avoids a
certain dead end. Estimate: 0.5 to 1 hour. Overlap: none.

### D6. Document and test the real ECB command

Evidence: `ecb-rates/SKILL.md:12` advertises `fetch-rates [YEAR]`, but no such
wrapper is tracked. `ecb-rates/fetch_ecb_rates.py:4` names the actual invocation
and its extra dependency. `ecb-rates/fetch_ecb_rates.py:78` parses the first
argument as an integer and retains the 2025 default. Historical data is valid;
an unexplained fixed year is the stale expectation.

Draft title: **Give the ECB helper a documented CLI and offline fixture.**
Work: use the actual script path, expose year/output arguments through argparse,
state the historical-year policy explicitly and declare the XML dependency.
Acceptance: help exits before any fetch; an invented local XML fixture produces
the expected ordered CSV; the documented command matches the parser. Benefit:
removes a missing-command failure and makes the requested year explicit.
Estimate: 1 hour. Overlap: none.

### D5. Make commit selection and context collection authoritative once

Evidence: `commit/SKILL.md:54` restricts commits to the staged set;
`conventional-committer/SKILL.md:45` adds an exception for an explicit request
to include unstaged changes, and
`conventional-committer/SKILL.md:105` starts another full procedure.
`commit-organizer/SKILL.md:52` delegates formatting to `commit`, whose
`disable-model-invocation` is true at `commit/SKILL.md:4`. In harnesses that
honor it, that skill is user-only. The chunk helper rebuilds history and the
entire staged diff at `conventional-committer/scripts/git_context_chunks.py:129`
for every requested chunk. This has repeated computation even though only one
chunk is emitted.

Draft title: **Share commit policy and read only the context each commit needs.**
Work: put shared message/staging rules in an ordinary referenced document;
keep user-invoked entry points and repository-specific differences explicit;
replace repeated complete procedures with pointers. Choose one context-reading
path that preserves full review without rereading unchanged chunks. Acceptance:
staged-only, explicit include-all, conversation-only and mixed-intent examples
preserve the requested scope; the
organizer reaches shared policy without invoking a disabled skill; compare
loaded word counts before/after. Benefit: fewer competing policies and repeated
loads. Estimate: 1 hour. Overlap: none. Retiring the chunk helper requires a
caller check, not a blind deletion.

### D3. Match mailbox profile selection to its documentation

Evidence: `email-mailbox-analyzer/SKILL.md:88` promises discovery of the first
matching Thunderbird profile and an explicit override. The script instead
hardcodes one profile at
`email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh:80`, and its main
function does not parse arguments. It emits all extracted accounts on one
space-separated line at
`email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh:49`, while its caller
reads one record per line at
`email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh:93`.

Draft title: **Add explicit mailbox profile selection and one account per record.**
Work: implement a profile argument and documented discovery; return records
with stable newline boundaries; keep diagnostic text out of CSV data.
Acceptance: synthetic preferences with two accounts produce two separate
invocations of a fake imapdu; help and profile errors need no network; output
CSV contains only CSV records. Benefit: multi-account analysis works on another
installation. Estimate: 1 hour. Overlap: none.

### D8. Resolve executable paths from the loaded skill

Evidence: `pi-session-logs/SKILL.md:55` and
`pi-session-logs/SKILL.md:80` use a misspelled checkout directory;
`browser-youtube-history/SKILL.md:81` and `zed-threads/SKILL.md:21` assume a
particular checkout layout. `jmap/SKILL.md:3` claims its script belongs to a
different repository although `jmap/sync_emails.py` is bundled here.

Draft title: **Use skill-relative helper paths in the affected instructions.**
Work: fix these examples with one discovered skill directory per command;
distinguish skill paths from caller input/output paths. Acceptance: examples
resolve in a synthetic checkout at an arbitrary directory, with no service operations;
no private paths are introduced. Benefit: avoids deployment-specific command
failures. Estimate: 1 hour. Overlap: none; D13 owns account configuration.

### D9. Give broad descriptions distinct branches and boundaries

Evidence: `brave-search/SKILL.md:4` claims generic web search,
`gemini-vision/SKILL.md:4` claims generic image reading,
`nano-banana-image/SKILL.md:4` claims generic image generation,
`library/SKILL.md:3` claims bare library mentions, and
`simplify-skill/SKILL.md:3` spends a long description on synonymous trim requests.
`pdf-to-markdown/SKILL.md:3` overlaps document reading in
`read-as-markdown/SKILL.md:4`. These are potential routing collisions, not
measured false-trigger rates.

Draft title: **Clarify service selection and document-conversion boundaries.**
Work: write one trigger per real branch; state service prerequisites and when
native capabilities already satisfy the request. Distinguish cached local
reading from sectioned remote PDF conversion and image analysis from image
editing. Preserve caption-vs-paid-transcription boundaries. Acceptance: a
small synthetic request matrix covers positive and nearby negative cases for
each changed description; no enabled capability branch disappears; report
before/after description lengths without invented token savings. Benefit:
less unnecessary loading and remote processing. Estimate: 1 hour. Overlap: none.

### D10. Shorten store discovery metadata and disclose API tables

Evidence: the repetitive query/price synonyms at `tokmanni/SKILL.md:4` through
`tokmanni/SKILL.md:8` recur across the ten store skills. API/CLI detail already
lives in `tokmanni/references/api.md:1` but is repeated at
`tokmanni/SKILL.md:36` and `tokmanni/SKILL.md:89`. `power/SKILL.md:4` omits
its independent store-stock branch, documented at `power/SKILL.md:124`.

Draft title: **Use concise store triggers and conditional API references.**
Work: revise descriptions for the ten store skills to name store, search/prices
and supported stock branches once; retain K-Rauta's no-price limitation. Keep
one runnable example and point advanced fields/pagination to existing
references/help. Acceptance: each store retains a distinct positive trigger,
another-store negative case, and every existing operation remains reachable;
Power stock requests are included; record actual size reductions. Benefit:
lower recurring metadata and body cost. Estimate: 1 hour. Overlap: none.
Similar store scripts are intentionally portable units; do not introduce a
shared dependency merely to remove their superficial duplication.

### D11. Remove unmeasured MCP savings claims and duplicated recipes

Evidence: `context7-skill/SKILL.md:11` starts a cost explanation repeated at
`context7-skill/SKILL.md:140`; `context7-skill/SKILL.md:150` labels an increased
active-context count as savings. `mcp-to-skill/SKILL.md:3` promises 90% savings,
while `mcp-to-skill/SKILL.md:11` gives illustrative values without a reproducible
measurement. Schema discovery is required repeatedly at
`context7-skill/SKILL.md:67` and `context7-skill/SKILL.md:99`.

Draft title: **Keep MCP execution steps and disclose generator explanations.**
Work: retain resolve/discover-schema/call steps once; move generator mechanics
and extended examples to linked references; remove unsupported percentages.
Treat listed remote tool names as historical examples and discover the current
schema before use. Acceptance: a fake stdio server proves schema discovery and
execution; instructions make no measured savings or current-server claim without
evidence. Benefit: fewer tokens without dropping dynamic-schema correctness.
Estimate: 1 hour. Overlap: none. Remote tool availability was not checked here.

### D13. Parameterize JMAP assumptions, amend the existing proposal

Evidence: `jmap/SKILL.md:10` assumes one tunnel and port, `jmap/SKILL.md:12`
selects a particular account, and `jmap/sync_emails.py:20` has matching defaults.
The existing **JMAP mail skill backed by mailjail** idea in `BACKLOG.md:9`
already calls for multi-account operation, privacy and failure handling.

Draft title: **Amend the JMAP idea with portable endpoint/account selection.**
Work: add a one-hour first slice to that existing proposal: require or discover
account/endpoint inputs, document current single-account limits and make examples
independent of local topology. Acceptance: a fake JMAP session with two account
IDs cannot silently use a fixed account; endpoint errors are explicit; all
examples use generic data. Benefit: turns deployment assumptions into inputs.
Estimate: 1 hour. Overlap: **existing backlog idea; amend it, do not file a new
issue**. Library's local-path assumptions should be handled with its existing
catalog/status planning, rather than a new inventory-tool draft.

### D14. Remove the absent article fallback and dead client helper

Evidence: `kuluttaja/SKILL.md:75` points to
`scripts/extract_browser.py`, which is absent. The unused private `_client`
occupies `kuluttaja/scripts/extract.py:54` through line 58; repository search
finds no calls. `kuluttaja/scripts/extract.py:61` and
`kuluttaja/scripts/extract.py:79` accept auth arguments that their HTTP calls
ignore, so they should not imply an implemented authenticated path.

Draft title: **Describe article extraction's actual paywall boundary.**
Work: remove the absent fallback instruction; state what the bundled public
extractor returns and how an explicitly available authenticated browser would
be selected. Delete the dead private helper; audit callers before changing any
public signatures. Acceptance: a synthetic paywalled response is labelled as
a teaser; no instruction points to a missing script; public extraction fixtures
still work. Benefit: stops a predictable missing-file retry and removes dead
code. Estimate: 1 hour. Overlap: none.

### D15. Make the Pandoc quick start consistent with its font requirement

Evidence: `pandoc-typst-pdf/SKILL.md:36` gives a basic conversion without a font;
`pandoc-typst-pdf/SKILL.md:147` says omitting `mainfont` fails. On local Pandoc
3.7.0.2 and Typst 0.15.1, the exact quick-start shape fails with exit 43 and "font fallback list must not be empty". Adding
`-V mainfont="DejaVu Serif"` produces a 19,080-byte PDF with exit 0, entirely
offline. This confirms the quick-start defect for those versions.

Draft title: **Reconcile Pandoc-Typst quick start and font guidance.**
Work: choose a locally available font in a minimal offline example or scope the
warning to the template/version that requires it; disclose CJK/custom-template
details behind a conditional reference. Acceptance: one tiny Markdown input
renders with the documented local versions and selected font, and every
claimed mandatory option appears in the quick start. Benefit: removes an
internal contradiction and avoids failed first attempts. Estimate: 1 hour.
Overlap: none. Rendering was reproduced with the local versions above.

### D16. Add offline proof for stack rebasing before simplifying it

Evidence: `rebase-all/SKILL.md:38` requires parent-before-child ordering and
`rebase-all/SKILL.md:65` requires reference fixups before descendants.
`rebase-all/scripts/rebase_all.py:665` exposes the dispatcher, but no test file
exists for this skill. Help passing does not validate ref rewriting or rollback.
The description's after-base-moved clause at `rebase-all/SKILL.md:3` also permits
loading without an actual multi-branch request.

Draft title: **Test one synthetic rebase stack and its restore path offline.**
Work: create a temporary two-feature Git repository, rebase in plan order,
exercise a hash rewrite and restore the saved refs; narrow the trigger to a
requested multi-branch operation. Acceptance: the fixture requires no remote,
proves stack ancestry and restored identities, and never changes the caller's
repository. Benefit: enables evidence-based future cuts to a high-impact helper.
Estimate: 1 hour. Overlap: none. No algorithm rewrite is justified by this review.

### D17. Scope upstream contribution policy to an actual contribution request

Evidence: `upstream-pr/SKILL.md:4` loads for any work in a fork;
`upstream-pr/SKILL.md:60` imposes a fixed named integration branch and git-knit;
`upstream-pr/SKILL.md:201` assumes the agent cannot push, while
`upstream-pr/SKILL.md:218` describes a helper that pushes. These are local
workflow choices presented as universal runtime facts.

Draft title: **Separate upstream PR procedure from repository integration policy.**
Work: trigger on preparing/submitting an upstream contribution; take remote,
base and integration strategy from repository instructions; keep PR-draft
handling in a conditional reference and describe push capability from observed
permissions. Acceptance: ordinary work in a fork does not force a PR workflow;
a requested contribution preserves its draft and review steps; an offline
shell-parser test reaches help before any Git mutation. Benefit: avoids a
302-line irrelevant load and unsolicited branch policy. Estimate: 1 hour.
Overlap: none.

### D12. Disclose branch-specific instruction reference in small slices

Evidence: `android-diagnostics/SKILL.md:157` embeds the analysis schema despite
linking interpretation details at `android-diagnostics/SKILL.md:197`;
`secrets-scan/SKILL.md:213` starts a plugin table and
`secrets-scan/SKILL.md:244` starts copied CLI reference;
`claude-session-logs/SKILL.md:31` embeds an event schema;
`hsl/SKILL.md:117` repeats earlier implementation/auth notes;
`youtube-to-markdown/SKILL.md:46` embeds a structuring prompt needed only for
post-processing. These are conditional reference, not dead safety rules.

Draft title: **Disclose one instruction branch while preserving its completion bar.**
Work: start with secrets-scan, moving plugin/manual CLI reference behind one
conditioned link; keep execution, secret-handling and classification rules in
the main workflow. Use the other cited files as later one-hour slices, not one
large rewrite. Acceptance: all current branches remain reachable, each moved
file has an explicit load condition, body size falls, and synthetic scan-output
classification remains unchanged. Benefit: lower loaded context with checkable
behaviour preservation. Estimate: 1 hour for the first slice. Overlap: none.

### D7. Parse help before reading private data or performing work

Evidence: `zed-threads/scripts/read_zed_threads.py:282` reads the database
before manual argument parsing; `discard-whitespace-hunks/scripts/discard_ws_hunks.py:103`
only recognizes dry-run, `pdf-to-markdown/scripts/convert.py:107` treats its
first argument as a config, and `youtube-transcription/scripts/transcribe_video.py:61`
has only a positional-argument check. The mailbox shell script also has no
help parser. These cannot be safely treated like argparse help commands.

Draft title: **Give the Zed reader a side-effect-free help path.**
Work: parse index/no-color/help before opening the database; allow a fixture
database path; test invalid options and empty input. Treat the other manual
parsers as separately scoped follow-ups, with ECB owned by D6 and mailbox by
D3. Acceptance: help works with no database, never opens SQLite, and invalid
options fail before private reads; a synthetic database still renders the
chosen thread. Benefit: makes capability checks safe and adds a reusable test
boundary. Estimate: 1 hour. Overlap: D6/D3 own their respective parsers; no
second issue for those files.

## Honey script delete-list

1. `kuluttaja/scripts/extract.py:54`: cut the unused private `_client`; no
   repository caller uses it, and active requests construct HTTP calls directly.
   Saves 5 lines, tracked in D14.

Total: 5 lines across 1 justified code deletion. Single-caller functions that
carry validation, protocol translation, filesystem protection or testable
boundaries were retained. No hand-rolled stdlib replacement was justified from
the inspected call paths. Parallel store implementations target different
services and remain independently deployable; similarity alone is not a reason
to add a cross-skill abstraction.

## Offline validation and limits

Networking was disabled with a separate network namespace for every runtime
probe. UV was explicitly offline. Parser inspection preceded execution so
`--help` could not fall through into a real operation. Existing environments
were reused when dependencies were absent from the registry cache. No package
was downloaded. No credentials were printed and no live endpoint was tested.
Temporary fixtures and caches stayed outside tracked source files.

| Check | Result and limit |
| --- | --- |
| Source coverage | 48 distinct tracked skill files, 48 table rows; symlinks excluded from the count. |
| Metadata | 47 valid complete YAML frontmatters; library fails at line 4, D19. Its description size was decoded independently. |
| Python syntax | AST parsing passed for all 114 repository Python files; no bytecode compilation needed. |
| CLI help | 54 Python help probes: 50 passed, 4 blocked by unavailable offline dependencies. These are environment limits, not proven script defects. |
| Blocked Python help | gemini-vision, nano-banana-image and youtube-frame-analysis lack cached google-genai; kuluttaja lacks cached lxml/BeautifulSoup dependencies. No network retry. |
| Manual parsers | ECB, document converter, transcription, Zed, whitespace cleanup and mailbox shell script have no normal help branch. Inspected instead of treating help as safe. Their runtime dependencies/private inputs were not provisioned. |
| Upstream shell helper | `bash .../submit-pr.sh --help` exits 1 with usage before Git operations. Both bundled shell scripts pass `bash -n`. |
| Android tests | 948 passed, 0 failed with a private temporary filesystem and networking disabled. |
| T3 helper tests | 83 passed, 0 failed using fake ticket/WebSocket transport. No inspect/start/send/settle/resume command reached a server. |
| Reflection plugin tests | 36 passed, 0 failed, included despite not being a skill. |
| Mail-save tests | 32 passed, 0 failed with mocked subprocesses. |
| MCP converter tests | 7 passed, 4 deselected. Selected validation, cleanup and command-shape tests are offline. Generation/integration tests that start configured MCP processes were excluded. The Context7 example test also launches its configured service and was not run. |
| Other skills | No maintained offline test suite found. Help proves argument-parser/import availability only, not service behaviour or correct output. |
| Pandoc/Typst | Minimal local rendering fails without font and passes with DejaVu Serif, D15. No remote template or package was used. |
| Discovery links | Repository symlink checker passes. Existing named references and bundled executable paths resolve except the explicitly identified design-only/missing fallback commands. |
| Topology | The new report contains no forbidden topology strings or absolute home paths. The full repository check already finds 19 matching lines on the reviewed main snapshot in existing tracker/task material. Those pre-existing files were not edited to evade scope. |

There were two preliminary environment failures: the first combined test
collection lacked Typer, and adding it through UV was blocked by the offline
cache. Reusing the repository environment solved mail-save testing. The first
Android run had 50 storage tests fail because the user namespace exposes the
outer temporary-directory owner as an unmapped UID; its other 898 tests and the
119 T3/reflection tests passed. Mounting a private tmpfs for the Android rerun
resolved those 50 failures. Final observed suite coverage is **1,106 unique
passing tests**, with the four MCP integration tests excluded as described.

Reproduction commands, from the repository root. `REVIEW_PYTHON` denotes the
existing repository environment containing pytest, Typer and the MCP SDK.
The UV environment supplies pytest, HTTPX, PyYAML and websocket-client.
`unshare` and a local package cache are prerequisites; the temporary-filesystem
mount changes only the child namespace.

```bash
PYTHONDONTWRITEBYTECODE=1 SHELL=/bin/bash unshare -rn \
  uv run --offline --no-project --with pytest --with httpx \
  --with pyyaml --with websocket-client \
  pytest -p no:cacheprovider android-diagnostics/tests \
  t3-start-thread/tests reflect-extensions/tests -q

PYTHONDONTWRITEBYTECODE=1 SHELL=/bin/bash unshare -rnm bash -c \
  'mount -t tmpfs -o mode=1777 tmpfs /tmp && uv run --offline --no-project --with pytest --with httpx --with pyyaml --with websocket-client pytest -p no:cacheprovider android-diagnostics/tests -q'

PYTHONDONTWRITEBYTECODE=1 SHELL=/bin/bash unshare -rn \
  "$REVIEW_PYTHON" -m pytest -p no:cacheprovider \
  himalaya-email-manager/tests -q

PYTHONDONTWRITEBYTECODE=1 SHELL=/bin/bash unshare -rn \
  "$REVIEW_PYTHON" -m pytest -p no:cacheprovider mcp-to-skill/tests -q \
  -k 'validate_config or cleanup or python_uv_command_structure'

python3 .github/scripts/check_symlinks.py
bash -n email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh \
  upstream-pr/scripts/submit-pr.sh
```

The first command reproduces the namespace ownership limitation on this host;
the second is the passing Android run. For CLI probes, use the same offline
namespace/environment with `python SKILL/scripts/HELPER.py --help`, or
`uv run --offline --no-project --script SKILL/scripts/HELPER.py --help` for
cached PEP 723 dependencies. Use these only for the audited argparse/Typer
entry points, not the manual-parser exceptions above.

External API schemas, model availability, subscription entitlements, browser
selectors, remote deployment paths and command extensions were not validated
against live systems. Command lookup found local Git, gh, UV/UVX, Pandoc,
Typst, ffmpeg, yt-dlp, journalctl, xh, bun and git-knit. It did not find adb,
pdfimages, magick, llm, detect-secrets or secretlint. Their absence does not make
the skills stale; preserve prerequisite checks and do not report an untested
service as unavailable. No draft here assumes a measured invocation frequency
except the T3 usage stated in the task brief.
