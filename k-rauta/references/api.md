# K-Rauta – Search API

The K-Rauta Finland webshop exposes a simple JSON search endpoint.

## ⚠️ Prices not available

The v1 search API **does not include prices**. Users must check prices on
`k-rauta.fi` directly.

## Search endpoint

```
POST https://www.k-rauta.fi/api/search
Content-Type: application/json
```

### Request body

```json
{
  "query": "suihkusetti"
}
```

The API ignores pagination parameters and always returns up to 100 results.
Limiting is applied client-side in `search.py`.

### Response structure

```json
{
  "results": [
    {
      "id": "1234567",
      "ean": "1234567890123",
      "name": "Product name",
      "brand": "Brand name",
      "description": "Product description",
      "images": [{ "url": "/path/to/image.jpg" }],
      "salesCategories": [
        [
          { "level": 0, "name": "Top category" },
          { "level": 1, "name": "Subcategory" }
        ]
      ],
      "ratings": {
        "avgScore": 4.5,
        "reviewCount": 23
      },
      "isNewProduct": false,
      "isOutgoing": false
    }
  ]
}
```

### Key product fields

| Field                 | Description                                                          |
| --------------------- | -------------------------------------------------------------------- |
| `id`                  | Internal product ID                                                  |
| `ean`                 | EAN barcode                                                          |
| `name`                | Product name                                                         |
| `brand`               | Brand name                                                           |
| `description`         | Product description                                                  |
| `images[].url`        | Image path (prefix with `https://public.keskofiles.com` if relative) |
| `salesCategories`     | Array of category chains; each chain is sorted by `level`            |
| `ratings.avgScore`    | Average review score                                                 |
| `ratings.reviewCount` | Number of reviews                                                    |
| `isNewProduct`        | Whether the product is newly listed                                  |
| `isOutgoing`          | Whether the product is being phased out                              |

## Image URLs

Image paths from the API may be relative. Prefix with:

```
https://public.keskofiles.com
```

## Notes

- No authentication required
- No API key required
- The API does not support sorting or filtering by price
- For product page URLs, construct them manually from the product name/id:
  `https://www.k-rauta.fi/tuote/<product-slug>/<id>`
