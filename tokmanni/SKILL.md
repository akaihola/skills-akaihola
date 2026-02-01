---
name: tokmanni
description: >-
  Search products on the Tokmanni webshop (tokmanni.fi).
  This skill uses the Klevu search API directly, requiring no browser.
  Use when the user asks to "search Tokmanni", "find products on tokmanni.fi",
  "tokmanni product search", "check Tokmanni prices",
  or mentions searching the Tokmanni store.
---

# Tokmanni Product Search

Search the Tokmanni product catalog using their internal Klevu REST API.
No browser or authentication required.

## Quick Start

Run the search script to find products:

```bash
./scripts/search.py "taskulamppu"
./scripts/search.py "pesuaine" --limit 20
./scripts/search.py "porakone" --json
./scripts/search.py "kahvinkeitin" --sort lth
```

## How It Works

The Tokmanni webshop at `tokmanni.fi` uses a Klevu search backend. The search
script calls this API directly over HTTPS with JSON responses, bypassing the
need for a browser.

The API requires no authentication — only a public API key embedded in the
Tokmanni website frontend.

## Using the Search Script

### Basic search

```bash
./scripts/search.py "search term"
```

Prints a formatted list of up to 10 products with name, brand, price, stock
status, category, SKU, and product URL.

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

## Programmatic Use

Import the search functions in Python:

```python
from scripts.search import search_products, extract_products

raw = search_products("lamppu", limit=5)
products = extract_products(raw)
for p in products:
    print(p["name"], p.get("salePrice", "N/A"))
```

## Key Product Fields

| Field              | Description                        |
|--------------------|------------------------------------|
| `name`             | Product name                       |
| `salePrice`        | Current selling price (EUR)        |
| `oldPrice`         | Original price before discount     |
| `item_brand_name`  | Brand name                         |
| `category`         | Product category                   |
| `sku`              | Product SKU / EAN code             |
| `inStock`          | Stock status (`"yes"` / `"no"`)    |
| `url`              | Full product URL                   |
| `cloudinary_image` | Product image URL (Cloudinary)     |

## Image URLs

Images are served via Cloudinary with full URLs in the `cloudinary_image` field:

```
https://res.cloudinary.com/tokmanni/image/upload/c_pad,b_white,f_auto,h_328,w_328/d_default.png/{sku}.jpg
```

## API Reference

See `references/api.md` for full API documentation including endpoint details,
all parameters, and response structure.
