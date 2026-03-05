---
name: bauhaus
description: >-
  Search products on the Bauhaus webshop (bauhaus.fi).
  This skill uses the Algolia search API with automatic key refresh.
  Use when the user asks to "search Bauhaus", "find products on bauhaus.fi",
  "bauhaus product search", "check Bauhaus prices",
  or mentions searching the Bauhaus store.
---

# Bauhaus Product Search

Search the Bauhaus product catalog using their Algolia search API.
The API key is automatically refreshed from the Bauhaus search page.

## Quick Start

```bash
./scripts/search.py "suihkusetti"
./scripts/search.py "laminaatti" --limit 20
./scripts/search.py "hana" --json
./scripts/search.py "työkalu" --sort price_asc
```

## Sort Options

- `relevance` (default)
- `price_asc` — cheapest first
- `price_desc` — most expensive first
- `newest` — newest first

## Key Product Fields

| Field            | Description                        |
|------------------|------------------------------------|
| `name`           | Product name                       |
| `brand`          | Brand name                         |
| `sku`            | Product SKU                        |
| `ean`            | EAN barcode                        |
| `price`          | Current price (EUR)                |
| `price_formatted`| Formatted price string             |
| `color`          | Primary color                      |
| `categories`     | Category hierarchy                 |
| `in_stock`       | Boolean stock status               |
| `web_stock`      | Web availability text              |
| `store_stock`    | Store availability text            |
| `url`            | Product page URL                   |

## API Reference

See `references/api.md` for full API documentation.
