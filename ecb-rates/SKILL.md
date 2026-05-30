---
name: ecb-rates
description: Fetch USD/EUR currency exchange rates from European Central Bank (ECB) and save to CSV. Provides 2025 rates and conversion guidance.
---

# ECB Currency Rates Skill

Fetches historical USD-EUR exchange rates from ECB's official data.

## Usage

`fetch-rates [YEAR]` - Gets daily rates for specified year (default: 2025)

## How it works

1. Downloads ECB's complete historical XML (eurofxref-hist.xml)
2. Extracts USD rates for each day
3. Saves to `valuuttakurssit_YYYY.csv` with columns:
   - date (DD.MM.YYYY format)
   - rate (USD per 1 EUR, ECB standard)

## Conversion Guide

**USD → EUR**: Divide USD amount by rate
**EUR → USD**: Multiply EUR amount by rate

Example: 1000 USD at rate 1.1668 = 1000 / 1.1668 = 857.04 EUR

Note: ECB rates are expressed as USD per 1 EUR. When converting:
- If you have USD and want EUR: **divide** by rate
- If you have EUR and want USD: **multiply** by rate
