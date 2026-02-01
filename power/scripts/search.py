#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on power.fi via their REST API.

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

import httpx

API_BASE = "https://www.power.fi/api/v2/productlists"

SORT_MAP = {
    "rel": 5,
    "lth": 1,
    "htl": 2,
    "az": 3,
    "za": 4,
}


def search_products(
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    sort: str = "rel",
) -> dict:
    """Search Power.fi products.

    Args:
        query: Search term.
        limit: Number of results to return.
        offset: Pagination offset (0-based).
        sort: Sort order — ``rel`` (relevance), ``lth`` (price low-to-high),
              ``htl`` (price high-to-low), ``az`` (name A–Z), ``za`` (name Z–A).

    Returns:
        Full API response as a dict.
    """
    params = {
        "q": query,
        "size": str(limit),
        "from": str(offset),
        "s": str(SORT_MAP.get(sort, 5)),
    }

    resp = httpx.get(API_BASE, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict) -> list[dict]:
    """Extract the flat product list from the API response."""
    return raw.get("products", [])


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    title = p.get("title", "?")
    manufacturer = p.get("manufacturerName", "")
    price = p.get("price")
    prev_price = p.get("previousPrice")
    category = p.get("categoryName", "")
    stock = p.get("stockCount", 0)
    stores_stock = p.get("storesStockCount", 0)
    url = p.get("url", "")
    barcode = p.get("barcode", "")
    review = p.get("productReview") or {}
    rating = review.get("overallAverageRating")
    review_count = review.get("overallTotalReviewCount")

    parts = [f"  {idx}. {title}"]
    if manufacturer:
        parts.append(f"     Brand: {manufacturer}")
    if price is not None:
        price_str = f"{price} EUR"
        if prev_price is not None and prev_price != price:
            price_str += f" (was {prev_price} EUR)"
        parts.append(f"     Price: {price_str}")
    if stock or stores_stock:
        parts.append(f"     Stock: {stock} online, {stores_stock} in stores")
    if rating is not None and review_count is not None:
        parts.append(f"     Rating: {rating}/5 ({review_count} reviews)")
    if category:
        parts.append(f"     Category: {category}")
    if barcode:
        parts.append(f"     Barcode: {barcode}")
    if url:
        parts.append(f"     URL: https://www.power.fi{url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on power.fi",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of results (default: 10)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Pagination offset, 0-based (default: 0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON",
    )
    parser.add_argument(
        "--sort",
        default="rel",
        choices=["rel", "lth", "htl", "az", "za"],
        help="Sort: rel=relevance, lth=price low-to-high, htl=price high-to-low, "
        "az=name A-Z, za=name Z-A",
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

    total = raw.get("totalProductCount", "?")
    print(f"Results for '{args.query}' ({len(products)} shown, {total} total):\n")
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
