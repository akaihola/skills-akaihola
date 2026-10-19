---
name: ecb-rates
description: Fetch USD/EUR currency exchange rates from European Central Bank (ECB) and save to CSV. Supports a requested historical year and currency conversion guidance.
---

# ECB Currency Rates Skill

Fetches historical USD-EUR exchange rates from ECB's official data.

## Usage

From the repository root (or substitute the absolute script path):

```bash
uv run ecb-rates/fetch_ecb_rates.py --help
uv run ecb-rates/fetch_ecb_rates.py 2024 rates-2024.csv
```

The CLI accepts positional `[YEAR] [OUTPUT]`. Both are optional: omitting the year
retains the fixed historical default **2025**, and omitting the output writes
`valuuttakurssit_YEAR.csv` in the current directory. The default never advances
with the calendar; pass the requested year explicitly for other exports. A year
without published USD observations produces a header-only CSV.

Requires Python 3.11+ and `defusedxml` (declared in the script's PEP 723 metadata;
`uv run` installs it). With an environment containing that dependency, the same
arguments work with `python ecb-rates/fetch_ecb_rates.py`. Help parses and exits
before fetching. A rates export requires network access to ECB.

## How it works

1. Downloads ECB's complete historical XML (eurofxref-hist.xml)
2. Extracts USD rates for each day
3. Orders observations from oldest to newest and saves CSV with columns:
   - date (DD.MM.YYYY format)
   - rate (USD per 1 EUR, ECB standard)

## Conversion Guide

**USD → EUR**: Divide USD amount by rate
**EUR → USD**: Multiply EUR amount by rate

Example: 1000 USD at rate 1.1668 = 1000 / 1.1668 = 857.04 EUR

Note: ECB rates are expressed as USD per 1 EUR. When converting:
- If you have USD and want EUR: **divide** by rate
- If you have EUR and want USD: **multiply** by rate

## Offline validation

```bash
uv run --no-project --with pytest --with defusedxml pytest ecb-rates/tests -q
```

Tests use invented XML observations and block live requests, including for CLI
help and invalid arguments.
