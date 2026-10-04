# Kuluttaja.fi API Reference

Site platform: WordPress + WooCommerce + WooCommerce Memberships + Yoast SEO + Relevanssi search plugin.

## Base URLs

| Base | Purpose |
|---|---|
| `https://kuluttaja.fi` | Frontend |
| `https://kuluttaja.fi/wp-json` | WP REST API root |
| `https://kuluttaja.fi/wp-json/wp/v2` | Standard WP endpoints |
| `https://kuluttaja.fi/wp-json/kuluttaja/v1` | Custom Kuluttaja endpoints |
| `https://kuluttaja.fi/wp-json/relevanssi/v1` | Relevanssi search |
| `https://kuluttaja.fi/wp-json/yoast/v1` | Yoast SEO |

## WP REST Endpoints (wp/v2)

### Posts

**Search posts:**
```
GET /wp-json/wp/v2/posts?search=<query>&per_page=<N>&offset=<N>&_embed=true
```

Response: array of post objects with fields:
- `id`, `date`, `date_gmt`, `slug`, `status` ("publish"/"draft")
- `title.rendered` — HTML title
- `content.rendered` — HTML content (paywalled: teaser only)
- `excerpt.rendered` — HTML excerpt
- `class_list` — includes `"access-restricted"` when paywalled
- `meta` — WordPress meta fields (including ACF fields)
- `yoast_head` — raw Yoast schema JSON-LD
- `yoast_head_json` — parsed Yoast schema (useful for date, author, OG data)
- `categories` — category IDs
- `tags` — tag IDs
- `writer` — writer taxonomy IDs

**Single post:**
```
GET /wp-json/wp/v2/posts/<id>?_embed=true
```

**By slug:**
```
GET /wp-json/wp/v2/posts?slug=<slug>&per_page=1
```

### Categories / Tags / Writer

```
GET /wp-json/wp/v2/categories?post=<id>
GET /wp-json/wp/v2/tags?post=<id>
GET /wp-json/wp/v2/writer?post=<id>
```

### Search URL template (Yoast Schema)

From the site's yoast schema:
```
Search URL: https://kuluttaja.fi/?s={search_term_string}
```

## Custom Endpoints (kuluttaja/v1)

| Endpoint | Method | Description |
|---|---|---|
| `/product-reviews/search?search=<q>&per_page=<N>` | GET | Search product reviews |
| `/product-reviews/latest-test-winners?limit=<N>` | GET | Latest test winners |
| `/product-reviews/get-products` | POST | Get products by IDs |
| `/product-reviews/<id>/related-products` | GET | Related products |
| `/test-data/<id>` | GET | Test data by ID |
| `/test-data/<id>/filters` | GET | Test data filters |
| `/magazine/latest` | GET | Latest magazine issues |
| `/magazine/<id>` | GET | Single magazine issue |
| `/magazine/get-epaper-url` | POST | Get ePaper URL |
| `/test-category-navigation/categories` | GET | Test categories |
| `/test-category-navigation/latest-tests-posts` | GET | Latest test posts |
| `/black-list/entries` | GET | Musta lista entries |
| `/black-list/locations` | GET | Musta lista locations |
| `/black-list/industries` | GET | Musta lista industries |
| `/content-restrictions/<id>` | GET | Content restriction info |
| `/comments?post=<id>` | GET | Comments for a post |
| `/wc/products` | GET | WooCommerce products |
| `/wc/up-sell-products-for-product` | GET | Upsell products |
| `/prisjakt/partner-search-by-products` | GET | Prisjakt partner search |
| `/code-scanner/tutorial` | GET | Code scanner tutorial |

## Authentication

### Subscriber accounts (Kuluttaja subscribers)

Reader accounts (e.g. `antti18+kuluttaja@kaihola.fi`) authenticate via
WooCommerce Memberships login flow, not WP application passwords. The
login UI is at `/kirjaudu/` and uses a form with:
- email field
- password field
- recaptcha
- redirects to membership dashboard after login

Full paywalled content requires this login flow. The WP REST API
content field (`content.rendered`) returns only the teaser for
`access-restricted` posts regardless of any HTTP auth headers.

### Application passwords

Available at `/wp/wp-admin/authorize-application.php`, but only for
WordPress admin accounts, not subscriber/ticket holders.

## Paywall Detection

A post is paywalled when:
- `"access-restricted"` ∈ `post.class_list`
- OR `"membership-content"` ∈ `post.class_list`
- OR `content.rendered` contains `<div id="paywall-section"`

The paywall section wraps `content.rendered` with:
```html
<div id="paywall-section" data-content-id="<post_id>" ...>
  <div class="paywall-section__wrapper__info ...">
    <h2>Jatka lukemista</h2>
    <p>Selvitimme olennaisen puolestasi...</p>
  </div>
  <div ...>
    <p>Osta pääsy tähän sisältöön tai tilaa Kuluttaja.</p>
    <a href="/kirjaudu/">Kirjaudu</a>
  </div>
</div>
```

## Cookie Consent

First-visit page has OneTrust cookie banner:
- "Hyväksy kaikki" — accept all
- "Vain välttämättömät" — accept only necessary
- `onetrust-accept-btn-handler` — accept button ID

## Content Structure

Article pages (when rendered from `content.rendered`) typically contain:
- Intro paragraphs (teaser — always visible)
- `<div id="paywall-section">` — paywall prompt for subscribers
- Section headings (h2, h3)
- Content paragraphs
- Tags (e.g., "GRILLAUS", "GRILLI", "KAASUGRILLI")
- Author attribution
- Related articles sidebar

Yoast head JSON-LD schema contains full article metadata:
- Author name
- Published date (`datePublished`)
- Article sections
- Keywords
- Image URLs
- Breadcrumbs
