#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on tokmanni.fi via the Klevu search API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
    ./search.py "search term" --sort lth
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlencode

import httpx

API_BASE = "https://eucs11.ksearchnet.com/cloud-search/n-search/search"
API_KEY = "klevu-15488592134928913"


def search_products(
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    sort: str = "rel",
) -> dict:
    """Search Tokmanni products via the Klevu search API.

    Args:
        query: Search term.
        limit: Number of results to return.
        offset: Pagination offset (0-based).
        sort: Sort order — ``rel`` (relevance), ``lth`` (price low-to-high),
              ``htl`` (price high-to-low).

    Returns:
        Full API response as a dict with ``meta`` and ``result`` keys.
    """
    params = {
        "ticket": API_KEY,
        "term": query,
        "paginationStartsFrom": str(offset),
        "noOfResults": str(limit),
        "klevuSort": sort,
        "responseType": "json",
        "category": "KLEVU_PRODUCT",
        "visibility": "search",
        "showOutOfStockProducts": "true",
        "fetchMinMaxPrice": "true",
        "analyticsApiKey": API_KEY,
    }
    url = f"{API_BASE}?{urlencode(params)}"

    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict) -> list[dict]:
    """Extract the flat product list from the API response."""
    return raw.get("result", [])


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    price = p.get("salePrice") or p.get("price", "?")
    old_price = p.get("oldPrice", "")
    brand = p.get("item_brand_name", "")
    category = p.get("category", "")
    sku = p.get("sku", "")
    in_stock = p.get("inStock", "")
    url = p.get("url", "")

    parts = [f"  {idx}. {name}"]
    if brand:
        parts.append(f"     Brand: {brand}")
    if price and price != "?":
        price_str = f"{price} EUR"
        if old_price and old_price != price:
            price_str += f" (was {old_price} EUR)"
        parts.append(f"     Price: {price_str}")
    if in_stock:
        parts.append(f"     In stock: {in_stock}")
    if category:
        parts.append(f"     Category: {category}")
    if sku:
        parts.append(f"     SKU: {sku}")
    if url:
        parts.append(f"     URL: {url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on tokmanni.fi",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of results (default: 10)"
    )
    parser.add_argument(
        "--offset", type=int, default=0, help="Pagination offset, 0-based (default: 0)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json", help="Output raw JSON"
    )
    parser.add_argument(
        "--sort",
        default="rel",
        choices=["rel", "lth", "htl"],
        help="Sort: rel=relevance, lth=price low-to-high, htl=price high-to-low",
    )
    args = parser.parse_args()

    raw = search_products(
        args.query,
        limit=args.limit,
        offset=args.offset,
        sort=args.sort,
    )

    if args.output_json:
        json.dump(raw, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    products = extract_products(raw)
    if not products:
        print(f"No results for '{args.query}'.")
        return

    total = raw.get("meta", {}).get("totalResultsFound", "?")
    print(f"Results for '{args.query}' ({len(products)} shown, {total} total):\n")
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
