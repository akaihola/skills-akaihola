# Transcription integration and extension notes

The bundled [youtube-transcription/scripts/transcribe_video.py] exposes only
one positional input. The SDK features previously listed here are not
implemented CLI options, and their availability or pricing cannot be inferred
from this script.

## What the code configures

`transcribe_with_assemblyai()` constructs
`TranscriptionConfig(language_code="en")`, then
`Transcriber(config=config)`. It returns only `transcript.text`.
There is no language detection, diarization, entity extraction, moderation,
sentiment analysis, chapters, summaries, webhook, vocabulary or PII-redaction
configuration in the wrapper.

The function creates a local `Settings(api_key=api_key)` object but does not
pass it to `Transcriber` or assign it to module-level SDK settings. Whether
the installed SDK picks up the environment independently remains unverified.
Do not present that local object as proof of working authentication.

**Proposed follow-up:** wire credentials through the supported SDK interface,
add an offline assertion for that wiring, and expose explicit language/output
options before documenting additional features. Check the installed SDK and
current service documentation when implementing them.

## Download and output limitations

`get_youtube_audio()` runs yt-dlp with MP3 extraction and Firefox cookies.
It writes an ID-based filename under the shared temporary directory, then
chooses the newest MP3 from that directory without tying it to the current
download. Concurrent or stale files can select the wrong audio.

The output is plain text in `/tmp/transcript.txt`, overwritten on each run.
There is no per-run output directory, cleanup or batch command.
A shell loop must preserve each transcript before the next invocation.

Authentication failures should be diagnosed without printing API keys or
browser cookies. The script does not supply alternative cookie browsers,
JavaScript runtimes or download flags; changing those requires separate work.

## Unsupported claims removed

The repository does not establish current service prices, free-tier quotas,
per-feature surcharges or comparative language accuracy. It also does not
validate combinations of advanced SDK features. Do not use the former example
percentages or constructor snippets as an operational contract.

There is no safe `--help` branch. Source inspection can establish these
limitations without contacting YouTube or AssemblyAI.

[youtube-transcription/scripts/transcribe_video.py]: ../scripts/transcribe_video.py
