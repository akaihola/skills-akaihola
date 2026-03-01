# Verkkokauppa.com — Search API

## Architecture

Verkkokauppa.com uses **Google Retail Search** as its search backend. The response
`meta.variant` field indicates which backend served the results (`google-retail-search`
or `elasticsearch` depending on sort order).

## Base URL

```
https://search.service.verkkokauppa.com/{lang}/api/v1/product-search
```

Where `{lang}` is `fi` (Finnish) or `en` (English).

## Endpoints

### Product Search

**GET** `/fi/api/v1/product-search`

Returns products matching the search term. Uses JSON:API filter syntax.

**Required parameters:**

| Parameter    | Type   | Description                                         |
|--------------|--------|-----------------------------------------------------|
| `filter[q]`  | string | The search query (URL-encoded)                      |
| `sessionId`  | UUID4  | Random UUID per session                             |
| `private`    | string | Must be `true` for anonymous users                  |

Without `sessionId` and `private=true`, the API returns `400 Invalid user`.

**Optional parameters:**

| Parameter            | Type   | Description                                     |
|----------------------|--------|-------------------------------------------------|
| `sort`               | string | Sort order (see below)                          |
| `page[size]`         | int    | Results per page (default: 48)                  |
| `page[number]`       | int    | Page number, **1-based** (default: 1)           |
| `filter[category][]` | string | Category slug filter                            |
| `filter[brandSlug][]`| string | Brand slug filter                               |
| `include`            | string | Comma-separated: `campaigns`, `category`, `salesCategories.parent`, `facets` |

**Important:** `page[number]` is **1-based**. Value `0` causes an error.

**Sort values:**

| Value                  | Description        |
|------------------------|--------------------|
| `-score`               | Relevance (default)|
| `price`                | Price low to high  |
| `-price`               | Price high to low  |
| `-popularity`          | Most popular       |
| `-rating`              | Highest rated      |
| `-releaseDate`         | Newest first       |
| `-discountPercentage`  | Biggest discount   |

**Minimal working request:**

```
https://search.service.verkkokauppa.com/fi/api/v1/product-search?sessionId=UUID&private=true&filter[q]=QUERY&sort=-score&page[number]=1
```

## Response Structure (JSON:API)

```json
{
  "data": [
    {
      "type": "products",
      "id": "911356",
      "attributes": {
        "active": true,
        "name": "Samsung ViewFinity S34C650T 34\" UWQHD -näyttö",
        "href": "/fi/product/911356/Samsung-ViewFinity...",
        "descriptionShort": "...",
        "price": {
          "current": 379.99,
          "currentFormatted": "379,99",
          "original": 549.99,
          "discountPercentage": 31,
          "taxRate": 25.5
        },
        "images": [{"orig": "https://cdn.verk.net/images/..."}],
        "rating": {"reviewCount": 42, "averageOverallRating": 4.5},
        "articles": [{"eans": ["8806095070..."], "articleId": 123456}],
        "bulletPoints": ["34\" ultrawide", "UWQHD 3440x1440"],
        "ribbons": []
      },
      "relationships": {
        "brand": {"data": {"id": "167", "type": "brands"}},
        "category": {"data": {"id": "monitors", "type": "salesCategories"}},
        "campaigns": {"data": []}
      }
    }
  ],
  "included": [
    {"type": "facet", "id": "category", "attributes": {"title": "Tuotealueet"}},
    {"type": "facet", "id": "brand", "attributes": {"title": "Brändit"}},
    {"type": "facet", "id": "price", "attributes": {"title": "Hinta"}}
  ],
  "meta": {
    "totalResults": 450,
    "variant": "google-retail-search"
  }
}
```

**Note:** Brand names are not directly available in the response — only brand IDs
in `relationships.brand.data.id`. However, product names typically include the
brand (e.g., "Samsung ViewFinity...").

### Autocomplete / Search Suggestions

```
GET https://search.service.verkkokauppa.com/{lang}/api/v1/autocomplete?filter[q]={term}&sessionId={uuid}&private=true
```

Returns term suggestions and product suggestions in JSON:API format.

### Popular Search Terms

```
GET https://search.service.verkkokauppa.com/fi/api/v1/popular-search-terms?page[size]=10
```

Returns trending search terms. Does not require `sessionId` or `private`.

## Authentication

No authentication required. A random UUID v4 for `sessionId` and `private=true`
are needed for anonymous access.

## Image URLs

Images are served via Verkkokauppa CDN with full URLs in the response:

```
https://cdn.verk.net/images/...
```

## Website Search URL (for reference)

```
https://www.verkkokauppa.com/fi/search?query=QUERY
```
