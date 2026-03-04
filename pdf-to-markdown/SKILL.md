---
name: pdf-to-markdown
description: Convert a PDF book or document into clean, structured Markdown files split by chapter/section, with embedded images. Uses the Gemini Files API for high-quality conversion. Handles hyphenation repair, page-break paragraph joining, and blockquote formatting.
---

# PDF to Markdown

Convert a structured PDF (book, report, manual) into clean Markdown files – one file per section – with images extracted and embedded.

## Requirements

- `GEMINI_API_KEY` environment variable set
- `uv` available

## Usage

### Step 1: Create a config file

Create `config.toml` next to your PDF describing the sections and their page ranges:

```toml
pdf = "MyBook.pdf"
output_dir = "."
images_dir = "images"
model = "gemini-2.0-flash"          # optional, this is the default
rate_limit_sleep = 1.0              # seconds between API calls

[[sections]]
slug = "chapter-1"
start_page = 10
end_page = 53
heading = "# Chapter 1 – Introduction"
output = "chapters/01-introduction.md"

[[sections]]
slug = "chapter-2"
start_page = 54
end_page = 113
heading = "# Chapter 2 – Core Concepts"
output = "chapters/02-core-concepts.md"

[[sections]]
slug = "appendix-1"
start_page = 114
end_page = 121
heading = "# Appendix 1 – Self-Assessment"
output = "appendices/appendix-1.md"
# Optional: extra instructions appended to the prompt for this section
instructions = "Format all quiz questions as numbered lists."
```

**Tips for setting page ranges:**

- Use a PDF viewer that shows physical page numbers (not printed numbers)
- Sections that are too long (>~50 pages) may hit the model's output token limit – split them
- Use `gemini-2.0-flash` (not flash-lite) for long sections

### Step 2: Run the converter

```bash
GEMINI_API_KEY=your-key uv run path/to/convert.py config.toml
```

The script:

1. Extracts all embedded images from the PDF with pymupdf
2. Uploads the PDF once to the Gemini Files API
3. Converts each section with a targeted prompt
4. Fixes remaining hyphenation and page-break artifacts in post-processing
5. Embeds image references at the correct locations
6. Deletes the uploaded file from the API when done

### Output structure

```
./
├── config.toml
├── images/
│   ├── image-01-page11.png
│   └── image-01-page22.png
└── chapters/
    ├── 01-introduction.md
    └── 02-core-concepts.md
```

Image paths in Markdown are relative from each output file to the images directory.

## What Gemini handles well

- Removing page numbers and headers/footers
- Preserving heading hierarchy (##, ###)
- Formatting block quotes (`>`)
- Recognising section structure from visual layout

## Known limitations

- Footnote superscripts (¹ ²) and asterisk references (\*) are reproduced as-is, not linked to their footnote text
- Very long sections (>60 pages) may truncate – split them in config.toml
- Image _placement_ within a section is approximate (Gemini marks [IMAGE page N] which maps to extracted images by page number)
