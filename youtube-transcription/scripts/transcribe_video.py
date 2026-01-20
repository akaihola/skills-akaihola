#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = ["assemblyai", "yt-dlp"]
# ///
"""Transcribe YouTube video using AssemblyAI."""

import sys
import os
from pathlib import Path
import subprocess
import json
from assemblyai import Transcriber, TranscriptionConfig, Settings


def get_youtube_audio(youtube_url: str) -> str:
    """Download audio from YouTube video and return path to audio file."""
    output_path = Path("/tmp/youtube_audio.mp3")

    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format",
        "mp3",
        "--cookies-from-browser",
        "firefox",
        "-o",
        str(output_path.with_name("%(id)s.%(ext)s")),
        youtube_url,
    ]

    print(f"Downloading audio from {youtube_url}...")
    print("(Using Firefox cookies for authentication)")
    subprocess.run(cmd, check=True)

    audio_files = list(Path("/tmp").glob("*.mp3"))
    if audio_files:
        actual_file = sorted(audio_files, key=lambda x: x.stat().st_mtime)[-1]
        return str(actual_file)

    raise FileNotFoundError("No audio file found after download")


def transcribe_with_assemblyai(audio_path: str, api_key: str) -> str:
    """Transcribe audio using AssemblyAI API."""
    settings = Settings(api_key=api_key)
    config = TranscriptionConfig(language_code="en")
    transcriber = Transcriber(config=config)

    print(f"Transcribing... (this may take a few minutes)")
    transcript = transcriber.transcribe(audio_path)

    if transcript.status == "error":
        raise Exception(f"Transcription failed: {transcript.error}")

    return transcript.text


def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Usage: transcribe_video.py <youtube_url_or_local_file>")
        sys.exit(1)

    input_arg = sys.argv[1]

    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        print("Error: ASSEMBLYAI_API_KEY environment variable not set")
        sys.exit(1)

    try:
        if input_arg.startswith("http"):
            audio_path = get_youtube_audio(input_arg)
            print(f"Audio saved to: {audio_path}")
        else:
            audio_path = input_arg
            if not Path(audio_path).exists():
                print(f"Error: File not found: {audio_path}")
                sys.exit(1)
            print(f"Using local file: {audio_path}")

        # Transcribe
        transcript = transcribe_with_assemblyai(audio_path, api_key)

        # Print transcript
        print("\n" + "=" * 80)
        print("TRANSCRIPT")
        print("=" * 80 + "\n")
        print(transcript)

        # Save to file
        output_file = Path("/tmp/transcript.txt")
        output_file.write_text(transcript)
        print(f"\n\nTranscript saved to: {output_file}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
