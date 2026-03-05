# Bauhaus Finland – Algolia Search API

The Bauhaus Finland webshop uses **Algolia** as its search backend.

## Authentication

The Algolia API key is **not static** – it is embedded in the HTML of the
Bauhaus search page and rotates periodically. The search script fetches it
automatically on every run:

```
GET https://www.bauhaus.fi/catalogsearch/result/?q=test
→ extract "apiKey":"<key>" from the HTML response
```

The Algolia Application ID is static: `PR1NXR88J1`.

## Search endpoint

```
POST https://PR1NXR88J1-dsn.algolia.net/1/indexes/<index>/query
```

### Headers

```
X-Algolia-Application-Id: PR1NXR88J1
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

| Field         | Type   | Default | Description           |
| ------------- | ------ | ------- | --------------------- |
| `query`       | string | —       | Search term           |
| `hitsPerPage` | int    | 10      | Results per page      |
| `page`        | int    | 0       | Page number (0-based) |

## Sort indices

| Sort option  | Algolia index                                      |
| ------------ | -------------------------------------------------- |
| `relevance`  | `nordic_production_fi_products`                    |
| `price_asc`  | `nordic_production_fi_products_price_group_0_asc`  |
| `price_desc` | `nordic_production_fi_products_price_group_0_desc` |
| `newest`     | `nordic_production_fi_products_created_at_desc`    |

## Response structure

```json
{
  "hits": [
    {
      "name": "Product name",
      "sku": "12345",
      "ean": "1234567890123",
      "brand": "Brand name",
      "url": "/fi/product-slug",
      "thumbnail_url": "https://...",
      "price": {
        "EUR": {
          "group_0": 29.99,
          "group_0_default_formatted": "29,99 €"
        }
      },
      "categories_without_path": ["Category", "Subcategory"],
      "in_stock": true,
      "primarycolor": "Black",
      "web_in_stock_text": "Saatavilla verkosta",
      "physic_in_stock_text": "Saatavilla myymälöistä"
    }
  ],
  "nbHits": 42,
  "page": 0,
  "nbPages": 5,
  "hitsPerPage": 10
}
```

### Key product fields

| Field                                 | Description                                         |
| ------------------------------------- | --------------------------------------------------- |
| `name`                                | Product name                                        |
| `sku`                                 | Product SKU                                         |
| `ean`                                 | EAN barcode                                         |
| `brand`                               | Brand name                                          |
| `url`                                 | Relative URL (prefix with `https://www.bauhaus.fi`) |
| `price.EUR.group_0`                   | Consumer price (EUR, inc. VAT)                      |
| `price.EUR.group_0_default_formatted` | Formatted price string                              |
| `categories_without_path`             | Category breadcrumb (array)                         |
| `in_stock`                            | Boolean stock status                                |
| `primarycolor`                        | Primary colour                                      |
| `web_in_stock_text`                   | Web availability text (Finnish)                     |
| `physic_in_stock_text`                | Store availability text (Finnish)                   |

## Notes

- Product URLs are relative; prefix with `https://www.bauhaus.fi`
- The `group_0` pricing tier corresponds to standard consumer pricing
- The API key expires and must be re-fetched; the script handles this transparently
