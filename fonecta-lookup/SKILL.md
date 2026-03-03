---
name: fonecta-lookup
description: Reverse-lookup Finnish phone numbers via Fonecta Caller (fonecta.fi). Use when given a list of Finnish mobile or landline numbers and asked to find the associated person or company names. Requires a Fonecta account with CallerPro subscription and Playwright installed.
---

# Purpose

Look up Finnish phone numbers on [Fonecta Caller](https://www.fonecta.fi/) and return a `phone → name` map. Fonecta is the primary Finnish directory service; it covers most publicly listed personal and business numbers.

The script uses Playwright to log in, navigate to each number's search page, and extract results from the `__NEXT_DATA__` JSON blob embedded in the SSR-rendered HTML. No undocumented API calls are needed beyond what the browser does naturally.

# When to Use

Use this skill when you have a list of Finnish phone numbers (starting with `+358` or `0`) and need to resolve them to names — for example to enrich a WhatsApp participant list, a call log, or any dataset that contains bare phone numbers.

Do not use for non-Finnish numbers; Fonecta only covers Finland.

# Prerequisites

<prerequisites>
- Playwright browsers must be installed. Check `$PLAYWRIGHT_BROWSERS_PATH`.
- Set `FONECTA_EMAIL` and `FONECTA_PASSWORD` in the environment before running. Never hard-code credentials.
- A CallerPro subscription is required for unlimited searches (`hasSearch: true` in the user object). A free account may be rate-limited or blocked.
- Python ≥ 3.11 and `uv` must be available.
</prerequisites>

# Workflow

<workflow>

## 1. Prepare the phone list

Normalise all numbers to bare E.164 digits without a leading `+` (e.g. `358401234567`). The script accepts any format — `+358…`, `0…`, `358…` — and normalises internally, but a clean list avoids surprises.

Write the numbers to a file, one per line, or pass them directly with `--phones`.

## 2. Run the lookup

```bash
FONECTA_EMAIL=user@example.com FONECTA_PASSWORD=secret \
    uv run scripts/fonecta_lookup.py \
        --phones-file phones.txt \
        --output fonecta-names.yaml
```

Or with inline numbers:

```bash
FONECTA_EMAIL=... FONECTA_PASSWORD=secret \
    uv run scripts/fonecta_lookup.py \
        --phones 358401234567 358407654321 \
        --output fonecta-names.yaml
```

The script is **incremental**: if `--output` already exists, previously resolved numbers are skipped. Reruns after a partial failure only look up the remainder.

## 3. Read the results

`fonecta-names.yaml` contains a mapping of normalised E.164 digits → name string (or `null` if not found):

```yaml
358401234567: Matti Meikäläinen
358407654321: Yritys Oy
358409999999: null   # not found in Fonecta
```

Pass this file to whatever downstream process needs the names.

</workflow>

# How Results Are Extracted

The search page `https://www.fonecta.fi/haku/<local-number>` is a Next.js SSR page. The search results are embedded in the page HTML as a `__NEXT_DATA__` JSON blob populated by React Query (`dehydratedState`). The script parses this directly — no additional API call is needed.

The relevant path inside `__NEXT_DATA__`:

```
props.pageProps.dehydratedState.queries[]
  → queryKey[0] == "search"
  → state.data.results[0].displayName
```

See [references/fonecta-api.md](references/fonecta-api.md) for full API details, the authentication flow, and notes on rate limiting.

# Login Flow Detail

The login form is a two-step MUI Dialog:

1. Accept the OneTrust cookie consent banner.
2. Click the "Kirjaudu sisään" nav button (opens the dialog).
3. Enter email → click "Seuraava".
4. Enter password → click the "Kirjaudu sisään" button **scoped to the dialog** (the nav-bar button is visually blocked by the dialog overlay and times out if clicked directly).

# Known Limitations

- Numbers that are unlisted, prepaid SIMs, or business lines not registered with Fonecta return `null`. Approximately 25 % of Finnish mobile numbers are not in the directory.
- The `fofisuggest` autocomplete endpoint consistently returns empty results even for numbers that the full search page resolves; ignore it.
- The script runs headless. If Fonecta introduces bot-detection measures, switching to `headless=False` may help.
- Session tokens expire after ~30 minutes. For batches longer than ~200 numbers, add token refresh logic (see [references/fonecta-api.md](references/fonecta-api.md)).
