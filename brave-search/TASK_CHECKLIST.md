# Brave Search Skill – Implementation Checklist

## 1. Planning & Design

- [ ] Review existing Brave MCP server implementation for web search and summarizer
- [ ] Confirm initial scope: implement only `brave_web_search`-equivalent and `brave_summarizer`-equivalent behavior
- [ ] Decide how closely to mirror existing parameter sets vs. simplifying for the skill

## 2. Skill Skeleton

- [ ] Ensure `brave-search/` skill directory exists under `skills-akaihola/`
- [ ] Add `SKILL.md` with:
  - [ ] YAML frontmatter (`name`, `description`)
  - [ ] Purpose and when-to-use sections
  - [ ] High-level workflows for web search and summarizer
  - [ ] Notes on configuration (API key, subscription requirements)
- [ ] Remove or adapt any template/example files created by the skill initializer (if used)

## 3. Implementation Script (`scripts/brave_search.py`)

### 3.1 Dependencies & Configuration

- [ ] Decide HTTP client library (e.g. `httpx`)
- [ ] Add dependency using project conventions (e.g. `uv pip install httpx`)
- [ ] Add PEP-723 inline script metadata block listing all Python dependencies
- [ ] Ensure all documented script invocations use `uv run` rather than `python`
- [ ] Implement configuration:
  - [ ] Read Brave API key from environment (e.g. `BRAVE_SEARCH_API_KEY`)
  - [ ] Define base URL and default headers (including `X-Subscription-Token`)
  - [ ] Add basic validation/error if API key is missing

### 3.2 Core Request Helper

- [ ] Implement `issue_request(endpoint: str, params: dict) -> dict`:
  - [ ] Map endpoint names → URL paths:
    - [ ] `"web"` → `/res/v1/web/search`
    - [ ] `"summarizer"` → `/res/v1/summarizer/search`
  - [ ] Convert input params to query string:
    - [ ] Map `query` → `q`
    - [ ] Implement `result_filter` behavior, including `summary == True` special case
    - [ ] Implement `goggles` handling (single or list, HTTPS-only)
    - [ ] Handle other supported fields (country, safesearch, freshness, etc.)
  - [ ] Issue GET request
  - [ ] On non-2xx responses, construct informative error including response body when possible

### 3.3 `brave_web_search` Function

- [ ] Define function signature to accept a params dict mirroring MCP `QueryParams`
- [ ] Call `issue_request("web", params)` and parse response
- [ ] Implement result formatting:
  - [ ] Extract `web.results` → list of `{ url, title, description, extra_snippets }`
  - [ ] Extract `faq.results` → list of `{ question, answer, title, url }`
  - [ ] Extract `discussions.results` → list of `{ mutated_by_goggles, url, data }`
  - [ ] Extract `news.results` → list of `{ mutated_by_goggles, source, breaking, is_live, age, url, title, description, extra_snippets }`
  - [ ] Extract `videos.results` → list of `{ mutated_by_goggles, url, title, description, age, thumbnail_url, duration, view_count, creator, publisher, tags }`
- [ ] Capture summarizer key:
  - [ ] Read `response.summarizer.key` if present and expose as `summarizer_key`
- [ ] Define output JSON structure:
  - [ ] `ok: true/false`
  - [ ] `web_results`, `faq_results`, `discussions_results`, `news_results`, `video_results`
  - [ ] `summarizer_key` (nullable)
  - [ ] Optional `raw_query_info`
  - [ ] `error` and optional `details` on failure
- [ ] Mirror MCP behavior:
  - [ ] If no web results, set `ok: false` and `error: "No web results found"`

### 3.4 `brave_summarizer` Function

- [ ] Define function signature to accept:
  - [ ] `key` (required)
  - [ ] `entity_info` (optional, default `False`)
  - [ ] `inline_references` (optional, default `False`)
  - [ ] Optional poll timing overrides
- [ ] Implement polling loop:
  - [ ] Call `issue_request("summarizer", params)` repeatedly
  - [ ] Break when `status == "complete"`
  - [ ] Respect max attempts and interval; abort with error if not complete
- [ ] Flatten `summary`:
  - [ ] Concatenate tokens (`type == "token"`)
  - [ ] When `type == "inline_reference"` and `inline_references == True`, append ` (URL)`
  - [ ] Ignore unsupported types or handle gracefully
- [ ] Include richer fields in output:
  - [ ] `summary_text`
  - [ ] `summary_raw`
  - [ ] `enrichments`
  - [ ] `followups`
  - [ ] `entities_infos`
- [ ] Define error output matching MCP semantics:
  - [ ] `ok: false`
  - [ ] `error: "Unable to retrieve a Summarizer summary."`

### 3.5 CLI Interface

- [ ] Add CLI entrypoint in `brave_search.py`:
  - [ ] Subcommand `"web"`:
    - [ ] Accept `--params-json` argument
    - [ ] Parse JSON → params dict
    - [ ] Call web search function
    - [ ] Print JSON result to stdout
  - [ ] Subcommand `"summarizer"`:
    - [ ] Accept `--params-json` argument
    - [ ] Parse JSON → params dict
    - [ ] Call summarizer function
    - [ ] Print JSON result to stdout
- [ ] Document basic CLI usage commands in `SKILL.md` using `uv run` (e.g. `uv run scripts/brave_search.py ...`)

## 4. Reference Documentation (`references/`)

- [ ] `brave_web_search_params.md`:
  - [ ] List all supported parameters, types, defaults, and notes
  - [ ] Provide example web search payloads for common cases
- [ ] `brave_summarizer_workflow.md`:
  - [ ] Describe end-to-end flow from web search to summarizer
  - [ ] Explain polling behavior and expected response structure
  - [ ] Include example summarizer input and output
- [ ] `brave_search_examples.md`:
  - [ ] Add 2–3 end-to-end example scenarios:
    - [ ] “Find and summarize latest news about a topic”
    - [ ] “Compare two products and summarize key differences”
  - [ ] Show representative JSON inputs and truncated outputs

## 5. Error Handling & Testing

- [ ] Add defensive checks:
  - [ ] Missing API key
  - [ ] Invalid or missing required parameters (e.g. `query`, `key`)
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

- [ ] Refine `SKILL.md` language:
  - [ ] Use imperative style per skill guidelines
  - [ ] Clearly explain when to use web search vs. summarizer
  - [ ] Emphasize that summarizer requires a prior web search with `summary: true`
- [ ] Make cross-references:
  - [ ] Link SKILL.md workflows to the CLI commands
  - [ ] Link to relevant files in `references/` from SKILL.md

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