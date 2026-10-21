# Review every skill for stale instructions, weak triggers and token cost, and draft the fixes

Steward issue, 2026-10-19 (spare quota, steward decisions D48 and D53:
quality, tokens per unit of work, and review of docs and instructions).
Goal: agentic-leverage; skills-akaihola is tier 2. It took 47 commits in the
last week and has never had a whole-repository review. Agents read these
skills' descriptions in every session and load a SKILL.md whenever one
matches: a vague description loads the wrong skill or misses the right one,
and a long SKILL.md costs tokens on every load. `t3-start-thread`, which the
steward uses on every run, lives here.

## Work

1. List every skill with the length of its description and SKILL.md and
   the references it loads.
2. For each skill, check: does the description say concretely when to use
   it, and when not? Is SKILL.md short, with details behind links? Do the
   commands, paths and scripts it names still exist, and do the scripts'
   `--help` and offline tests run? Does it duplicate another skill?
3. Apply `honey-review` to the scripts (dead code, single-caller
   abstractions, hand-rolled stdlib) and `writing-for-agents` to the
   instructions.
4. Write `docs/reviews/2026-10-19-skills-review.md`: a table of every
   skill, then findings ranked by benefit per hour, each with file and line
   evidence and a drafted issue (title, work, acceptance, about an agent
   hour each). Mark drafts that overlap open issues in `TASKS.md` instead of
   duplicating them.

## Ground rules

- Read-only apart from the report and this issue's tracker moves. Don't
  file the drafts; the steward files them.
- Run nothing that sends a message, starts or settles a thread, or reaches
  the network.
- No host names or private home paths in any file: the topology check
  rejects them.

## Acceptance

- Every skill appears in the report's table.
- Every finding cites a file and line on `main` and says what changes if it
  is fixed.
- The report names the three drafts it would do first, and why.

## Follow-up verification, 2026-10-21

The four dependency-blocked help probes in the [review report]'s
"Offline validation and limits" section now pass. This follow-up implements
[the help-probe task]; it does not change the original review's historical
results or validate live services.

Dependencies were installed in a disposable Python 3.14.7 environment with
`uv venv` and `uv pip install`: `google-genai==2.32.0`, `Pillow==13.0.0`,
`httpx==0.28.1`, `beautifulsoup4==4.15.0`, and `lxml==6.1.3`.
Only dependency provisioning used networking. Each script ran sequentially
using the environment's Python under `unshare -Urn`, with a fresh temporary
home and an allowlisted environment containing no credentials. Source
inspection confirmed that argument parsing precedes client creation, file
processing, downloads and requests. No private database, mailbox, model call
or external message was used.

- **Gemini vision:** [the vision helper] with `--help` exited 0, with usage,
  positional prompt/images and model/token/system options; stderr empty.
- **Nano Banana image:** [the image helper] with `--help` exited 0, with usage,
  prompt and input/output/model options; stderr empty. Help bypasses the
  required output argument without generating or writing an image.
- **YouTube frame analysis:** [the frame helper] with `--help` exited 0, with
  usage, URL and threshold/frame/prompt/model/format/time options; stderr
  empty. No video download, ffmpeg operation or model call occurred.
- **Kuluttaja:** [the extraction helper] with `--help` exited 0, with usage,
  search/article/listing and output options; stderr empty. No article request
  or output directory creation occurred.

All four outputs were checked for both `usage:` and `--help`. No help path
among these four remains unsupported. No script changes were necessary.

### Manual-parser limitations

The review's manual-parser exceptions were inspected, not executed:

- **Whitespace cleanup:** [the whitespace helper]'s `main` recognizes only
  `--dry-run`; `--help` becomes a working directory before Git operations.
- **PDF conversion:** [the converter]'s `main` treats the first argument as
  a TOML configuration path, then processes files and uploads the PDF.
- **Transcription:** [the transcription helper]'s `main` treats the first
  argument as a URL or local audio path and proceeds toward transcription
  when credentials are available. There is no help branch.
- **Zed threads:** [the Zed helper] reads the database before inspecting the
  index and `--no-color` arguments; it has no help branch.
- **Mailbox analysis:** [the mailbox helper] calls `main` unconditionally;
  it has no option parser and reads profile configuration before mailbox work.
- **ECB rates:** [the rates helper] has since gained argparse in the
  [completed CLI repair]. Source inspection confirms parsing precedes the
  fetch. The original review's unsupported-help finding is historical;
  this helper is outside the four dependency-blocked probes.

### Resource checks

Each command had a 300-second limit, ran alone, and was monitored for
available memory below 1024 MiB or swap growth above 512 MiB. All were
**started at once**, with 0-second admission waits and exit code 0. Values
below are MiB; swap growth is the maximum observed increase during the run.

- **uv venv:** available 3318.1 at admission, 3322.6 final; starting swap
  2123.0, growth 0.0; elapsed 0.20 seconds.
- **uv pip install:** available 3322.6 at admission, 3302.8 final; starting
  swap 2123.0, growth 0.0; elapsed 4.62 seconds.
- **Gemini vision help:** available 3303.0 at admission, 3311.9 final;
  starting swap 2123.0, growth 0.0; elapsed 2.41 seconds.
- **Nano Banana help:** available 3311.9 at admission, 3335.8 final;
  starting swap 2123.0, growth 0.0; elapsed 2.22 seconds.
- **YouTube frame help:** available 3335.8 at admission, 3332.4 final;
  starting swap 2123.0, growth 0.0; elapsed 3.41 seconds.
- **Kuluttaja help:** available 3332.4 at admission, 3337.9 final;
  starting swap 2123.0, growth 0.0; elapsed 0.80 seconds.

[review report]: ../reviews/2026-10-19-skills-review.md
[the help-probe task]: 17-run-the-four-safe-help-probes-the-skill-review-could-not-run.md
[the vision helper]: ../../gemini-vision/scripts/gemini_vision.py
[the image helper]: ../../nano-banana-image/scripts/nano_banana_edit.py
[the frame helper]: ../../youtube-frame-analysis/scripts/yt_frame_analysis.py
[the extraction helper]: ../../kuluttaja/scripts/extract.py
[the whitespace helper]: ../../discard-whitespace-hunks/scripts/discard_ws_hunks.py
[the converter]: ../../pdf-to-markdown/scripts/convert.py
[the transcription helper]: ../../youtube-transcription/scripts/transcribe_video.py
[the Zed helper]: ../../zed-threads/scripts/read_zed_threads.py
[the mailbox helper]: ../../email-mailbox-analyzer/scripts/email-mailbox-analyzer.sh
[the rates helper]: ../../ecb-rates/fetch_ecb_rates.py
[completed CLI repair]: 13-fix-the-skills-review-s-next-three-library-argument-hint-asana-discove.md
