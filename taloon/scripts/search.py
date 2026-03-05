#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on taloon.com via the Loop54 search API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
    ./search.py "search term" --offset 20
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

import httpx

API_URL = "https://taloon-fi-prod.54proxy.com/search"
SITE_BASE = "https://www.taloon.com"
DEFAULT_LIMIT = 10


def search_products(
    query: str,
    *,
    limit: int = 10,
    skip: int = 0,
) -> dict:
    """Search Taloon.com products via the Loop54 search API."""
    payload = {
        "query": query,
        "resultsOptions": {
            "skip": skip,
            "take": limit,
        },
    }

    resp = httpx.post(
        API_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Api-Version": "V3",
            "User-Id": str(uuid.uuid4()),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict, limit: int = 10) -> list[dict]:
    """Extract flat product list from the Loop54 response."""
    results = raw.get("results", {})
    items = results.get("items", [])
    products = []
    for item in items[:limit]:
        attrs = {}
        for attr in item.get("attributes", []):
            attrs[attr["name"]] = attr["values"][0] if attr.get("values") else None
        products.append(attrs)
    return products


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    brand = p.get("brand", "")
    price = p.get("price", "")
    list_price = p.get("list_price", "")
    availability = p.get("availability", "")
    url = p.get("product_url", "")

    parts = [f"  {idx}. {name}"]
    if brand:
        parts.append(f"     Brand: {brand}")
    if price:
        price_str = f"{price} EUR"
        if list_price and str(list_price) != str(price):
            price_str += f" (was {list_price} EUR)"
        parts.append(f"     Price: {price_str}")
    if availability:
        parts.append(f"     Availability: {availability}")
    if url:
        full_url = url if url.startswith("http") else f"{SITE_BASE}{url}"
        parts.append(f"     URL: {full_url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on taloon.com",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of results (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of results to skip (default: 0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON",
    )
    args = parser.parse_args()

    raw = search_products(args.query, limit=args.limit, skip=args.offset)

    if args.output_json:
        json.dump(raw, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    products = extract_products(raw, limit=args.limit)
    if not products:
        print(f"No results for '{args.query}'.")
        return

    total = raw.get("results", {}).get("count", "?")
    print(
        f"Results for '{args.query}' ({len(products)} shown, {total} total):\n"
    )
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
