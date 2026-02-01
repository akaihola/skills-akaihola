---
name: power
description: >-
  Search products on the Power webshop (power.fi).
  This skill uses the Power.fi REST API directly, requiring no browser.
  Use when the user asks to "search Power", "find products on power.fi",
  "power product search", "check Power prices",
  or mentions searching the Power store.
---

# Power.fi Product Search

Search the Power.fi product catalog using their internal REST API.
No browser or authentication required.

## Quick Start

Run the search script to find products:

```bash
./scripts/search.py "kahvinkeitin"
./scripts/search.py "televisio" --limit 20
./scripts/search.py "kuulokkeet" --json
./scripts/search.py "pölynimuri" --sort lth
```

## How It Works

The Power webshop at `power.fi` has a JSON REST API for product listings. The
search script calls this API directly over HTTPS, bypassing the need for a
browser.

The API requires no authentication.

## Using the Search Script

### Basic search

```bash
./scripts/search.py "search term"
```

Prints a formatted list of up to 10 products with name, brand, price, stock,
rating, category, barcode, and product URL.

### JSON output

```bash
./scripts/search.py "search term" --json
```

Outputs the raw API response as JSON for programmatic use.

### Pagination

```bash
./scripts/search.py "search term" --limit 20 --offset 10
```

- `--limit N` — Number of results (default: 10)
- `--offset N` — Starting position, 0-based (default: 0)

### Sorting

```bash
./scripts/search.py "search term" --sort lth
```

- `rel` — Relevance (default)
- `lth` — Price low to high
- `htl` — Price high to low
- `az` — Name A–Z
- `za` — Name Z–A

## Programmatic Use

Import the search functions in Python:

```python
from scripts.search import search_products, extract_products

raw = search_products("kahvinkeitin", limit=5)
products = extract_products(raw)
for p in products:
    print(p["title"], p.get("price", "N/A"))
```

## Key Product Fields

| Field              | Description                                                      |
| ------------------ | ---------------------------------------------------------------- |
| `title`            | Product name                                                     |
| `manufacturerName` | Brand / manufacturer                                             |
| `price`            | Current price (EUR, incl. VAT)                                   |
| `previousPrice`    | Previous price before discount                                   |
| `vatlessPrice`     | Price excluding VAT                                              |
| `categoryName`     | Product category                                                 |
| `stockCount`       | Online stock count                                               |
| `storesStockCount` | Total physical store stock                                       |
| `barcode`          | EAN / GTIN barcode                                               |
| `url`              | Relative product URL (prefix `https://www.power.fi`)             |
| `productReview`    | Object with `overallAverageRating` and `overallTotalReviewCount` |
| `productImage`     | Object with `basePath` and `variants[]`                          |

## Image URLs

Images use the pattern:

```
https://www.power.fi{basePath}/{filename}
```

where `basePath` and `filename` come from the `productImage` field.

## API Reference

See `references/api.md` for full API documentation including endpoint details,
all parameters, and response structure.
