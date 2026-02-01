# Tokmanni — Klevu Search API

## Base URL

```
https://eucs11.ksearchnet.com/cloud-search/n-search/search
```

API Key (ticket): `klevu-15488592134928913`

## Endpoints

### Product Search

**GET** `/cloud-search/n-search/search`

Returns product results matching the search term.

**Required parameters:**

| Parameter              | Type   | Description                                   |
| ---------------------- | ------ | --------------------------------------------- |
| `ticket`               | string | API key, always `klevu-15488592134928913`     |
| `term`                 | string | The search query                              |
| `paginationStartsFrom` | int    | Pagination offset (0-based)                   |
| `noOfResults`          | int    | Number of results per page                    |
| `klevuSort`            | string | Sort order: `rel`, `lth` (low-to-high), `htl` |
| `responseType`         | string | Always `json`                                 |

**Optional parameters:**

| Parameter                     | Type   | Description                                       |
| ----------------------------- | ------ | ------------------------------------------------- |
| `analyticsApiKey`             | string | Same as ticket (for analytics tracking)           |
| `showOutOfStockProducts`      | bool   | Include out-of-stock items (default: `true`)      |
| `klevuShowOutOfStockProducts` | bool   | Same, duplicated param (default: `true`)          |
| `fetchMinMaxPrice`            | bool   | Include price range in response (default: `true`) |
| `klevu_priceInterval`         | int    | Price facet interval (default: `500`)             |
| `klevu_multiSelectFilters`    | bool   | Enable multi-select filters (default: `true`)     |
| `enableFilters`               | bool   | Include filter facets in response                 |
| `filterResults`               | string | Apply filters (empty = none)                      |
| `visibility`                  | string | `search` for search results                       |
| `category`                    | string | Record type: `KLEVU_PRODUCT`                      |
| `klevu_filterLimit`           | int    | Max filter values (default: `50`)                 |
| `klevuFetchPopularTerms`      | bool   | Include popular search terms                      |
| `enablePersonalisation`       | bool   | Enable personalized results                       |
| `sortPrice`                   | bool   | Whether to sort by price                          |
| `ipAddress`                   | string | Client IP (can be `undefined`)                    |

**Minimal working request:**

```
https://eucs11.ksearchnet.com/cloud-search/n-search/search?ticket=klevu-15488592134928913&term=QUERY&paginationStartsFrom=0&noOfResults=10&klevuSort=rel&responseType=json&category=KLEVU_PRODUCT&visibility=search
```

## Response Structure

```json
{
  "meta": {
    "totalResultsFound": 60,
    "noOfResults": 5,
    "paginationStartFrom": 0,
    "typeOfQuery": "WILDCARD_AND",
    "storeBaseCurrency": "EUR",
    "term": "taskulamppu",
    "notificationCode": 1
  },
  "result": [
    {
      "name": "Taskulamppu Airam MAX 120",
      "sku": "6435200272911",
      "price": "11.95",
      "salePrice": "11.95",
      "oldPrice": "11.95",
      "basePrice": "11.95",
      "startPrice": "11.95",
      "currency": "EUR",
      "inStock": "yes",
      "url": "https://www.tokmanni.fi/taskulamppu-airam-max-120-6435200272911",
      "cloudinary_image": "https://res.cloudinary.com/tokmanni/image/upload/c_pad,b_white,f_auto,h_328,w_328/d_default.png/6435200272911.jpg",
      "id": "215413",
      "item_brand_name": "airam",
      "item_main_color": "musta",
      "category": "taskulamput",
      "klevu_category": "KLEVU_PRODUCT;;Kodin kunnostus;Valaisimet ja lamput;Taskulamput  @ku@kuCategory@ku@",
      "weight": "0.090000",
      "shortDesc": "",
      "typeOfRecord": "KLEVU_PRODUCT",
      "totalVariants": "0"
    }
  ]
}
```

## Key Product Fields

| Field              | Description                              |
| ------------------ | ---------------------------------------- |
| `name`             | Product name                             |
| `sku`              | Product SKU / EAN code                   |
| `price`            | Current price (EUR)                      |
| `salePrice`        | Sale price (EUR)                         |
| `oldPrice`         | Original price before discount           |
| `inStock`          | Stock status: `"yes"` or `"no"`          |
| `url`              | Full product URL on tokmanni.fi          |
| `cloudinary_image` | Product image URL (Cloudinary CDN)       |
| `id`               | Internal product ID                      |
| `item_brand_name`  | Brand name (lowercase)                   |
| `item_main_color`  | Main product color                       |
| `category`         | Product category                         |
| `klevu_category`   | Full category path (semicolon-delimited) |
| `weight`           | Product weight in kg                     |
| `shortDesc`        | Short description (often empty)          |

## Authentication

No authentication required. The API key (`klevu-15488592134928913`) is public
and embedded in the Tokmanni website frontend.

## Image URLs

Images are served via Cloudinary with the full URL in the `cloudinary_image` field.
The URL pattern includes automatic resizing:

```
https://res.cloudinary.com/tokmanni/image/upload/c_pad,b_white,f_auto,h_328,w_328/d_default.png/{sku}.jpg
```

## Website Search URL (for reference)

```
https://www.tokmanni.fi/catalogsearch/result/?q=QUERY
```
