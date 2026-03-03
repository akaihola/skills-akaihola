# Fonecta Caller – API & Page Structure Reference

Discovered by intercepting network traffic from `www.fonecta.fi` with Playwright.
Last verified: 2026-03-03.

---

## Authentication

Fonecta Caller uses AWS Cognito for auth, exposed via `customer-api.fonecta.fi`.

### Login flow (two-step form in a MUI Dialog)

1. `GET https://www.fonecta.fi/` — load the homepage
2. Accept the OneTrust cookie consent banner (`#onetrust-accept-btn-handler`)
3. Click `button[text="Kirjaudu sisään"]` (opens a MUI Dialog)
4. Fill `input[name='email']`, click `button[text="Seuraava"]`
5. Fill `input[name='password']`, click the login button **inside** the dialog:
   `div[role='presentation'].MuiDialog-root >> button[text="Kirjaudu sisään"]`
   (There are two buttons with that text — the nav bar one is intercepted by the dialog overlay,
   so scoping to the dialog is required.)

### Token acquisition

`POST https://customer-api.fonecta.fi/users/login?sourceApp=callerWeb`

Response:
```json
{
  "accessToken": "eyJ…",
  "refreshToken": "eyJ…",
  "idToken": "eyJ…"
}
```

The `accessToken` is a JWT issued by AWS Cognito (`eu-west-1_ZQNfKddqK`).
It appears in subsequent requests as `Authorization: Bearer <accessToken>`.
Expires after ~30 minutes; refresh via
`POST /users/refresh-token?sourceApp=callerWeb` with `{"refreshToken": "…"}`.

### Subscription check

`GET https://customer-api.fonecta.fi/user?sourceApp=callerWeb`

```json
{
  "subscription": {
    "type": "CallerPro",
    "hasSearch": true,
    "expires": "2026-04-03T08:29:17.957Z"
  }
}
```

`hasSearch: true` is required to retrieve search results.

---

## Reverse phone number search

### URL pattern

```
https://www.fonecta.fi/haku/<local-number>
```

`<local-number>` is the Finnish local format: `0401234567` (not `+358401234567`).

This is a Next.js SSR page. Results are embedded in the HTML inside `__NEXT_DATA__`
as a JSON blob — no extra API call is needed after page load.

### Extracting results from `__NEXT_DATA__`

```python
import json, re

nd = re.search(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    html, re.DOTALL
)
data = json.loads(nd.group(1))
page_props = data["props"]["pageProps"]

# Results live in dehydratedState (React Query cache pre-populated by SSR)
for query in page_props["dehydratedState"]["queries"]:
    if query["queryKey"][0] == "search":
        results = query["state"]["data"]["results"]
        for r in results:
            name = r.get("displayName") or r.get("name")
```

### Result object shapes

**Person** (`contactType: "PERSON"`):
```json
{
  "id": "e53da82edbf923a4",
  "contactType": "PERSON",
  "name": "Jesse Peurala",
  "firstName": "Jesse",
  "lastName": "Peurala",
  "mobile": "040 768 2810",
  "cityName": "Helsinki",
  "ownerName": "Yes & Se Oy",
  "operatorName": "Elisa Oyj"
}
```

**Company** (`contactType: "COMPANY"`):
```json
{
  "id": "3513053",
  "contactType": "COMPANY",
  "name": "Yes & Se Oy",
  "businessId": "31556423",
  "mobile": "040 768 2810",
  "mainLineOfBusinessName": "IT-konsultointi, IT-palvelut",
  "cityName": "Helsinki"
}
```

A single phone number can match both a PERSON and a COMPANY result (e.g. a sole
trader's mobile registered under their company). Always prefer `contactType == "PERSON"`
over `"COMPANY"` when both are present — the person name is more useful for identifying
who sent a message.

### When a number has no entry

```json
{"results": [], "query": {"totalResults": 0, "numberSearch": true}}
```

The page shows "Voi harmi, numerolla ei löytynyt tietoja!" — the number is either
unlisted, a prepaid SIM, or a business line not registered with Fonecta.

---

## `fofisuggest` autocomplete endpoint

`GET https://customer-api.fonecta.fi/fofisuggest?searchTerm=0401234567&results_per_page=5&sourceApp=callerWeb`

Returns quick autocomplete suggestions. In practice this endpoint returned empty
results (`{"suggestions":[]}`) for all tested numbers even when the full search
page returned a match. Do not rely on it for name resolution — use the SSR page instead.

---

## Rate limiting

No explicit rate limit was observed during a batch of 41 lookups with 300 ms delays.
The `CallerPro` subscription tier has `"credits": 0` in the user object (credits are
for SMS/call lookups, not web searches). Web searches appear unlimited under Pro.
