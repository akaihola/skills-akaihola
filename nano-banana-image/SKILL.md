---
name: nano-banana-image
description: >
  Edit or generate images using Nano Banana Pro (Google's gemini-3-pro-image-preview model).
  Use when the user asks to edit, translate, recreate, or generate an image using AI.
  Requires GEMINI_API_KEY environment variable.
---

# Nano Banana Image Editing

Edit existing images or generate new ones using **Nano Banana Pro** (`gemini-3-pro-image-preview`).

## Model names

| Display name    | API model name                      |
| --------------- | ----------------------------------- |
| Nano Banana     | `models/gemini-2.5-flash-image`     |
| Nano Banana Pro | `models/gemini-3-pro-image-preview` |

List all available models:

```bash
uvx --from google-genai python3 -c "
import google.genai as genai, os
client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
for m in client.models.list():
    print(m.name, '-', m.display_name)
"
```

## Quick usage

```bash
# Edit an existing image
~/.claude/skills/nano-banana-image/scripts/nano_banana_edit.py \
  "Your prompt here" \
  --input path/to/input.jpg \
  --output path/to/output.png

# Generate a new image from scratch
~/.claude/skills/nano-banana-image/scripts/nano_banana_edit.py \
  "Your prompt here" \
  --output path/to/output.png
```

## SDK — critical rules

Use the **new** `google-genai` package (not the deprecated `google-generativeai`):

```python
# /// script
# dependencies = ["google-genai", "Pillow"]
# ///
import google.genai as genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="models/gemini-3-pro-image-preview",
    contents=[
        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
        "Your prompt",
    ],
    config=types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
    ),
)

# Extract the image from the response
for part in response.candidates[0].content.parts:
    if part.inline_data and part.inline_data.mime_type.startswith("image/"):
        raw_bytes = part.inline_data.data
        break
```

## ⚠️ Critical gotcha: API returns JPEG even for PNG outputs

The API returns JPEG-encoded bytes regardless of what output format you want.
**Always re-save through Pillow** to get a correctly formatted PNG:

```python
from PIL import Image
import io

img = Image.open(io.BytesIO(raw_bytes))
img.save(Path("output.png"), format="PNG")
# Pillow detects the actual format (JPEG) and re-encodes as PNG
```

If you skip this step and just write the raw bytes to a `.png` file,
the file will contain JPEG data with a PNG extension — GIMP and other
tools will report it as corrupted.

## ⚠️ Do not use `response_mime_type`

The old `google-generativeai` SDK's `response_mime_type` parameter is not supported
for image models — it only accepts `text/plain` etc. Use `response_modalities` instead:

```python
# ❌ Wrong — causes INVALID_ARGUMENT error
config={"response_mime_type": "image/png"}

# ✅ Correct
config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
```

## ⚠️ Use `google-genai`, not `google-generativeai`

```python
# ❌ Deprecated — does not support image generation properly
import google.generativeai as genai

# ✅ Current SDK
import google.genai as genai
from google.genai import types
```
