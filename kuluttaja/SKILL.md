---
name: kuluttaja
description: >-
  Search and extract articles from kuluttaja.fi (Finnish consumer magazine)
  via the WordPress REST API and custom endpoints. Fast httpx-based, no browser
  required. Public metadata (title, date, excerpt, tags, paywall status) is
  always available; full text for paywalled articles requires browser login.
  Use when the user asks to "search Kuluttaja", "find articles on kuluttaja.fi",
  "extract kuluttaja.fi content", or mentions reading Kuluttaja.
---

# Kuluttaja.fi Article Search & Extraction

Search, discover, and extract article content from kuluttaja.fi using
its native WordPress REST API (`/wp-json/wp/v2/posts`) and custom
endpoints (`/wp-json/kuluttaja/v1/*`).

No browser required for search, metadata extraction, or public articles.

## Quick Start

```bash
# Search articles
./scripts/extract.py --search "kaasugrilli"

# Search with limit
./scripts/extract.py --search "grilli" --limit 5

# Extract single article by post ID
./scripts/extract.py --id 249062

# Extract by slug
./scripts/extract.py --slug puhdista-grillin-ritilat-lampimana

# JSON output
./scripts/extract.py --search "kaasugrilli" --limit 3 --json

# List latest test posts
./scripts/extract.py --latest-tests

# List latest test winners
./scripts/extract.py --test-winners

# Search product reviews
./scripts/extract.py --product-search "grilli"

# List magazine issues
./scripts/extract.py --magazines
```

## How It Works

Kuluttaja.fi runs on WordPress with WooCommerce. The skill uses:

| Endpoint | Purpose | Auth |
|---|---|---|
| `/wp-json/wp/v2/posts?search=<q>` | Article search & metadata | None |
| `/wp-json/wp/v2/posts/<id>` | Single post (full content) | None* |
| `/wp-json/kuluttaja/v1/product-reviews/search` | Product review search | None |
| `/wp-json/kuluttaja/v1/product-reviews/latest-test-winners` | Test winners | None |
| `/wp-json/kuluttaja/v1/test-category-navigation/latest-tests-posts` | Latest tests | None |
| `/wp-json/kuluttaja/v1/magazine/latest` | Magazine issues | None |
| `/wp-json/kuluttaja/v1/black-list/entries` | Musta lista (black list) | None |
| `/wp-json/kuluttaja/v1/test-category-navigation/categories` | Test categories | None |

**\* Paywall note:** The WP REST API returns full `content.rendered` for
public articles, but paywalled articles only return the teaser text.
Full paywalled content requires browser-based login (WooCommerce
Memberships auth, not WP application passwords).

## Paywall vs Public

Articles with `class_list` containing `"access-restricted"` are paywalled.
For these, only the first few paragraphs are available via the REST API.
The Playwright-based fallback (`scripts/extract_browser.py`, legacy)
can extract full content after login.

## Script Usage

### Search + extract to markdown files
```bash
./scripts/extract.py --search "kaasugrilli" --output-dir ./articles
# Saves one .md file per result with title, metadata, and body
```

### Programmatic use
```python
from scripts.extract import (
    search_posts, get_post, get_post_by_slug,
    extract_metadata, extract_body, post_to_markdown,
    product_reviews_search, latest_test_winners,
    latest_tests_posts, magazine_issues,
)

# Search
posts = search_posts("kaasugrilli", limit=5)

# Extract metadata
meta = extract_metadata(posts[0])
print(meta["title"], meta["is_paywalled"], meta["tags"])

# Extract body (teaser for paywalled, full for public)
body = extract_body(posts[0]["content"]["rendered"])

# Full markdown doc
md = post_to_markdown(posts[0])
```

## Key Functions

| Function | Description |
|---|---|
| `search_posts(query, limit)` | Search articles, return WP REST post objects |
| `get_post(id)` | Get single post by ID |
| `extract_metadata(post)` | Extract clean metadata dict from post |
| `extract_body(html)` | Strip paywall + UI noise from content HTML |
| `post_to_markdown(post)` | Convert post dict to markdown |
| `product_reviews_search(q)` | Custom API product review search |
| `latest_test_winners()` | Latest test winner list |
| `latest_tests_posts()` | Latest test posts |
| `magazine_issues()` | Magazine issue listing |

## Metadata Fields

Extracted by `extract_metadata()`:

| Field | Source |
|---|---|
| `id` | WP post ID |
| `title` | Rendered title (HTML-stripped) |
| `slug` | URL slug |
| `link` | Full article URL |
| `date` | Post date (YYYY-MM-DD) |
| `published` | Published date from Yoast schema |
| `author` | Author name from embedded data / Yoast |
| `excerpt` | Rendered excerpt |
| `tags` | Post tag names |
| `categories` | Category IDs |
| `is_paywalled` | Boolean — `"access-restricted"` in class_list |
| `featured_media` | Featured image ID |

## API Reference

See `references/api.md` for full endpoint documentation, response
structure, and DOM/page selectors (for Playwright fallback).
