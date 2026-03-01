---
name: verkkokauppa
description: >-
  Search products on the Verkkokauppa.com Finnish webshop.
  This skill uses the Verkkokauppa search API directly, requiring no browser.
  Use when the user asks to "search Verkkokauppa", "find products on verkkokauppa.com",
  "verkkokauppa product search", "check Verkkokauppa prices",
  or mentions searching the Verkkokauppa store.
---

# Verkkokauppa.com Product Search

Search the Verkkokauppa.com product catalog using their internal search API.
No browser or authentication required.

## Quick Start

Run the search script to find products:

```bash
./scripts/search.py "näyttö"
./scripts/search.py "kuulokkeet" --limit 20
./scripts/search.py "näytönohjain" --json
./scripts/search.py "kannettava" --sort price
```

## How It Works

The Verkkokauppa.com webshop uses a search backend at `search.service.verkkokauppa.com`.
The search script calls this API directly over HTTPS with JSON responses,
bypassing the need for a browser.

The API requires no authentication — only a random UUID v4 for session tracking.

## Using the Search Script

### Basic search

```bash
./scripts/search.py "search term"
```

Prints a formatted list of up to 10 products with name, brand, price,
category, rating, and product URL.

### JSON output

```bash
./scripts/search.py "search term" --json
```

Outputs the raw API response as JSON for programmatic use.

### Pagination

```bash
./scripts/search.py "search term" --limit 20 --page 2
```

- `--limit N` — Number of results (default: 10)
- `--page N` — Page number, 1-based (default: 1)

### Sorting

```bash
./scripts/search.py "search term" --sort price
```

- `-score` — Relevance (default)
- `price` — Price low to high
- `-price` — Price high to low
- `-popularity` — Most popular
- `-rating` — Highest rated
- `-releaseDate` — Newest
- `-discountPercentage` — Biggest discount

## Programmatic Use

Import the search functions in Python:

```python
from scripts.search import search_products, extract_products

raw = search_products("näyttö", limit=5)
products = extract_products(raw)
for p in products:
    print(p["name"], p.get("price_current", "N/A"))
```

## Key Product Fields

| Field                | Description                        |
|----------------------|------------------------------------|
| `name`               | Product name                       |
| `price_current`      | Current selling price (EUR)        |
| `price_original`     | Original price before discount     |
| `discount_percent`   | Discount percentage                |
| `brand`              | Brand name                         |
| `category`           | Product category                   |
| `rating`             | Average rating                     |
| `review_count`       | Number of reviews                  |
| `url`                | Full product URL                   |
| `image`              | Product image URL (CDN)            |
| `product_id`         | Internal product ID                |

## Image URLs

Images are served via Verkkokauppa CDN with full URLs:

```
https://cdn.verk.net/images/...
```

## API Reference

See `references/api.md` for full API documentation including endpoint details,
all parameters, and response structure.
