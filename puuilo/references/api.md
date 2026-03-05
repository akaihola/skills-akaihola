# Puuilo – Algolia Search API

The Puuilo webshop uses **Algolia** as its search backend.

## Authentication

The Algolia API key is **not static** – it is embedded in the HTML of the
Puuilo search page and rotates periodically. The search script fetches it
automatically on every run by scraping:

```
GET https://www.puuilo.fi/catalogsearch/result/?q=test
→ extract "apiKey":"<key>" from the HTML (tries plain JSON, unicode-escaped,
   and algoliaConfig JSON.parse patterns)
```

The Algolia Application ID is static: `HH40ESW4PH`.

## Search endpoint

```
POST https://HH40ESW4PH-dsn.algolia.net/1/indexes/<index>/query
```

### Headers

```
X-Algolia-Application-Id: HH40ESW4PH
X-Algolia-API-Key: <fetched-dynamically>
Content-Type: application/json
```

### Request body

```json
{
  "query": "suihkusetti",
  "hitsPerPage": 10,
  "page": 0
}
```

## Sort indices

| Sort option  | Algolia index                           |
| ------------ | --------------------------------------- |
| `relevance`  | `puuilo_fi_products`                    |
| `popular`    | `puuilo_fi_products_views_desc`         |
| `newest`     | `puuilo_fi_products_created_at_desc`    |
| `price_asc`  | `puuilo_fi_products_price_default_asc`  |
| `price_desc` | `puuilo_fi_products_price_default_desc` |
| `name_asc`   | `puuilo_fi_products_name_asc`           |
| `name_desc`  | `puuilo_fi_products_name_desc`          |

## Response structure

```json
{
  "hits": [
    {
      "name": "Product name",
      "sku": "12345",
      "url": "/fi/product-slug",
      "thumbnail_url": "https://...",
      "image_url": "https://...",
      "price": {
        "EUR": {
          "default": 29.99,
          "default_formated": "29,99 €"
        }
      },
      "categories_without_path": ["Category", "Subcategory"],
      "in_stock": true
    }
  ],
  "nbHits": 42,
  "page": 0,
  "nbPages": 5,
  "hitsPerPage": 10
}
```

### Key product fields

| Field                        | Description                                           |
| ---------------------------- | ----------------------------------------------------- |
| `name`                       | Product name                                          |
| `sku`                        | Product SKU                                           |
| `url`                        | Relative URL (prefix with `https://www.puuilo.fi`)    |
| `price.EUR.default`          | Consumer price (EUR, inc. VAT)                        |
| `price.EUR.default_formated` | Formatted price string (note: typo in API field name) |
| `categories_without_path`    | Category breadcrumb (array)                           |
| `in_stock`                   | Boolean stock status                                  |
| `thumbnail_url`              | Small product image URL                               |
| `image_url`                  | Full-size product image URL                           |

## Notes

- Product URLs are relative; prefix with `https://www.puuilo.fi`
- The API key expires and must be re-fetched; the script handles this transparently
- `default_formated` is a typo in the Puuilo API (missing an 't'); use as-is
