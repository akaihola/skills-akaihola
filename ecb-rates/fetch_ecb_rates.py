# Copyright (c) 2026 Antti Kaihola
"""Fetch USD/EUR currency exchange rates from ECB and save to CSV.

Usage: uv run --with defusedxml fetch_ecb_rates.py [year] [output_file]
"""

from __future__ import annotations

import csv
import operator
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import defusedxml.ElementTree


def fetch_ecb_rates(year: int = 2025, output_file: str | None = None) -> list[dict]:
    """Fetch all USD/EUR rates for specified year from ECB.

    Args:
        year: Year to fetch rates for (default: 2025)
        output_file: Output CSV file path (default: valuuttakurssit_{year}.csv)

    Returns:
        List of dictionaries containing date and rate

    """
    if output_file is None:
        output_file = f"valuuttakurssit_{year}.csv"

    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
        data = response.read()

    root = defusedxml.ElementTree.fromstring(data)

    ns = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}

    rates: list[dict] = []
    for cube in root.findall(".//ecb:Cube[@time]", ns):
        date_str = cube.get("time")
        if not date_str:
            continue
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)

        # Filter for requested year
        if date_obj.year != year:
            continue

        date_formatted = date_obj.strftime("%d.%m.%Y")

        # Find USD rate
        for rate_cube in cube:
            if rate_cube.get("currency") == "USD":
                rate = float(rate_cube.get("rate"))
                rates.append({
                    "date": date_formatted,
                    "rate": rate,
                    "date_obj": date_obj,
                })
                break

    # Sort by date
    rates.sort(key=operator.itemgetter("date_obj"))

    # Save to CSV using Path
    output_path = Path(output_file)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "rate"])
        for r in rates:
            writer.writerow([r["date"], r["rate"]])

    return rates


if __name__ == "__main__":
    MIN_ARGS_YEAR = 1
    MIN_ARGS_OUTPUT = 2
    year = int(sys.argv[1]) if len(sys.argv) > MIN_ARGS_YEAR else 2025
    output = sys.argv[2] if len(sys.argv) > MIN_ARGS_OUTPUT else None
    fetch_ecb_rates(year, output)
