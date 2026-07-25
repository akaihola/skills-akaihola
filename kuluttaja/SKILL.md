---
name: kuluttaja
description: >-
  Search and extract articles from kuluttaja.fi (Finnish consumer magazine).
  Supports login for paywalled content. Uses Playwright for browser automation.
  Use when the user asks to "search Kuluttaja", "find articles on kuluttaja.fi",
  "extract kuluttaja.fi content", or mentions reading Kuluttaja.
---

# Kuluttaja.fi Article Search & Extraction

Search the Kuluttaja.fi content catalog and extract full article text,
including paywalled content after authenticating.

## Quick Start

```bash
# List search results
./scripts/extract.py --search "kaasugrilli" --limit 5

# Extract a single public article
./scripts/extract.py https://kuluttaja.fi/fi/artikkeli/bauhausin-grilli-polttaa-napit

# Extract with login (for paywalled articles)
KULUTTAJA_EMAIL=user@example.com KULUTTAJA_PASSWORD=secret \
    ./scripts/extract.py --search "kaasugrilli" --limit 3
```

## How It Works

Kuluttaja.fi is a Next.js-based site with no public REST API for content
discovery. The extract script uses Playwright (headless Chromium) to:

1. Navigate to the homepage
2. Use the built-in search box (in header) to search
3. Parse article results from `<article>` elements
4. Visit each article page and extract content from the main body
5. For paywalled articles: log in first via the "Kirjaudu" header link

Login credentials are read from `KULUTTAJA_EMAIL` and `KULUTTAJA_PASSWORD`
environment variables. Never hard-code them.

## Login Flow (reverse-engineered)

The login UI is reached by clicking "KIRJAUDU" in the site header:

1. Form fields identified by `role="textbox"` labels:
   - "SÄHKÖPOSTIOSOITE" — email
   - "SALASANA" — password
2. "PIDÄ MINUT KIRJAUTUNEENA" checkbox (optional)
3. "Kirjaudu sisään" button — submits
4. After success: header shows "KIRJAUDU ULOS" and "Oma tili"

## Search Flow

1. Header search box: `input[placeholder="Haku"]` → fill + Enter
2. Results page shows `<article>` elements with:
   - `<h4>` title + link
   - Date string (e.g., "18.06.2026")
   - Snippet excerpt
3. Radio filters: KAIKKI / TESTIT / ARTIKKELIT / MUUT
4. "LATAA LISÄÄ" button for pagination

## Article Content

Article pages use a standard layout:
- `h1` — title
- `JULKAISTU:` — publish date
- `KIRJOITTAJA:` — author name
- `<main>` — body content (`<p>`, `<h2>`–`<h4>`, `<li>`, `<figure>`)
- Tags listed as paragraphs at the bottom
- Paywalled articles show "Jatka lukemista" / "Osta pääsy" prompt
- "Näytä lisää" expandable sections need to be clicked

## Script Usage

### Search only
```bash
./scripts/extract.py --search "grilli" --limit 5
# Output: formatted result list to stdout, no file writes
```

### Search + extract
```bash
KULUTTAJA_EMAIL=... KULUTTAJA_PASSWORD=... \
    ./scripts/extract.py --search "kaasugrilli" \
    --output-dir ./articles
```

### Single URL extraction
```bash
./scripts/extract.py https://kuluttaja.fi/fi/artikkeli/...
```

### Multiple URLs from file
```bash
./scripts/extract.py --file urls.txt --output-dir ./articles
```

### JSON output (search results)
```bash
./scripts/extract.py --search "grilli" --limit 5 --json
```

### JSON output (extracted articles)
```bash
KULUTTAJA_EMAIL=... KULUTTAJA_PASSWORD=... \
    ./scripts/extract.py --search "grilli" --limit 2 --json
```

## Programmatic Use

```python
from scripts.extract import search, extract_article, article_to_markdown

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_context().new_page()

    # Search
    results = search(page, "kaasugrilli", limit=5)

    # Extract (logged in)
    article = extract_article(page, results[0]["url"], logged_in=True)
    md = article_to_markdown(article)

    browser.close()
```

## Key Functions

| Function            | Description                                   |
|----------------------|-----------------------------------------------|
| `search(page, q)`   | Search articles, return list of dicts           |
| `extract_article()`  | Extract article content as dict                 |
| `login(page, e, p)`  | Authenticate to kuluttaja.fi                    |
| `article_to_md()`    | Convert extracted article dict to markdown      |

## Key Article Fields

| Field        | Description                              |
|--------------|------------------------------------------|
| `title`      | Article title (from <h1>)               |
| `author`     | Author name                             |
| `published`  | Publication date                         |
| `url`        | Full article URL                        |
| `paywalled`  | Boolean — content behind login wall      |
| `body`       | Extracted body text (markdown-ish)       |

## Search Result Fields

| Field       | Description                              |
|-------------|------------------------------------------|
| `title`     | Article title                            |
| `url`       | Full article URL                        |
| `date`      | Published date string                   |
| `snippet`   | Excerpt text                             |

## API Reference

See `references/api.md` for selectors, login flow, and page structure details.
