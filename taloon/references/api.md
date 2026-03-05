# Taloon.com – Loop54 Search API

The Taloon.com webshop uses **Loop54** as its search backend.
This is identical in structure to the Netrauta API (both are Loop54 deployments).

## Search endpoint

```
POST https://taloon-fi-prod.54proxy.com/search
Content-Type: application/json
Api-Version: V3
User-Id: <random UUID v4>
```

A fresh random UUID must be generated for each request as `User-Id`.

### Request body

```json
{
  "query": "suihkusetti",
  "resultsOptions": {
    "skip": 0,
    "take": 10
  }
}
```

| Field                 | Type   | Description                      |
| --------------------- | ------ | -------------------------------- |
| `query`               | string | Search term                      |
| `resultsOptions.skip` | int    | Offset (0-based, for pagination) |
| `resultsOptions.take` | int    | Number of results to return      |

### Response structure

```json
{
  "results": {
    "items": [
      {
        "attributes": [
          { "name": "name", "values": ["Product name"] },
          { "name": "brand", "values": ["Brand"] },
          { "name": "price", "values": ["29.99"] },
          { "name": "list_price", "values": ["39.99"] },
          { "name": "availability", "values": ["1"] },
          { "name": "product_url", "values": ["/product/slug"] }
        ]
      }
    ],
    "count": 42
  }
}
```

Product fields are returned as a flat list of `{name, values}` objects.
The script flattens these into a dict keyed by attribute name.

### Key product attributes

| Attribute      | Description                                                 |
| -------------- | ----------------------------------------------------------- |
| `name`         | Product name                                                |
| `brand`        | Brand name                                                  |
| `price`        | Current price (EUR, inc. VAT)                               |
| `list_price`   | Original price before discount                              |
| `availability` | Stock status (`1` = in stock, `0` = out of stock)           |
| `product_url`  | Relative product URL (prefix with `https://www.taloon.com`) |

## Notes

- No authentication required
- Sorting is not supported by this API endpoint
- Pagination uses `skip` (offset) and `take` (limit)
- Loop54 is a product discovery platform; the proxy URL is specific to Taloon.com
