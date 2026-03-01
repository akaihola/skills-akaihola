---
name: motonet
description: >-
  Search products on the Motonet webshop (motonet.fi).
  This skill uses the Motonet search API directly, requiring no browser.
  Use when the user asks to "search Motonet", "find products on motonet.fi",
  "motonet product search", "check Motonet prices",
  or mentions searching the Motonet store.
---

# Motonet Product Search

Search the Motonet product catalog using their internal search API.
No browser or authentication required.

## Quick Start

Run the search script to find products:

```bash
./scripts/search.py "akku"
./scripts/search.py "öljynsuodatin" --limit 20
./scripts/search.py "perävaunu" --json
./scripts/search.py "jarrupalat" --page 2
```

## How It Works

The Motonet webshop at `motonet.fi` uses a Next.js backend with an internal
search API. The search script calls this API directly over HTTPS with JSON
responses, bypassing the need for a browser.

The API requires no authentication.

## Using the Search Script

### Basic search

```bash
./scripts/search.py "search term"
```

Prints a formatted list of up to 10 products with name, brand, price,
category, product code, and product URL.

### JSON output

```bash
./scripts/search.py "search term" --json
```

Outputs the raw API response as JSON for programmatic use.

### Pagination

```bash
./scripts/search.py "search term" --limit 20 --page 2
```

- `--limit N` — Number of results (default: 10, max: 30)
- `--page N` — Page number, 1-based (default: 1)

Note: The API enforces a maximum page size of 30 results.

## Programmatic Use

Import the search functions in Python:

```python
from scripts.search import search_products, extract_products

raw = search_products("akku", limit=5)
products = extract_products(raw)
for p in products:
    print(p["name"], p.get("price", "N/A"))
```

## Key Product Fields

| Field          | Description                        |
|----------------|------------------------------------|
| `id`           | Product code (e.g. "90-9512")      |
| `name`         | Product name                       |
| `price`        | Current price (EUR, as string)     |
| `brand`        | Brand name                         |
| `categoryName` | Product category                   |
| `categoryUrl`  | Category page URL                  |
| `description`  | Product description                |
| `webshopOnly`  | Whether only available online      |
| `url`          | Full product URL on motonet.fi     |

## Image URLs

Product images are served via the Broman Group CDN:

```
https://cdn.broman.group/api/image/v1/image/{hash}.{slug}.jpg
```

Product detail pages include images but the search API returns only basic
product data.

## API Reference

See `references/api.md` for full API documentation including endpoint details,
all parameters, and response structure.
