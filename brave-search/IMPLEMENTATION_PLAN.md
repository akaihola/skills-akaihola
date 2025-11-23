# brave-search Skill – Implementation Plan

This document describes how to re-implement the `brave_web_search` and `brave_summarizer` tools from the Brave MCP server as a new `brave-search` skill, following the skill-authoring guidelines from the `skill-creator` skill.

---

## 1. Goals and Scope

### 1.1 Functional Goals

- Provide a `brave-search` skill that:
  - Exposes a **web search workflow** equivalent to the `brave_web_search` MCP tool.
  - Exposes a **summarizer workflow** equivalent to the `brave_summarizer` MCP tool.
- Preserve key semantics of the MCP server:
  - Parameter behavior (e.g., `summary`, `result_filter`, `goggles`, safesearch, freshness, etc.).
  - API error handling and "no results" handling.
  - Summarizer polling behavior and output format (flattened summary text, optional inline references).

### 1.2 Non-Goals (for initial version)

- Supporting additional Brave endpoints beyond:
  - `/res/v1/web/search`
  - `/res/v1/summarizer/search`
- Recreating every field of Brave’s API response as structured types.
- Implementing advanced rate-limiting, multi-key rotation, or caching.

---

## 2. Reference Behavior from Brave MCP Server

### 2.1 `brave_web_search` Summary

Source: original MCP server’s `src/tools/web/index.ts` and related files.

Key behaviors:

- Calls Brave Search Web endpoint via `API.issueRequest<'web'>('web', params)`:
  - URL: `GET https://api.search.brave.com/res/v1/web/search`
  - Parameters include:
    - `query` (mapped to `q` in query string)
    - `country`, `search_lang`, `ui_lang`
    - `count`, `offset`
    - `safesearch`
    - `freshness`
    - `text_decorations`
    - `spellcheck`
    - `result_filter` (array of result types)
    - `goggles`
    - `units`
    - `extra_snippets`
    - `summary` (enables summarizer key generation)
- Uses `X-Subscription-Token` header with Brave API key.

Response handling:

- Expects `WebSearchApiResponse`, potentially containing:
  - `web`, `faq`, `discussions`, `news`, `videos`, `summarizer`, etc.
- Formats results into simplified arrays:
  - **Web results**: `{ url, title, description, extra_snippets }[]`
  - **FAQ results**: `{ question, answer, title, url }[]`
  - **Discussions**: `{ mutated_by_goggles, url, data }[]`
  - **News**:
    - `{ mutated_by_goggles, source, breaking, is_live, age, url, title, description, extra_snippets }[]`
  - **Videos**:
    - `{ mutated_by_goggles, url, title, description, age, thumbnail_url, duration, view_count, creator, publisher, tags }[]`
- If a `summarizer` object exists in the response, the MCP tool exposes its `key`.

Error semantics:

- If there are no `web.results`:
  - Treat as error and return `"No web results found"`.

### 2.2 `brave_summarizer` Summary

Source: original MCP server’s `src/tools/summarizer/index.ts` and related files.

Key behaviors:

- Summarizer endpoint: `GET https://api.search.brave.com/res/v1/summarizer/search`
- Parameters (`SummarizerQueryParams`):
  - `key` – required; matches `summarizer.key` from web search response.
  - `entity_info?: boolean` – include extra entity info.
  - `inline_references?: boolean` – include inline references to URLs in summary.
- Uses a polling helper `pollForSummary`:
  - Default `pollInterval = 50 ms`, `attempts = 20`.
  - Repeatedly calls summarizer endpoint until response `status === "complete"`.
  - Throws if no complete response after all attempts.

Flattening summary:

- Response includes `summary?: SummaryMessage[]`, where:
  - Each entry has `type` and `data`.
- MCP tool flattens this to a single text string:
  - For `type === "token"`: append `data` text directly.
  - For `type === "inline_reference"`: append ` (url)` if present.
  - Other types are ignored for the text output.
- Final tool output is:
  - A flat text summary string.
  - Error message `"Unable to retrieve a Summarizer summary."` if summary is missing or polling fails.

### 2.3 Cross-Tool Dependency

- To use the summarizer, a client must:
  1. Perform web search with `summary: true`.
  2. Extract the `summarizer.key` from `web` search response.
  3. Pass that `key` into the summarizer query.

The `brave-search` skill will keep this two-step workflow.

---

## 3. Skill Design Overview

### 3.1 Skill Name and Purpose

- Skill name: `brave-search`
- Purpose:
  - Provide structured web search results and AI-generated summaries via Brave Search API.
  - Serve as a reusable, low-context wrapper around the Brave MCP server’s web and summarizer tools.

### 3.2 High-Level Components

1. **SKILL.md**
   - Contains:
     - YAML frontmatter (`name`, `description`).
     - Clear instructions on:
       - When to use this skill.
       - How to run web searches.
       - How to request and use summarizer keys.
       - How to run the summarizer and interpret outputs.
   - Written in imperative / instructional style (no second-person).

2. **scripts/**
   - `brave_search.py`:
     - Implements both:
       - `brave_web_search`-equivalent functionality.
       - `brave_summarizer`-equivalent functionality.
     - Provides a simple CLI so commands can be called deterministically.

3. **references/**
   - `brave_web_search_params.md`:
     - Detailed parameter docs and examples for web search.
   - `brave_summarizer_workflow.md`:
     - Summarizer lifecycle explanation, polling, and usage patterns.
   - `brave_search_examples.md`:
     - End-to-end example flows combining search and summarization.

4. **assets/**
   - Initially empty.
   - Reserved for potential future templates or example artifacts.

### 3.3 Context-Efficiency Strategy

- Keep `SKILL.md` under ~5k words, focusing on:
  - When to use the skill.
  - Concrete procedural steps.
- Push heavy documentation into `references/` files, to be loaded only when needed.
- Encapsulate all HTTP and polling logic in `scripts/brave_search.py` so it doesn’t need to be derived or re-explained in the main skill body.

---

## 4. Repository Layout

Target directory structure:

- `skills-akaihola/brave-search/`
  - `SKILL.md`
  - `IMPLEMENTATION_PLAN.md` (this file)
  - `scripts/`
    - `brave_search.py`
  - `references/`
    - `brave_web_search_params.md`
    - `brave_summarizer_workflow.md`
    - `brave_search_examples.md`
  - `assets/`
    - (empty for now)

---

## 5. `scripts/brave_search.py` Design

### 5.1 Dependencies and Environment

- Language: Python.
- HTTP client: `httpx` (preferred) or `requests`.
- Dependency declaration:
  - List all Python dependencies in PEP 723 inline script metadata at the top of `scripts/brave_search.py` (and any future Python scripts used by this skill).
- Installation (documented, not executed here):
  - Use the project convention `uv pip install httpx` (and similar) when adding dependencies to the environment.
- Execution convention:
  - Always invoke Python scripts via `uv run`, not `python`, in all documentation and examples.
- Configuration:
  - Require environment variable `BRAVE_SEARCH_API_KEY`.
  - Optionally document integration with a secrets-management mechanism if used in the environment.

Environment variables:

- `BRAVE_SEARCH_API_KEY` – Brave Search API subscription token.

### 5.2 Shared HTTP Utility: `issue_request`

Function: `issue_request(endpoint: str, params: dict) -> dict`

Responsibilities:

- Map `endpoint` to path:
  - `"web"` → `/res/v1/web/search`
  - `"summarizer"` → `/res/v1/summarizer/search`
- Construct URL: `BASE_URL + path`.
- Construct headers:
  - `Accept: application/json`
  - `Accept-Encoding: gzip`
  - `X-Subscription-Token: <BRAVE_SEARCH_API_KEY>`
- Build query string from `params` with equivalent behavior to MCP:

Parameter handling:

- `query`:
  - Map to `q` in query string.
- `result_filter`:
  - If `summary` is `True`, override so that:
    - `result_filter=summarizer`
  - Otherwise, if non-empty list, join values with comma:
    - e.g., `web,query,news`.
- `goggles`:
  - Accept a string or a list of strings.
  - If list, include each value as a separate `goggles` parameter.
  - Filter out non-HTTPS URLs (mimic `isValidGoggleURL`).
- For `localPois` / `localDescriptions` (future extension), handle `ids` as repeated parameters (not needed in v1).
- All other non-`None` parameters:
  - Convert to string and assign directly, with `query` → `q` mapping.
- Execute HTTP GET request, parse JSON response.
- On non-2xx:
  - Attempt to parse JSON error body and attach to error message.
  - Otherwise, attach raw text.

Return:

- Parsed JSON body as `dict`.
- Raise or propagate errors via explicit return format (see below).

### 5.3 Web Search Function: `run_web_search`

Function signature (internal):

- `def run_web_search(params: dict) -> dict`

Input expectations:

- `params` keys align with MCP `QueryParams`:
  - Required:
    - `query: str`
  - Optional (common cases):
    - `country: str`
    - `search_lang: str`
    - `ui_lang: str`
    - `count: int`
    - `offset: int`
    - `safesearch: str`
    - `freshness: str`
    - `text_decorations: bool`
    - `spellcheck: bool`
    - `result_filter: list[str]`
    - `goggles: str | list[str]`
    - `units: str`
    - `extra_snippets: bool`
    - `summary: bool`

Behavior:

1. Validate required fields (`query`, basic types) in a lightweight way (no heavy schema library required; simple checks and doc references).
2. Call `issue_request("web", params)`.
3. If `web` or `web["results"]` is missing or empty:
   - Return an object with `ok: false` and error `"No web results found"`.
4. Extract and format results into simplified structures:

   - `web_results`:
     - For each `result` in `response.get("web", {}).get("results", [])`:
       - `url`
       - `title`
       - `description`
       - `extra_snippets`
   - `faq_results`:
     - From `response.get("faq", {}).get("results", [])`, each:
       - `question`
       - `answer`
       - `title`
       - `url`
   - `discussions_results`:
     - From `response.get("discussions", {}).get("results", [])`:
       - `mutated_by_goggles` from `response["discussions"]["mutated_by_goggles"]`
       - `url`
       - `data` (full `ForumData` object if present)
   - `news_results`:
     - From `response.get("news", {}).get("results", [])`:
       - `mutated_by_goggles` from `response["news"]["mutated_by_goggles"]`
       - `source`
       - `breaking`
       - `is_live`
       - `age`
       - `url`
       - `title`
       - `description`
       - `extra_snippets`
   - `video_results`:
     - From `response.get("videos", {}).get("results", [])`:
       - `mutated_by_goggles` from `response["videos"]["mutated_by_goggles"]`
       - `url`
       - `title`
       - `description`
       - `age`
       - `thumbnail_url` from `thumbnail["src"]` if available
       - `duration` from `video["duration"]`
       - `view_count` from `video["views"]`
       - `creator` from `video["creator"]`
       - `publisher` from `video["publisher"]`
       - `tags` from `video["tags"]`

5. Extract summarizer key:

   - If `response.get("summarizer")` exists and has `key`, attach `summarizer_key` field.

6. Return response:

   - On success:

     ```json
     {
       "ok": true,
       "web_results": [...],
       "faq_results": [...],
       "discussions_results": [...],
       "news_results": [...],
       "video_results": [...],
       "summarizer_key": "..." or null,
       "raw_query_info": {
         "query": ...,            // selected subset of response.query fields
         "country": ...
       }
     }
     ```

   - On error (HTTP, JSON parse, missing web results, etc.):

     ```json
     {
       "ok": false,
       "error": "<human-readable message>",
       "details": { ... optional diagnostic info ... }
     }
     ```

### 5.4 Summarizer Function: `run_summarizer`

Function signature (internal):

- `def run_summarizer(params: dict) -> dict`

Expected `params`:

- `key: str` (required).
- `entity_info?: bool` (default `False`).
- `inline_references?: bool` (default `False`).

Polling parameters:

- `poll_interval_ms: int = 50` (optional override).
- `max_attempts: int = 20` (optional override).

Behavior:

1. Validate presence of `key`.
2. Implement polling loop:

   - For `attempt` from `1` to `max_attempts`:
     - Call `issue_request("summarizer", summarizer_params)` where:
       - `summarizer_params = { "key": key, "entity_info": ..., "inline_references": ... }`
     - If `response.get("status") == "complete"`:
       - Break and process summary.
     - Otherwise, sleep `poll_interval_ms` milliseconds.
   - If no complete response after all attempts:
     - Return `{ "ok": false, "error": "Unable to retrieve a Summarizer summary." }`.

3. Flatten summary:

   - Retrieve `summary_list = response.get("summary", [])`.
   - If list is empty or missing:
     - Return the same error payload.
   - Iterate over `summary_list`:
     - If `item["type"] == "token"` and `item["data"]` is a string:
       - Append to `summary_text`.
     - If `item["type"] == "inline_reference"`:
       - If `inline_references` is `True` and `item["data"]["url"]` is available:
         - Append `" (" + url + ")"` to `summary_text`.
       - Otherwise, ignore in the text.
     - Otherwise, ignore for flattened text.

4. Preserve rich structures:

   - `enrichments = response.get("enrichments")`
   - `followups = response.get("followups")`
   - `entities_infos = response.get("entities_infos")`

5. Return:

   - On success:

     ```json
     {
       "ok": true,
       "summary_text": "<flattened text>",
       "summary_raw": [...],         // original summary list
       "enrichments": { ... } or null,
       "followups": [...],
       "entities_infos": { ... } or null
     }
     ```

   - On error:

     ```json
     {
       "ok": false,
       "error": "Unable to retrieve a Summarizer summary."
     }
     ```

### 5.5 CLI Interface

Provide a simple CLI entry point in `brave_search.py`:

- Usage:

  - Web search:

    ```bash
    uv run scripts/brave_search.py web --params-json '<json>'
    ```

  - Summarizer:

    ```bash
    uv run scripts/brave_search.py summarizer --params-json '<json>'
    ```

- Implementation outline:

  - Parse `sys.argv`:
    - First positional argument: `mode` ∈ `{ "web", "summarizer" }`.
    - Option `--params-json` with JSON string representing `params`.
  - On `mode == "web"`:
    - Call `run_web_search(params)` and print JSON to stdout.
  - On `mode == "summarizer"`:
    - Call `run_summarizer(params)` and print JSON to stdout.
  - Exit with non-zero status on unhandled errors.

Document these commands in `SKILL.md` and references so that any agent can invoke them deterministically.

---

## 6. SKILL.md Design

### 6.1 Frontmatter

- YAML frontmatter:

  - `name: brave-search`
  - `description`: short, third-person description explaining:
    - The skill exposes Brave web search and summarizer via the Brave Search API.
    - It is suitable for high-quality web queries and succinct summaries.

### 6.2 Core Sections

1. **Purpose**
   - Brief description of:
     - Web search capability.
     - Summarizer capability.
     - Types of results returned.

2. **When to Use**
   - Web search:
     - Factual questions, current events, topic exploration, research tasks.
   - Summarizer:
     - When user explicitly requests a short, synthesized summary of multiple sources.
     - When summarization of Brave search results is desired (and subscription features permit).

3. **Configuration Requirements**
   - Explain that:
     - `BRAVE_SEARCH_API_KEY` must be set.
     - If applicable, how to store/manage the key using a secrets-management approach.
   - Mention that summarizer may require specific Brave AI plan (e.g., Pro AI).

4. **Workflows**

   - **A. Web Search without Summary**

     - Steps:
       1. Construct JSON with at least `"query"`.
       2. Optionally set filters (`country`, `freshness`, `safesearch`, etc.).
       3. Run `python scripts/brave_search.py web --params-json '<json>'`.
       4. Use `web_results` and other result lists to answer the user.

   - **B. Web Search with Summarizer Key**

     - Steps:
       1. Use same process as above but include `"summary": true`.
       2. Allow the script to handle `result_filter` semantics.
       3. Extract `summarizer_key` from the tool output.
       4. Use structured results like in (A) for detailed answers if needed.

   - **C. Summarization via Brave Summarizer**

     - Steps:
       1. After successful web search with `summary: true`, obtain `summarizer_key`.
       2. Build JSON:

          ```json
          {
            "key": "<summarizer_key>",
            "entity_info": false,
            "inline_references": true
          }
          ```

       3. Run:
          - `python scripts/brave_search.py summarizer --params-json '<json>'`
       4. Use `summary_text` as the main textual answer.
       5. Optionally incorporate:
          - `enrichments` (entities, images, QA).
          - `followups` (for suggesting follow-up questions).

5. **Error Handling and Fallbacks**

   - Describe how to interpret:

     - `ok: false` + `"No web results found"`:
       - Suggest query reformulation (simplify, broaden, or clarify).
     - `ok: false` from summarizer:
       - Fallback to manual summarization using `web_results`.
       - Possibly adjust filters or rerun search for more relevant sources.

6. **References**

   - Briefly mention:
     - `references/brave_web_search_params.md` – detailed parameter docs.
     - `references/brave_summarizer_workflow.md` – summarizer details.
     - `references/brave_search_examples.md` – usage examples.

---

## 7. Reference Document Design

### 7.1 `brave_web_search_params.md`

Contents:

- Overview of Brave Web Search endpoint used by the skill.
- Table or bullets for each key parameter:
  - Name, type, default, valid values, and notes.
- Notes on specific behaviors:
  - `summary` parameter and its impact on `result_filter`.
  - `goggles` behavior and requirement for HTTPS.
  - Relationship between `count`, `offset`, and pagination.
- A few example JSON payloads:
  - Generic knowledge query.
  - Location-sensitive query.
  - Freshness-constrained query.

### 7.2 `brave_summarizer_workflow.md`

Contents:

- Explanation of the end-to-end summarizer workflow:
  - Web search → summarizer key → summarizer call.
- Polling details:
  - Interval, number of attempts, what “complete” means.
- Structure of `summary_raw`:
  - `token`, `inline_reference`, and other possible types.
- Guidance on:
  - When to set `inline_references = true`.
  - How to interpret `enrichments`, `followups`, and `entities_infos`.

### 7.3 `brave_search_examples.md`

Contents:

- 2–4 worked examples, such as:

  - “Get current news on [topic] and summarize key points.”
  - “Compare [product A] and [product B] and provide a short summary.”
  - “Find key discussions around [topic] and summarize perspectives.”

- For each example:
  - Input user intent.
  - Example web search parameters JSON.
  - Example summarizer parameters JSON.
  - Illustrative snippets of outputs (`web_results`, `summary_text`).

---

## 8. Implementation Steps (High-Level)

1. **Scaffold directories**
   - Ensure `skills-akaihola/brave-search/` exists.
   - Create `scripts/`, `references/`, and `assets/` subdirectories.

2. **Implement `scripts/brave_search.py`**
   - Implement environment variable and configuration handling.
   - Implement `issue_request` helper.
   - Implement `run_web_search`.
   - Implement `run_summarizer`.
   - Add CLI entry point for `web` and `summarizer` modes.
   - Test locally with sample calls.

3. **Write `SKILL.md`**
   - Add YAML frontmatter.
   - Provide purpose, usage guidelines, workflows, and error handling.
   - Reference scripts and reference docs.

4. **Create reference documents in `references/`**
   - `brave_web_search_params.md`
   - `brave_summarizer_workflow.md`
   - `brave_search_examples.md`

5. **Review for context-efficiency and clarity**
   - Ensure SKILL.md is concise and procedural.
   - Move verbose details out of SKILL.md into references.
   - Confirm no redundant or conflicting information.

6. **Validate and package**
   - Run any available validation tooling for skills.
   - Package the skill into a zip if needed (e.g., `scripts/package_skill.py brave-search ./dist`).
   - Address any reported validation issues.

7. **Iterate**
   - After initial usage, capture feedback.
   - Refine:
     - Error messages.
     - Parameter defaults.
     - Examples and documentation.
   - Consider future extensions to other Brave endpoints (images, news, local, videos).