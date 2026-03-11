#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on k-rauta.fi via the K-Rauta search API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

API_URL = "https://www.k-rauta.fi/api/search"
SITE_BASE = "https://www.k-rauta.fi"
DEFAULT_LIMIT = 10


def search_products(
    query: str,
    *,
    limit: int = 100,
) -> dict:
    """Search K-Rauta products via the backend search API.

    Note: The v1 API always returns up to 100 results. Limit is applied
    client-side in extract_products().
    """
    resp = httpx.post(
        API_URL,
        json={"query": query},
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict, limit: int = 10) -> list[dict]:
    """Extract flat product list from the K-Rauta response."""
    results = raw.get("results", [])
    products = []
    for item in results[:limit]:
        # Build image URL
        images = item.get("images", [])
        image_url = ""
        if images:
            image_url = images[0].get("url", "")
            if image_url and not image_url.startswith("http"):
                image_url = f"https://public.keskofiles.com{image_url}"

        # Build product URL from EAN/id
        product_id = item.get("id", "")
        ean = item.get("ean", "")

        # Extract category from salesCategories
        categories = []
        for chain in item.get("salesCategories", []):
            for cat in sorted(chain, key=lambda c: c.get("level", 0)):
                categories.append(cat.get("name", ""))

        products.append({
            "id": product_id,
            "ean": ean,
            "name": item.get("name", ""),
            "brand": item.get("brand", ""),
            "description": item.get("description", ""),
            "categories": categories,
            "is_new": item.get("isNewProduct", False),
            "is_outgoing": item.get("isOutgoing", False),
            "image_url": image_url,
            "ratings": item.get("ratings", {}),
        })
    return products


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    brand = p.get("brand", "")
    ean = p.get("ean", "")
    is_new = p.get("is_new", False)
    is_outgoing = p.get("is_outgoing", False)
    ratings = p.get("ratings", {})

    parts = [f"  {idx}. {name}"]
    if brand:
        parts.append(f"     Brand: {brand}")
    if ean:
        parts.append(f"     EAN: {ean}")
    if ratings and ratings.get("reviewCount", 0) > 0:
        parts.append(
            f"     Rating: {ratings.get('avgScore', '?')}/5 "
            f"({ratings['reviewCount']} reviews)"
        )
    description = p.get("description", "")
    categories = p.get("categories", [])
    if categories:
        parts.append(f"     Category: {' > '.join(categories[:3])}")
    if description:
        # Truncate description
        short = description[:120].rstrip()
        if len(description) > 120:
            short += "..."
        parts.append(f"     Description: {short}")
    flags = []
    if is_new:
        flags.append("NEW")
    if is_outgoing:
        flags.append("OUTGOING")
    if flags:
        parts.append(f"     Flags: {', '.join(flags)}")
    # Note: K-Rauta API v1 does not include prices in search results
    parts.append("     ⚠ Price: check on k-rauta.fi")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on k-rauta.fi",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of results (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON",
    )
    args = parser.parse_args()

    raw = search_products(args.query)

    if args.output_json:
        json.dump(raw, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    products = extract_products(raw, limit=args.limit)
    if not products:
        print(f"No results for '{args.query}'.")
        return

    total = raw.get("totalHits", "?")
    print(
        f"Results for '{args.query}' ({len(products)} shown, {total} total):\n"
    )
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
