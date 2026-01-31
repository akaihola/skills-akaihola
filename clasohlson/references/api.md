# Clas Ohlson Finland — Voyado Elevate (Apptus eSales) Search API

## Base URL

```
https://w76e66a6f.api.esales.apptus.cloud/api/v2/panels
```

Cluster ID: `w76E66A6F`, Market: `FI`

## Endpoints

### Product Search: `/search`

The primary search endpoint. Returns multiple sub-panels grouped into two sections:

**`assistant` section** (search-as-you-type results):

| Sub-panel              | Type          | Description                          |
|------------------------|---------------|--------------------------------------|
| `autocomplete`         | completions   | Search phrase completions            |
| `product-suggestions`  | products      | **Actual search results** (use this) |
| `did-you-mean`         | corrections   | Spelling corrections                 |
| `category-suggestions` | —             | Matching categories                  |
| `brand-suggestions`    | completions   | Matching brands                      |
| `store-suggestions`    | products      | Matching stores                      |
| `content-suggestions`  | products      | Matching content pages               |
| `top-sellers`          | products      | Popular products (not query-specific) |

**`result` section** (page-level data):

| Sub-panel              | Type          | Description                          |
|------------------------|---------------|--------------------------------------|
| `search-hits`          | products      | Top sellers (NOT query-specific)     |
| `search-hit-count`     | count         | Total hit count                      |
| `fixed-facets`         | facetList     | Available filters                    |
| `relevant-facets`      | facetList     | Relevant filters for this query      |

> **Important:** The `product-suggestions` sub-panel in the `assistant` section
> contains the actual search results. The `result/search-hits` panel always
> returns generic top sellers regardless of the search query.

**Required parameters:**

| Parameter               | Type   | Description                                     |
|-------------------------|--------|-------------------------------------------------|
| `esales.market`         | string | Market code, always `FI`                        |
| `esales.sessionKey`     | UUID4  | Random UUID per session                         |
| `esales.customerKey`    | UUID4  | Random UUID per session                         |
| `esales.searchPhrase`   | string | The search query                                |
| `market`                | string | Repeated market code, `FI`                      |
| `search_prefix`         | string | Same as searchPhrase                            |
| `window_first`          | int    | Pagination start (1-based)                      |
| `window_last`           | int    | Pagination end (inclusive)                       |
| `search_attributes`     | string | Comma-separated list of fields (literal commas) |

> **Note:** The `search_attributes` parameter requires literal commas, not
> percent-encoded `%2C`. Build the URL manually if using an HTTP library.

**Available `search_attributes`:**

- `name_fi` — Product name in Finnish
- `baseprice` — Price incl. VAT
- `basepricewithoutvat` — Price excl. VAT
- `sellingprice` — Current selling price
- `oldPriceWithoutVat` — Previous price (for discounts)
- `gridViewImage` — Product image (relative path, prefix with `https://images.clasohlson.com/medias`)
- `mainCategoryName_fi` — Primary category name
- `mainCategoryPath_fi` — Full category path
- `brand` — Brand name
- `description_fi` — Product description
- `article_number` — Article number
- `campaignStatus` — Whether product is on campaign

**Response structure:**

```json
{
  "assistant": [
    {
      "name": "product-suggestions",
      "resultType": "products",
      "products": [
        {
          "key": "416100001_FI",
          "variants": [
            {
              "key": "41-6100_FI",
              "attributes": {
                "name_fi": ["Porakone Ryobi R18DD4 One+ 18V"],
                "baseprice": ["99.9"],
                "mainCategoryName_fi": ["Porakoneet & ruuvinvääntimet"],
                "brand": ["RYOBI"]
              }
            }
          ]
        }
      ]
    },
    {
      "name": "autocomplete",
      "resultType": "completions",
      "completions": [
        {"query": "porakoneet"}
      ]
    }
  ],
  "result": [
    {
      "name": "search-hits",
      "resultType": "products",
      "products": []
    }
  ]
}
```

All attribute values are arrays (usually single-element).

## Authentication

No authentication required. Only random UUID v4 values for session/customer keys.

## Image URLs

Image attribute values are relative paths. Prefix with:

```
https://images.clasohlson.com/medias
```

## Website search URL (for reference)

```
https://www.clasohlson.com/fi/search?text=QUERY
```

This renders server-side HTML and loads products via the same Apptus API client-side.
