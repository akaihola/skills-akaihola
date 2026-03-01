# Motonet — Search API

## Architecture

Motonet.fi is a Next.js application by Broman Group. The search is served
by their own backend (no third-party search service like Algolia or Klevu).
The API is exposed as Next.js API routes.

## Endpoints

### 1. Product Search (PRIMARY)

**POST** `https://www.motonet.fi/api/search/products?locale=fi`

**Headers:**
```
Content-Type: application/json
```

**Request body (JSON):**

| Field      | Type   | Required | Description                                    |
|------------|--------|----------|------------------------------------------------|
| `q`        | string | Yes      | Search term                                    |
| `page`     | int    | Yes      | Page number, 1-based                           |
| `pageSize` | int    | Yes      | Results per page (must be exactly 30)          |
| `facets`   | string | No       | Base64-encoded JSON for filtering (see below)  |

**Important:** `pageSize` must be exactly `30`. The server validates this and
rejects other values.

**Facets parameter:**

The `facets` field is a base64-encoded JSON string with this shape:
```json
{
  "Categories": [],
  "Brand": ["EXIDE"],
  "CampaignPrice": {},
  "AvailableInLocations": []
}
```

Encode it as base64 and pass as a string in the request body.

**Example request:**

```bash
curl -s -X POST 'https://www.motonet.fi/api/search/products?locale=fi' \
  -H 'Content-Type: application/json' \
  -d '{"q": "akku", "page": 1, "pageSize": 30}'
```

**Response structure:**

```json
{
  "products": [
    {
      "id": "90-9512",
      "isVariant": false,
      "name": "Exide EB454 45 Ah / 330 A akku P237 x L127 x K227 -+",
      "description": "Täysin huoltovapaa käynnistysakku...",
      "price": "99,90",
      "tags": [],
      "productGroup": false,
      "webshopOnly": true,
      "modelProductCode": null,
      "brand": "EXIDE",
      "categoryName": "Käynnistysakut",
      "categoryUrl": "/tuoteryhmat/akut-ja-akkutarvikkeet/akut/kaynnistysakut?category=d51fae27-..."
    }
  ],
  "facets": [
    {"name": "Tuoteryhmä", "type": "distinct", "items": [{"item": "AGM-akut", "count": 11}]},
    {"name": "Brändi", "type": "distinct", "items": [...]},
    {"name": "Hinta", "type": "range", "items": []},
    {"name": "Saatavuus tavaratalosta", "type": "distinct", "items": [...]}
  ],
  "queryUsed": null,
  "pagination": {
    "page": 1,
    "pageCount": 73,
    "totalCount": 2171,
    "nextPage": "page=2&pageSize=30&facets=...&q=akku"
  },
  "sort": null,
  "relatedResults": ["98-16988"]
}
```

### 2. Suggestions / Autocomplete

**GET** `https://www.motonet.fi/api/suggestions?q={term}`

No special headers required.

**Response:**
```json
{
  "groups": [
    {
      "caption": "did_you_mean",
      "items": [
        {"type": "link", "text": "akku", "as": "/search?q=akku", "href": "/search?q=akku"}
      ]
    },
    {
      "caption": "categories",
      "items": [{"text": "Käynnistysakut", "href": "/tuoteryhmat/..."}]
    },
    {
      "caption": "brands",
      "items": [{"text": "EXIDE", "href": "/brands/exide"}]
    }
  ],
  "products": [
    {"id": "90-9512", "name": "...", "price": "99,90", "brand": "EXIDE"}
  ]
}
```

### 3. Pricing API

**POST** `https://www.motonet.fi/api/pricing/prices?locale=fi`

**Body:** `{"productCodeList": ["90-9512", "90-1101"]}`

Returns array of price objects with VAT details, unit prices, campaign info.

### 4. Availability / Stock API

**POST** `https://www.motonet.fi/api/stocksAndAvailability/availabilities`

**Body:** `{"productCodes": ["90-9512", "90-1101"]}`

Returns store availability and delivery timeframes.

## Authentication

No authentication required for search, pricing, and availability APIs.

## Product URLs

Products are at:
```
https://www.motonet.fi/tuote/{slug}?product={id}
```

Where `{slug}` is a URL-friendly version of the product name and `{id}` is the
product code (e.g., `90-9512`).

## Website Search URL (for reference)

```
https://www.motonet.fi/haku?q=QUERY
```
