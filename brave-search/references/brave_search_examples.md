# Brave Search Example Scenarios

This reference shows how to combine the web and summarizer workflows for common research tasks. Each scenario includes:

1. **Intent** — what the user is trying to accomplish.
2. **Web search payload** — JSON for `uv run scripts/brave_search.py web`.
3. **Possible web output sketch** — representative excerpts of structured results.
4. **Summarizer payload** — JSON for `uv run scripts/brave_search.py summarizer`.
5. **Answer strategy** — how to blend structured data and summary text.

---

## Scenario 1: Track Breaking Tech News

**Intent:** “Find the latest developments in AI accelerator hardware and summarize the highlights.”

**Web Search Payload**

```json
{
  "query": "latest AI accelerator chips 2024",
  "summary": true,
  "freshness": "pw",
  "count": 8,
  "extra_snippets": true,
  "goggles": "https://goggles.brave.com/tech-news.xml"
}
```

**Representative Web Output**

- `web_results[0]`: Blog post detailing Nvidia’s newest data-center GPU with latency metrics.
- `news_results[0]`: Financial outlet covering AMD’s MI325 launch window.
- `faq_results`: Q&A entries explaining “What is an AI accelerator?” for framing the answer.

**Summarizer Payload**

```json
{
  "key": "<summarizer_key_from_web>",
  "inline_references": true,
  "entity_info": true
}
```

**Answer Strategy**

1. Start with `summary_text` to provide a concise narrative.
2. Mention 2–3 flagship announcements, citing URLs either from inline references or `news_results`.
3. Use `entities_infos` to spotlight companies (Nvidia, AMD, startups) and any performance benchmarks.

---

## Scenario 2: Compare Consumer Products

**Intent:** “Compare the latest flagship noise-cancelling headphones and highlight pros/cons.”

**Web Search Payload**

```json
{
  "query": "sony wh-1000xm6 vs bose quietcomfort ultra 2024 review",
  "summary": true,
  "result_filter": ["web", "news"],  // ignored once summary=true, but documents intent
  "count": 6,
  "search_lang": "en",
  "safesearch": "moderate"
}
```

**Representative Web Output**

- `web_results`: Tech review sites (The Verge, Rtings) with detailed pros/cons.
- `news_results`: Press releases or expert roundups mentioning release dates and firmware updates.
- `discussions_results`: Forums discussing comfort or battery-life anecdotes.

**Summarizer Payload**

```json
{
  "key": "<summarizer_key_from_web>",
  "inline_references": false,
  "entity_info": false
}
```

**Answer Strategy**

1. Use `summary_text` for a quick comparative paragraph.
2. Pull explicit specs (battery hours, price, weight) directly from `web_results` snippets.
3. Quote forum perspectives from `discussions_results` to capture user sentiment.

---

## Scenario 3: Rapid News Digest for Decision Makers

**Intent:** “Summarize regulatory developments affecting European EV subsidies over the past month.”

**Web Search Payload**

```json
{
  "query": "EU electric vehicle subsidies policy change 2024",
  "summary": true,
  "country": "eu",
  "ui_lang": "en",
  "freshness": "pm",
  "count": 10,
  "goggles": [
    "https://goggles.brave.com/eu-policy.xml",
    "https://goggles.brave.com/green-energy.xml"
  ],
  "extra_snippets": true
}
```

**Representative Web Output**

- `news_results`: Government press releases, EU parliament blogs, investigative journalism.
- `faq_results`: Clarifications regarding subsidy eligibility rules.
- `video_results`: Short explainers from policy think tanks.

**Summarizer Payload**

```json
{
  "key": "<summarizer_key_from_web>",
  "inline_references": true,
  "entity_info": true,
  "poll_interval_ms": 100,
  "max_attempts": 30
}
```

**Answer Strategy**

1. Lead with `summary_text` to outline policy shifts and timelines.
2. Reference specific sources by leveraging inline citations.
3. Use `entities_infos` to call out key agencies (e.g., European Commission, national ministries) and the role they play.
4. Point to `news_results` entries for deeper reading or official statements.

---

## Scenario 4: Discussion Mining for Sentiment Analysis

**Intent:** “Gather diverse perspectives on remote-first work culture changes.”

**Web Search Payload**

```json
{
  "query": "remote first work culture 2024 employee discussion",
  "summary": false,
  "discussions_only": true,      // not a real field; instead use result_filter
  "result_filter": ["discussions", "web"],
  "count": 5,
  "freshness": "pm",
  "extra_snippets": true
}
```

**Representative Web Output**

- `discussions_results`: Reddit, Hacker News, company blogs debating pros/cons.
- `web_results`: Research articles and HR consultancy pieces.

**Summarizer Step**

- If a synthesis is later required, rerun web search with `summary: true` to acquire a `summarizer_key`, then call the summarizer.

**Answer Strategy**

1. Extract themes directly from `discussions_results` (e.g., burnout concerns, collaboration tools).
2. Augment with `web_results` for data-backed viewpoints.
3. Highlight contrasting opinions and cite URLs explicitly since no summarizer output is available.

---

## Scenario 5: End-to-End Example (News Followed by Summary)

1. **Web Search**

```json
{
  "query": "global wheat crop forecast 2024 drought impact",
  "summary": true,
  "freshness": "pm",
  "country": "us",
  "count": 8
}
```

2. **Sample Web Response Notes**
   - `news_results`: FAO updates, Reuters coverage, regional agricultural boards.
   - `web_results`: Academic blogs discussing yield projections.
   - `summarizer_key`: e.g., `summ-123abc`.

3. **Summarizer Call**

```json
{
  "key": "summ-123abc",
  "inline_references": true
}
```

4. **Composing the Final Answer**
   - Begin with `summary_text` (e.g., “Forecasts predict moderate decline due to XYZ…”).
   - Cite specific regions or data points gleaned from `news_results`.
   - Use inline references to point to FAO and Reuters articles for credibility.
   - Provide follow-up suggestions (e.g., “Consider checking fertilizer price trends”) if `followups` contains meaningful prompts.

---

Use these examples as templates when training agents or documenting SOPs. Mix and match patterns to suit different verticals—current events, competitive research, sentiment analysis, or compliance monitoring. ```
