---
name: netrauta
description: >-
  Search products on the Netrauta webshop (netrauta.fi).
  This skill uses the Loop54 search API directly, requiring no browser.
  Use when the user asks to "search Netrauta", "find products on netrauta.fi",
  "netrauta product search", "check Netrauta prices",
  or mentions searching the Netrauta store.
---

# Netrauta Product Search

Search the Netrauta product catalog using their Loop54 search API.
No browser or authentication required.

## Quick Start

```bash
./scripts/search.py "suihkusetti"
./scripts/search.py "laminaatti" --limit 20
./scripts/search.py "hana" --json
./scripts/search.py "laatta" --offset 20
```

## Key Product Fields

| Field          | Description                        |
|----------------|------------------------------------|
| `name`         | Product name                       |
| `brand`        | Brand name                         |
| `price`        | Current price (EUR)                |
| `list_price`   | Original price before discount     |
| `availability` | Stock status (1 = in stock)        |
| `product_url`  | Product page URL                   |

## API Reference

See `references/api.md` for full API documentation.
