# Brave Web Search Parameters

This reference enumerates every parameter the `scripts/brave_search.py web` workflow accepts, mirroring the Brave MCP server semantics. All requests translate to `GET https://api.search.brave.com/res/v1/web/search` with `X-Subscription-Token` set from `BRAVE_SEARCH_API_KEY`.

## Quick Usage Checklist

1. Build a JSON object containing at least `"query"`.
2. Optional fields listed below may be added to steer geography, freshness, filtering, or output structure.
3. Run `uv run scripts/brave_search.py web --params-json '<JSON>'`.
4. Inspect the structured sections returned (`web_results`, `faq_results`, `discussions_results`, `news_results`, `video_results`, `summarizer_key`).

## Parameter Reference

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `query` | string (required) | — | Maps to `q`. Must be non-empty text. |
| `country` | string | `None` | ISO country code (e.g., `us`, `gb`). Influences localization of sources. |
| `search_lang` | string | `None` | ISO language code for indexing preference. |
| `ui_lang` | string | `None` | ISO language code for interface/localized snippets. |
| `count` | integer | Brave default (typically 10) | Number of web results. Combine with `offset` for pagination. |
| `offset` | integer | 0 | Starting result index. |
| `safesearch` | string | `moderate` (Brave default) | One of `off`, `moderate`, `strict`. Filters explicit content. |
| `freshness` | string | `None` | Examples: `pd` (past day), `pw` (past week), `pm` (past month). Narrows web/news recency. |
| `text_decorations` | boolean | `true` | When `false`, disables bold/emphasis markup in snippets. |
| `spellcheck` | boolean | `true` | Turn off to avoid Brave’s auto spell correction. |
| `result_filter` | list<string> or string | `None` | Comma-joined server-side filter for sections (`web`, `news`, `videos`, `faq`, etc.). Ignored when `summary=true` (see below). |
| `goggles` | string or list<string> | `None` | One or more HTTPS URLs pointing to Brave Goggles definitions. Non-HTTPS entries are discarded. |
| `units` | string | `None` | Measurement system hint such as `metric` or `imperial`. |
| `extra_snippets` | boolean | `false` | Request additional snippet sentences when available. |
| `summary` | boolean | `false` | When `true`, automatically rewrites `result_filter` to `summarizer` so the response includes `summarizer.key`. Required before calling the summarizer workflow. |

## Derived Behaviors

- **Summarizer Key Generation**: Setting `summary: true` informs Brave to prepare summarizer context. The script enforces `result_filter=summarizer` in that scenario; any user-provided `result_filter` is ignored.
- **Goggles Validation**: Only HTTPS Goggles URLs are forwarded. Supply either a single URL or an array when stacking multiple community ranking rules.
- **Boolean Serialization**: Boolean flags are transmitted as lowercase `true`/`false` strings to match Brave’s expectations.
- **Error Semantics**:
  - Missing `query` or malformed JSON → immediate validation error (`ok: false`).
  - Brave HTTP errors bubble up with `details` containing either parsed JSON or the raw body.
  - Empty `web.results` from the API triggers `"No web results found"` to encourage query reformulation.

## Example Payloads

### General Research Query

```/dev/null/example.json#L1-9
{
  "query": "history of carbon capture breakthroughs",
  "count": 6,
  "freshness": "pm",
  "extra_snippets": true
}
```

### Localization and SafeSearch Override

```/dev/null/example.json#L11-20
{
  "query": "electric bicycle subsidies",
  "country": "de",
  "ui_lang": "de",
  "safesearch": "strict",
  "goggles": [
    "https://goggles.brave.com/eu-policy.xml"
  ]
}
```

### Preparing for Summarization

```/dev/null/example.json#L22-33
{
  "query": "latest ai chips competition",
  "summary": true,
  "result_filter": [
    "web",
    "news"
  ],
  "goggles": "https://goggles.brave.com/tech-news.xml",
  "count": 8
}
```

The final example shows how any explicit `result_filter` entries are superseded by `summary: true`, yet keeping them in documentation can remind authors which sections they expected the summarizer to synthesize. ```
