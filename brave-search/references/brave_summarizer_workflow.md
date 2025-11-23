# Brave Summarizer Workflow

This reference explains how the `scripts/brave_search.py summarizer` command mirrors Brave’s MCP summarizer tool, including prerequisites, polling mechanics, and output interpretation.

## 1. Prerequisites

1. **Prior web search with `summary: true`:**
   - Run `uv run scripts/brave_search.py web --params-json '<JSON>'` and include `"summary": true`.
   - Capture the `summarizer_key` value from the successful response.

2. **Environment configuration:**
   - `BRAVE_SEARCH_API_KEY` must remain set; the summarizer relies on the same header as web search.
   - Keep network access to `https://api.search.brave.com/res/v1/summarizer/search`.

3. **Request payload basics:**
   - Minimum JSON: `{"key": "<summarizer_key>"}`.
   - Optional flags:
     - `entity_info` (bool) — request enriched entity objects.
     - `inline_references` (bool) — request inline citation markers inside the summary stream.
     - `poll_interval_ms` (int, default 50) — time between polling attempts.
     - `max_attempts` (int, default 20) — upper bound on polling retries.

## 2. Command Invocation

```/dev/null/example.md#L1-5
uv run scripts/brave_search.py summarizer --params-json '{
  "key": "summ-key-from-web-call",
  "inline_references": true,
  "entity_info": false
}'
```

- All arguments must form a single JSON object string.
- The script prints JSON to stdout; `ok` indicates whether a summary completed.

## 3. Polling Mechanism

1. After parsing parameters, the script sends `GET /res/v1/summarizer/search` with query parameters `key`, `entity_info`, and `inline_references`.
2. The response `status` field determines control flow:
   - `complete` → proceed to summary flattening.
   - Anything else → sleep `poll_interval_ms / 1000` seconds and retry.
3. If the loop reaches `max_attempts` without `status == "complete"`, the script returns `{"ok": false, "error": "Unable to retrieve a Summarizer summary."}`.

### Tuning Guidelines

- Increase `max_attempts` or `poll_interval_ms` for slower accounts or congested queues.
- Decrease `poll_interval_ms` only if the environment can tolerate more frequent HTTP calls.
- Re-run the web search if repeated polling failures indicate an expired `summarizer_key`.

## 4. Summary Flattening Logic

The Brave API returns `summary` as a list of message objects:

| Field | Description |
| --- | --- |
| `type` | Message segment classifier (`token`, `inline_reference`, other future values). |
| `data` | Content payload; string for tokens, object with `url` for inline references. |

Flattening rules:

1. For each `type == "token"` with string `data`, append the text verbatim.
2. For `type == "inline_reference"`:
   - If `inline_references` parameter was `true` and `data.url` exists, append ` (URL)` after the preceding text.
   - Otherwise ignore the segment for the flattened string.
3. Other types are ignored for `summary_text` but remain in `summary_raw`.

The final `summary_text` is the concatenation of all appended tokens and inline reference markers.

## 5. Output Structure

Successful response:

```json
{
  "ok": true,
  "summary_text": "<flattened tokens + inline references>",
  "summary_raw": [ ... ],               // Original summary message list
  "enrichments": { ... } | null,        // Optional entities, media, QA data
  "followups": [ ... ] | null,          // Suggested follow-up prompts
  "entities_infos": { ... } | null      // Detailed entity metadata
}
```

Failure response:

```json
{
  "ok": false,
  "error": "Unable to retrieve a Summarizer summary."
}
```

When `ok` is `false`, inspect accompanying `details` (if present) for HTTP or Brave-side diagnostics.

## 6. Recommended Workflow Pattern

1. **Search with summary intent:**

```/dev/null/workflow.md#L1-6
uv run scripts/brave_search.py web --params-json '{
  "query": "quantum dot display breakthroughs 2024",
  "summary": true,
  "freshness": "pm"
}'
```

2. **Store `summarizer_key` from the web response.**

3. **Summarize:**

```/dev/null/workflow.md#L8-15
uv run scripts/brave_search.py summarizer --params-json '{
  "key": "<summarizer_key>",
  "inline_references": true,
  "entity_info": true,
  "poll_interval_ms": 100,
  "max_attempts": 30
}'
```

4. **Compose user-facing answer:**
   - Lead with `summary_text`.
   - Cite notable URLs from the web results or inline references.
   - Use `enrichments`/`followups` for expanded insights or suggested next questions.

## 7. Troubleshooting

| Symptom | Resolution |
| --- | --- |
| Immediate `Missing key` error | Ensure `--params-json` includes `"key"` and the JSON is a valid object. |
| Repeated polling timeout | Increase `max_attempts`, refresh the key with a new web search, or investigate Brave service health. |
| Empty `summary_text` despite `ok: true` | Rare but possible when the API returns non-token segments only; fall back to manual summary using `web_results`. |
| HTTP error with details | Examine `details` for rate limiting, invalid key, or subscription requirements, then adjust accordingly. |

Keep this document close when authoring new automation or when mentoring agents on how to leverage Brave’s summarizer efficiently. ```
