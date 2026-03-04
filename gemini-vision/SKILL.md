---
name: gemini-vision
description: >
  Analyse one or more images with Gemini's vision model – describe contents,
  answer questions, extract text (OCR), compare images, or analyse
  charts/screenshots/diagrams. Requires GEMINI_API_KEY environment variable.
  Use when the user asks to look at, analyse, describe, read, or compare images.
---

# Gemini Vision

Analyse images with Gemini's vision capabilities. Pass one or more images and
a prompt; the model returns a detailed text answer.

## Requirements

- `GEMINI_API_KEY` environment variable set
- `uv` available

## Quick usage

```bash
# Describe an image
uv run ~/.claude/skills/gemini-vision/scripts/gemini_vision.py \
  "Describe this image in detail." \
  photo.jpg

# Answer a specific question about an image
uv run ~/.claude/skills/gemini-vision/scripts/gemini_vision.py \
  "What text is visible in this screenshot?" \
  screenshot.png

# Compare two images
uv run ~/.claude/skills/gemini-vision/scripts/gemini_vision.py \
  "What are the differences between these two images?" \
  before.png after.png

# Extract structured data from a chart or table
uv run ~/.claude/skills/gemini-vision/scripts/gemini_vision.py \
  "Extract all values from this bar chart as a Markdown table." \
  chart.png

# Control the model and output format
uv run ~/.claude/skills/gemini-vision/scripts/gemini_vision.py \
  "List every product name and price visible in this photo." \
  --model gemini-2.5-flash \
  shelf.jpg
```

## Options

| Flag           | Default            | Description                 |
| -------------- | ------------------ | --------------------------- |
| `--model`      | `gemini-2.0-flash` | Gemini model to use         |
| `--max-tokens` | `4096`             | Maximum output tokens       |
| `--system`     | _(none)_           | Optional system instruction |

## Supported image formats

JPEG, PNG, GIF, WEBP, BMP, TIFF, PDF pages (single-page PDFs work as images).

The script auto-detects MIME type from the file content (not the extension).

## Common prompts

| Goal                   | Example prompt                                                 |
| ---------------------- | -------------------------------------------------------------- |
| General description    | `"Describe this image in detail."`                             |
| OCR / text extraction  | `"Extract all text visible in this image."`                    |
| Chart / graph data     | `"Convert this chart to a Markdown table."`                    |
| Diagram explanation    | `"Explain the architecture shown in this diagram."`            |
| Accessibility alt-text | `"Write a concise alt-text for this image."`                   |
| Comparison             | `"Compare these two images and list the differences."`         |
| Receipt / invoice      | `"List every line item, quantity, and price in this receipt."` |
| UI screenshot          | `"Describe the UI elements and layout in this screenshot."`    |

## SDK notes

Uses the **new** `google-genai` package (not the deprecated `google-generativeai`):

```python
# ✅ Correct
import google.genai as genai
from google.genai import types

# ❌ Deprecated
import google.generativeai as genai
```

Multiple images are passed as a list; the model sees them in order:

```python
contents = [
    types.Part.from_bytes(data=img1_bytes, mime_type="image/jpeg"),
    types.Part.from_bytes(data=img2_bytes, mime_type="image/png"),
    "Your prompt here",
]
response = client.models.generate_content(model=model, contents=contents)
print(response.text)
```
