---
name: k-rauta
description: >-
  Search products on the K-Rauta webshop (k-rauta.fi).
  This skill uses the K-Rauta backend search API directly, requiring no browser.
  Use when the user asks to "search K-Rauta", "find products on k-rauta.fi",
  "k-rauta product search", or mentions searching K-Rauta.
  Note: Prices are not included in search results — check on k-rauta.fi.
---

# K-Rauta Product Search

Search the K-Rauta product catalog using their backend search API.
No browser or authentication required.

**Note:** The K-Rauta search API v1 does not include prices. Users need to check prices on k-rauta.fi.

## Quick Start

```bash
./scripts/search.py "suihkusetti"
./scripts/search.py "laminaatti" --limit 20
./scripts/search.py "hana" --json
```

## Key Product Fields

| Field          | Description                        |
|----------------|------------------------------------|
| `name`         | Product name                       |
| `brand`        | Brand name                         |
| `ean`          | EAN barcode                        |
| `description`  | Product description                |
| `categories`   | Category hierarchy                 |
| `ratings`      | Review score and count             |

## API Reference

See `references/api.md` for full API documentation.
