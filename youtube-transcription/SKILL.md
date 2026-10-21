---
name: YouTube Transcription
description: Transcribe a YouTube URL or local audio file with the paid AssemblyAI service when captions are unavailable or speech-to-text is explicitly requested. Requires ASSEMBLYAI_API_KEY. The bundled script currently fixes the language to English.
version: 0.1.0
---

# YouTube transcription

Resolve [scripts/transcribe_video.py](scripts/transcribe_video.py) from this
skill’s installed directory. Python 3.13+, `assemblyai` and `yt-dlp` are
declared in its PEP 723 metadata; `uv run` supplies them. YouTube extraction
also needs ffmpeg and Firefox cookies accessible to yt-dlp.

```bash
uv run /path/to/youtube-transcription/scripts/transcribe_video.py /path/to/audio.mp3
uv run /path/to/youtube-transcription/scripts/transcribe_video.py "https://youtu.be/VIDEO_ID"
```

Set `ASSEMBLYAI_API_KEY` through the user’s credential mechanism. Check
presence without printing it:

```bash
if [ -n "${ASSEMBLYAI_API_KEY:-}" ]; then
  printf '%s\n' 'ASSEMBLYAI_API_KEY is set'
else
  printf '%s\n' 'ASSEMBLYAI_API_KEY is missing or empty'
fi
```

## Current behaviour

The script takes one positional input and has no option parser. It does not
implement `--help`, language/model/output flags, or a dry run. Do not use
`--help` as a capability probe.

Inputs beginning with `http` enter the yt-dlp download path, with Firefox
cookies and MP3 extraction. Local files go directly to transcription.
The script constructs `TranscriptionConfig(language_code="en")`.

It prints progress and the full transcript to stdout, then overwrites
`/tmp/transcript.txt`. It does not generate Markdown metadata, headings,
timestamps, summaries or speaker sections. Formatting and copying the result
into the requested destination are separate steps. Preserve each result
before another run.

## Limitations

Read [integration limits and extension notes](references/assemblyai_options.md)
before choosing SDK features or handling download failures. The current
download helper selects the newest MP3 from the shared temporary directory,
so the selected file may not belong to this invocation. API-key wiring also
needs verification before claiming the environment variable is sufficient.

No live transcription is implied by loading this skill. Paid service use
must fit the user’s request; current pricing and account limits are not
encoded in this repository.
