---
name: power
description: >-
  Search products on the Power webshop (power.fi).
  This skill uses the Power.fi REST API directly, requiring no browser.
  Use when the user asks to "search Power", "find products on power.fi",
  "power product search", "check Power prices",
  or mentions searching the Power store.
---

# Power.fi Product Search & Store Stock

Search the Power.fi product catalog and check per-store stock using their
internal REST API. No browser or authentication required.

## Quick Start

Search for products:

```bash
./scripts/search.py "kahvinkeitin"
./scripts/search.py "televisio" --limit 20
./scripts/search.py "kuulokkeet" --json
./scripts/search.py "pölynimuri" --sort lth
```

Check store stock for a product:

```bash
./scripts/store_stock.py 3060434
./scripts/store_stock.py 3060434 --postal-code 33100
./scripts/store_stock.py 3060434 --store "Itis"
./scripts/store_stock.py 3060434 --in-stock --json
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

## Store Stock Lookup

Check per-store availability for a specific product using its product ID
(found in search results or product URLs).

### Basic usage

```bash
./scripts/store_stock.py PRODUCT_ID
```

Shows all stores sorted by distance from Helsinki (postal code 00100).

### Options

- `--postal-code CODE` — Sort by distance from a postal code (default: 00100)
- `--store NAME` — Filter by store name (case-insensitive substring)
- `--in-stock` — Show only stores with stock > 0
- `--json` — Output raw JSON

### Programmatic use

```python
from scripts.store_stock import get_store_stock

stores = get_store_stock(3060434, postal_code="33100")
for s in stores:
    print(s["name"], s["storeStockCount"])
```

### Key Store Fields

| Field               | Description                                    |
| ------------------- | ---------------------------------------------- |
| `storeId`           | Unique store identifier                        |
| `name`              | Store name (e.g. "POWER Itis Helsinki")        |
| `address`           | Street address                                 |
| `city`              | City                                           |
| `storeStockCount`   | Number of units in stock at this store         |
| `storeDisplayStock` | Display stock count                            |
| `storeAvailability` | 0 = not available, 1 = low stock, 2 = in stock |
| `clickNCollect`     | Whether click & collect is available           |
| `distance`          | Distance in km from the given postal code      |
| `workingSchedule`   | Array of opening hours per day                 |

## API Reference

See `references/api.md` for full API documentation including endpoint details,
all parameters, and response structure.
