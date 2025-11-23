# Brave Search Skill – Implementation Checklist

## 1. Planning & Design

- [x] Review existing Brave MCP server implementation for web search and summarizer
- [x] Confirm initial scope: implement only `brave_web_search`-equivalent and `brave_summarizer`-equivalent behavior
- [x] Decide how closely to mirror existing parameter sets vs. simplifying for the skill

## 2. Skill Skeleton

- [x] Ensure `brave-search/` skill directory exists under `skills-akaihola/`
- [x] Add `SKILL.md` with:
  - [x] YAML frontmatter (`name`, `description`)
  - [x] Purpose and when-to-use sections
  - [x] High-level workflows for web search and summarizer
  - [x] Notes on configuration (API key, subscription requirements)
- [x] Remove or adapt any template/example files created by the skill initializer (if used)

## 3. Implementation Script (`scripts/brave_search.py`)

### 3.1 Dependencies & Configuration

- [x] Decide HTTP client library (e.g. `httpx`)
- [x] Add dependency using project conventions (e.g. `uv pip install httpx`)
- [x] Add PEP-723 inline script metadata block listing all Python dependencies
- [x] Ensure all documented script invocations use `uv run` rather than `python`
- [x] Implement configuration:
  - [x] Read Brave API key from environment (e.g. `BRAVE_SEARCH_API_KEY`)
  - [x] Define base URL and default headers (including `X-Subscription-Token`)
  - [x] Add basic validation/error if API key is missing

### 3.2 Core Request Helper

- [x] Implement `issue_request(endpoint: str, params: dict) -> dict`:
  - [x] Map endpoint names → URL paths:
    - [x] `"web"` → `/res/v1/web/search`
    - [x] `"summarizer"` → `/res/v1/summarizer/search`
  - [x] Convert input params to query string:
    - [x] Map `query` → `q`
    - [x] Implement `result_filter` behavior, including `summary == True` special case
    - [x] Implement `goggles` handling (single or list, HTTPS-only)
    - [x] Handle other supported fields (country, safesearch, freshness, etc.)
  - [x] Issue GET request
  - [x] On non-2xx responses, construct informative error including response body when possible

### 3.3 `brave_web_search` Function

- [x] Define function signature to accept a params dict mirroring MCP `QueryParams`
- [x] Call `issue_request("web", params)` and parse response
- [x] Implement result formatting:
  - [x] Extract `web.results` → list of `{ url, title, description, extra_snippets }`
  - [x] Extract `faq.results` → list of `{ question, answer, title, url }`
  - [x] Extract `discussions.results` → list of `{ mutated_by_goggles, url, data }`
  - [x] Extract `news.results` → list of `{ mutated_by_goggles, source, breaking, is_live, age, url, title, description, extra_snippets }`
  - [x] Extract `videos.results` → list of `{ mutated_by_goggles, url, title, description, age, thumbnail_url, duration, view_count, creator, publisher, tags }`
- [x] Capture summarizer key:
  - [x] Read `response.summarizer.key` if present and expose as `summarizer_key`
- [x] Define output JSON structure:
  - [x] `ok: true/false`
  - [x] `web_results`, `faq_results`, `discussions_results`, `news_results`, `video_results`
  - [x] `summarizer_key` (nullable)
  - [x] Optional `raw_query_info`
  - [x] `error` and optional `details` on failure
- [x] Mirror MCP behavior:
  - [x] If no web results, set `ok: false` and `error: "No web results found"`

### 3.4 `brave_summarizer` Function

- [x] Define function signature to accept:
  - [x] `key` (required)
  - [x] `entity_info` (optional, default `False`)
  - [x] `inline_references` (optional, default `False`)
  - [x] Optional poll timing overrides
- [x] Implement polling loop:
  - [x] Call `issue_request("summarizer", params)` repeatedly
  - [x] Break when `status == "complete"`
  - [x] Respect max attempts and interval; abort with error if not complete
- [x] Flatten `summary`:
  - [x] Concatenate tokens (`type == "token"`)
  - [x] When `type == "inline_reference"` and `inline_references == True`, append ` (URL)`
  - [x] Ignore unsupported types or handle gracefully
- [x] Include richer fields in output:
  - [x] `summary_text`
  - [x] `summary_raw`
  - [x] `enrichments`
  - [x] `followups`
  - [x] `entities_infos`
- [x] Define error output matching MCP semantics:
  - [x] `ok: false`
  - [x] `error: "Unable to retrieve a Summarizer summary."`

### 3.5 CLI Interface

- [x] Add CLI entrypoint in `brave_search.py`:
  - [x] Subcommand `"web"`:
    - [x] Accept `--params-json` argument
    - [x] Parse JSON → params dict
    - [x] Call web search function
    - [x] Print JSON result to stdout
  - [x] Subcommand `"summarizer"`:
    - [x] Accept `--params-json` argument
    - [x] Parse JSON → params dict
    - [x] Call summarizer function
    - [x] Print JSON result to stdout
- [x] Document basic CLI usage commands in `SKILL.md` using `uv run` (e.g. `uv run scripts/brave_search.py ...`)

## 4. Reference Documentation (`references/`)

- [x] `brave_web_search_params.md`:
  - [x] List all supported parameters, types, defaults, and notes
  - [x] Provide example web search payloads for common cases
- [x] `brave_summarizer_workflow.md`:
  - [x] Describe end-to-end flow from web search to summarizer
  - [x] Explain polling behavior and expected response structure
  - [x] Include example summarizer input and output
- [x] `brave_search_examples.md`:
  - [x] Add 2–3 end-to-end example scenarios:
    - [x] “Find and summarize latest news about a topic”
    - [x] “Compare two products and summarize key differences”
  - [x] Show representative JSON inputs and truncated outputs

## 5. Error Handling & Testing

- [x] Add defensive checks:
  - [x] Missing API key
  - [x] Invalid or missing required parameters (e.g. `query`, `key`)
- [ ] Manual tests for web search:
  - [ ] Simple query with defaults
  - [ ] Query with advanced filters (`safesearch`, `freshness`, `goggles`, etc.)
  - [ ] Case where no web results are returned
- [ ] Manual tests for summarizer:
  - [ ] Happy-path: summary returned successfully
  - [ ] Slow/never-completing summary (polling timeout path)
  - [ ] Behavior with `inline_references` on and off
- [ ] Validate that JSON outputs are well-structured and easy for a model to consume

## 6. Documentation Polish

- [x] Refine `SKILL.md` language:
  - [x] Use imperative style per skill guidelines
  - [x] Clearly explain when to use web search vs. summarizer
  - [x] Emphasize that summarizer requires a prior web search with `summary: true`
- [x] Make cross-references:
  - [x] Link SKILL.md workflows to the CLI commands
  - [x] Link to relevant files in `references/` from SKILL.md

## 7. Packaging & Validation

- [ ] Run skill validation script on `brave-search/`
- [ ] Fix any validation issues (frontmatter, structure, missing files)
- [ ] Package skill:
  - [ ] Run packaging command to produce distributable zip
  - [ ] Verify resulting archive structure and contents

## 8. Future Extensions (Optional)

- [ ] Plan support for additional Brave endpoints:
  - [ ] Images
  - [ ] Videos
  - [ ] News
  - [ ] Local POIs and descriptions
- [ ] Add TODO section or follow-up checklist to track these future enhancements