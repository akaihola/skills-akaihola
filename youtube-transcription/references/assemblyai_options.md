# AssemblyAI Advanced Options Reference

Extended configuration options for the transcription script.

## TranscriptionConfig Parameters

The `TranscriptionConfig` class accepts these parameters:

### Basic Options

```python
TranscriptionConfig(
    language_code="en",              # Language of audio (default: auto-detect)
    language_confidence_threshold=0.5  # Minimum confidence for language detection
)
```

### Speaker Identification

```python
TranscriptionConfig(
    speaker_labels=True,              # Identify and label different speakers
    speakers_expected=2                # Expected number of speakers (optional)
)
```

Output includes `[SPEAKER A]:` and `[SPEAKER B]:` labels in transcript.

### Entity Detection

```python
TranscriptionConfig(
    entity_detection=True              # Identify people, places, organizations, etc.
)
```

Returns a list of detected entities with confidence scores.

### Content Moderation

```python
TranscriptionConfig(
    content_safety=True                # Flag potentially unsafe content
)
```

Flags explicit content (profanity, violence, etc.) in transcript.

### Sentiment Analysis

```python
TranscriptionConfig(
    sentiment_analysis=True            # Analyze sentiment per sentence
)
```

Returns sentiment scores (positive, negative, neutral) for each sentence.

### Auto Chapters

```python
TranscriptionConfig(
    auto_chapters=True                 # Generate chapter headings
)
```

Automatically creates sections/chapters from the transcript.

### Summarization

```python
TranscriptionConfig(
    summarization=True,
    summary_type="bullets"             # "bullets", "gist", or "headline"
)
```

Generates automatic summaries of the transcript.

## Usage Example

```python
from assemblyai import Transcriber, TranscriptionConfig

config = TranscriptionConfig(
    language_code="en",
    speaker_labels=True,
    entity_detection=True,
    auto_chapters=True,
    summarization=True,
    summary_type="bullets"
)

transcriber = Transcriber(config=config)
transcript = transcriber.transcribe("audio.mp3")

# Access results
print(f"Text: {transcript.text}")
print(f"Entities: {transcript.entities}")
print(f"Summary: {transcript.summary}")
print(f"Chapters: {transcript.chapters}")
```

## Webhook Integration

For long transcriptions, use webhooks to get notified when complete:

```python
config = TranscriptionConfig(
    webhook_url="https://your-domain.com/transcription-webhook",
    webhook_auth_header_value="your-secret-key"
)
```

AssemblyAI will POST to your webhook when transcription completes.

## Cost Implications

- **Base transcription:** ~$0.60-1.00/hour
- **Speaker labels:** +20% cost
- **Entity detection:** +5% cost
- **Auto chapters:** +10% cost
- **Summarization:** +5% cost

Example: 1-hour video with all options = ~$1.40

## Supported Languages

- English (en)
- Spanish (es)
- French (fr)
- German (de)
- Italian (it)
- Portuguese (pt)
- Dutch (nl)
- And many more

Check https://www.assemblyai.com/docs/concepts/supported-languages for full list.

## Custom Vocabulary

Improve accuracy for domain-specific terms:

```python
config = TranscriptionConfig(
    word_boost=[
        {"word": "Obsidian", "boost": 1.5},
        {"word": "Zapier", "boost": 1.5},
        {"word": "Claude", "boost": 1.5}
    ]
)
```

Boosts recognition of these words (values 1.0-2.0).

## Redaction Options

Remove sensitive information from transcript:

```python
config = TranscriptionConfig(
    redact_pii=True,                   # Redact personally identifiable info
    redact_pii_policies=[
        "credit_card",
        "ssn",
        "phone_number",
        "email_address"
    ]
)
```

Replaces detected PII with `[REDACTED]`.

## Testing & Debugging

Check transcription status and errors:

```python
if transcript.status == "error":
    print(f"Transcription failed: {transcript.error}")
else:
    print(f"Confidence: {transcript.confidence}")
    print(f"Words: {len(transcript.words)}")
    print(f"Duration: {transcript.duration}s")
```

## Performance Tips

1. **Batch processing:** Upload multiple files in sequence with rate limiting
2. **Check costs:** Monitor usage at https://www.assemblyai.com/dashboard
3. **Test first:** Start with basic transcription, add features as needed
4. **Use webhooks:** For long videos (>2 hours), use async webhooks instead of polling
