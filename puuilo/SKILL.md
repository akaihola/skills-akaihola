---
name: puuilo
description: >-
  Search products on the Puuilo webshop (puuilo.fi).
  This skill uses the Algolia search API with automatic key refresh.
  Use when the user asks to "search Puuilo", "find products on puuilo.fi",
  "puuilo product search", "check Puuilo prices",
  or mentions searching the Puuilo store.
---

# Puuilo Product Search

Search the Puuilo product catalog using their Algolia search API.
The API key is automatically refreshed from the Puuilo search page.

## Quick Start

```bash
./scripts/search.py "suihkusetti"
./scripts/search.py "porakone" --limit 20
./scripts/search.py "maali" --json
./scripts/search.py "työkalu" --sort price_asc
```

## Sort Options

- `relevance` (default)
- `popular` — most popular
- `newest` — newest first
- `price_asc` — cheapest first
- `price_desc` — most expensive first
- `name_asc` / `name_desc` — alphabetical

## Key Product Fields

| Field            | Description                        |
|------------------|------------------------------------|
| `name`           | Product name                       |
| `sku`            | Product SKU                        |
| `price`          | Current price (EUR)                |
| `price_formatted`| Formatted price string             |
| `categories`     | Category hierarchy                 |
| `in_stock`       | Boolean stock status               |
| `url`            | Product page URL                   |

## API Reference

See `references/api.md` for full API documentation.
