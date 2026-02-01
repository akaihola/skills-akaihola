# Power.fi — Product Search API

## Base URL

```
https://www.power.fi/api/v2/productlists
```

## Endpoints

### Product Search

**GET** `/api/v2/productlists`

Returns product results matching the search term with filters, pagination, and
sorting.

**Parameters:**

| Parameter | Type   | Required | Description                          |
| --------- | ------ | -------- | ------------------------------------ |
| `q`       | string | yes      | Search query                         |
| `size`    | int    | yes      | Number of results per page (e.g. 36) |
| `from`    | int    | yes      | Pagination offset (0-based)          |
| `s`       | int    | yes      | Sort order (see below)               |
| `o`       | string | no       | Unknown flag (default: `false`)      |
| `cd`      | string | no       | Unknown flag (default: `false`)      |

**Sort values (`s`):**

| Value | Description         |
| ----- | ------------------- |
| `1`   | Price low to high   |
| `2`   | Price high to low   |
| `3`   | Name A–Z            |
| `4`   | Name Z–A            |
| `5`   | Relevance (default) |

Values 6 and 7 behave identically to 5. Value 8 may sort by newest. Values 0
and 9+ return HTTP 400.

### Search Suggestions

**GET** `/api/v2/search/suggestions`

Returns autocomplete suggestions including brands, categories, and manufacturers.

| Parameter    | Type   | Required | Description  |
| ------------ | ------ | -------- | ------------ |
| `searchTerm` | string | yes      | Search query |

## Response Structure — Product Search

```json
{
  "filters": [
    {
      "attributeId": "BasicBrand",
      "name": "Tuotemerkki",
      "filterType": 1,
      "valueCountDictionary": { "Moccamaster": 51, "Wilfa": 7 }
    },
    {
      "attributeId": "BasicPrice",
      "name": "Hinta",
      "filterType": 4,
      "min": 3.0,
      "max": 1899.0
    }
  ],
  "products": [
    {
      "productId": 3060434,
      "title": "Moccamaster Oneswitch kahvinkeitin, Black",
      "manufacturerName": "Moccamaster",
      "manufacturerId": 318,
      "price": 249.0,
      "previousPrice": 199.0,
      "vatlessPrice": 198.41,
      "vatPercent": 25.5,
      "categoryId": 3562,
      "categoryName": "Kahvinkeittimet",
      "shortDescription": "Luotettavaa ja helppoa kahvin valmistusta",
      "salesArguments": "Tilavuus 1,25 L / 10 kuppia\n...",
      "stockCount": 147,
      "storesStockCount": 212,
      "clickNCollectStoreCount": 37,
      "isLimitedQuantity": false,
      "url": "/keittion-pienkoneet/kahvi-ja-tee/kahvinkeittimet/moccamaster-.../p-3060434/",
      "barcode": "8712072537514",
      "breadcrumb": [
        { "id": 3562, "name": "Kahvinkeittimet" },
        { "id": 3395, "name": "Kahvi ja tee" },
        { "id": 3311, "name": "Keittiön pienkoneet" }
      ],
      "productReview": {
        "overallAverageRating": 4.5,
        "overallTotalReviewCount": 1082
      },
      "productImage": {
        "basePath": "/images/h-b995b5568c0600c95b451ccee324717a/products/3060434",
        "variants": [
          {
            "filename": "3060434_2_600x600_w_g.jpg",
            "width": 600,
            "height": 600
          }
        ]
      },
      "priceType": 2,
      "showSavingsAs": 1
    }
  ],
  "startIndex": 0,
  "totalProductCount": 138,
  "sortId": 5,
  "pageSize": 36,
  "isLastPage": false
}
```

## Key Product Fields

| Field                     | Description                                                      |
| ------------------------- | ---------------------------------------------------------------- |
| `productId`               | Unique product ID                                                |
| `title`                   | Product name                                                     |
| `manufacturerName`        | Brand / manufacturer                                             |
| `price`                   | Current price (EUR, incl. VAT)                                   |
| `previousPrice`           | Previous price (for showing discounts)                           |
| `vatlessPrice`            | Price excluding VAT                                              |
| `vatPercent`              | VAT percentage                                                   |
| `categoryName`            | Product category name                                            |
| `shortDescription`        | Short product description                                        |
| `salesArguments`          | Bullet points (newline-separated)                                |
| `stockCount`              | Online stock count                                               |
| `storesStockCount`        | Total physical store stock                                       |
| `clickNCollectStoreCount` | Number of stores with C&C availability                           |
| `url`                     | Relative product URL (prefix with `https://www.power.fi`)        |
| `barcode`                 | EAN / GTIN barcode                                               |
| `productReview`           | Object with `overallAverageRating` and `overallTotalReviewCount` |
| `productImage`            | Object with `basePath` and `variants[]`                          |
| `breadcrumb`              | Category hierarchy array                                         |

## Image URLs

Images use the pattern:

```
https://www.power.fi{basePath}/{filename}
```

For example:

```
https://www.power.fi/images/h-b995b5568c0600c95b451ccee324717a/products/3060434/3060434_2_600x600_w_g.jpg
```

Common variant sizes: 150×150, 300×300, 600×600, 900×900, 1200×1200.
Formats: `.jpg` (opaque), `.webp` (opaque or transparent), `.png` (transparent).

## Store Stock

### Per-Store Availability

**GET** `/api/v2/products/{productId}/stores`

Returns per-store stock information for a product, sorted by distance from the
given postal code.

**Parameters:**

| Parameter    | Type   | Required | Description                        |
| ------------ | ------ | -------- | ---------------------------------- |
| `postalCode` | string | yes      | Postal code for distance sorting   |

**Response:** Array of store objects.

**Example response:**

```json
[
  {
    "storeId": 3789,
    "name": "POWER Itis Helsinki",
    "address": "Itäkatu 1",
    "city": "Helsinki",
    "storeStockCount": 11,
    "storeDisplayStock": 0,
    "storeAvailability": 2,
    "clickNCollect": true,
    "distance": 9.4,
    "workingSchedule": [
      { "dayOfWeek": "Sunday", "hours": "12 - 18" }
    ]
  }
]
```

**Store availability values:**

| Value | Meaning       |
| ----- | ------------- |
| `0`   | Not available |
| `1`   | Low stock     |
| `2`   | In stock      |

## Authentication

No authentication required. The API is publicly accessible.

## Filters

The API returns available filters in the response. Known filter attribute IDs:

| attributeId       | Description          | Type         |
| ----------------- | -------------------- | ------------ |
| `BasicBrand`      | Brand / manufacturer | Value counts |
| `BasicPrice`      | Price range          | Min/max      |
| `BasicInStock`    | Stock availability   | Value counts |
| `BasicCnC`        | Store availability   | Value counts |
| `BasicCategories` | Category IDs         | Value counts |

## Website Search URL (for reference)

```
https://www.power.fi/search/?q=QUERY
```
