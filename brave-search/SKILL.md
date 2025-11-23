---
name: brave-search
description: Structured Brave Search web queries and summarizer workflows for MCP-style agents.
---

# Purpose

Provide deterministic wrappers around Brave Search’s web and summarizer endpoints. Use the web workflow to retrieve structured SERP data (web pages, FAQs, discussions, news, videos). Use the summarizer workflow to turn Brave’s aggregated findings into a concise narrative when the subscription permits summarization.

# When to Use

- Run web fact-finding on current events, product comparisons, research digests, or perspective gathering when Google/Bing responses are insufficient.
- Request the summarizer only after a prior web search produced a `summarizer_key`, and the user explicitly wants a Brave-generated synthesis.

# Configuration Requirements

- Set `BRAVE_SEARCH_API_KEY` in the execution environment. The value populates the `X-Subscription-Token` header.
- Prefer secure storage through the project’s secrets tooling before launching the script.
- All invocations must use `uv run` to respect the project’s Python environment.

# Workflows

## A. Web Search (results only)

1. Prepare JSON containing at least `"query"`. Optional keys include `country`, `search_lang`, `ui_lang`, `count`, `offset`, `safesearch`, `freshness`, `text_decorations`, `spellcheck`, `result_filter`, `goggles`, `units`, and `extra_snippets`.
2. Run `uv run scripts/brave_search.py web --params-json '<JSON>'`.
3. Consume `web_results`, `faq_results`, `discussions_results`, `news_results`, and `video_results` from the JSON output. Each section mirrors the Brave MCP tool’s simplified records.
4. If `ok` is `false` with `"No web results found"`, broaden or restate the query before retrying.

## B. Web Search with Summarizer Key

1. Follow workflow A but add `"summary": true` to the JSON payload.
2. The script automatically requests `result_filter=summarizer`. Inspect the response’s `summarizer_key`.
3. Store the key and cite the original `web_results` when answering detailed questions while preparing for a summarizer follow-up.

## C. Summarizer

1. Ensure a recent workflow B run produced a `summarizer_key`.
2. Build JSON like `{"key": "<summarizer_key>", "entity_info": false, "inline_references": true}`. Optional overrides: `poll_interval_ms` (default 50) and `max_attempts` (default 20).
3. Run `uv run scripts/brave_search.py summarizer --params-json '<JSON>'`.
4. Use `summary_text` as the main synthesis. Supplement with `enrichments`, `followups`, and `entities_infos` for deeper context or suggested next steps.
5. If the summarizer fails, rely on the previously collected `web_results` to craft a manual answer.

# Error Handling and Fallbacks

- Missing API key: the script emits `ok: false` with an explicit description; set the environment variable and rerun.
- HTTP or Brave-side errors: review the `details` object, adjust parameters, or pause if throttled.
- Summarizer polling timeout: rerun the web search to refresh the key, or answer using raw web data.

# References

- `references/brave_web_search_params.md` — exhaustive parameter definitions and sample payloads.
- `references/brave_summarizer_workflow.md` — polling logic, summary message schema, and tuning guidance.
- `references/brave_search_examples.md` — end-to-end scenarios demonstrating combined web and summarizer usage.