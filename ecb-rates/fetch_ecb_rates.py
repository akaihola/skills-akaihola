# Copyright (c) 2026 Antti Kaihola
"""Fetch USD/EUR currency exchange rates from ECB and save to CSV.

Usage: uv run ecb-rates/fetch_ecb_rates.py [YEAR] [OUTPUT]
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["defusedxml>=0.7.1"]
# ///

from __future__ import annotations

import argparse
import csv
import operator
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

        if date_obj.year != year:
            continue

        date_formatted = date_obj.strftime("%d.%m.%Y")

        for rate_cube in cube:
            if rate_cube.get("currency") == "USD":
                rate = float(rate_cube.get("rate"))
                rates.append(
                    {
                        "date": date_formatted,
                        "rate": rate,
                        "date_obj": date_obj,
                    }
                )
                break

    rates.sort(key=operator.itemgetter("date_obj"))

    output_path = Path(output_file)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "rate"])
        for r in rates:
            writer.writerow([r["date"], r["rate"]])

    return rates


def main() -> None:
    """Parse the documented CLI before fetching historical rates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "year",
        type=int,
        nargs="?",
        default=2025,
        metavar="YEAR",
        help="historical year to export (default: 2025; never rolls forward)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        metavar="OUTPUT",
        help="output CSV path (default: valuuttakurssit_YEAR.csv)",
    )
    args = parser.parse_args()
    fetch_ecb_rates(args.year, args.output)


if __name__ == "__main__":
    main()
