#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on verkkokauppa.com via the Verkkokauppa search API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
    ./search.py "search term" --sort price
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

import httpx

API_BASE = "https://search.service.verkkokauppa.com/fi/api/v1/product-search"
SITE_BASE = "https://www.verkkokauppa.com"
# Default API page size; we slice client-side for smaller limits
API_PAGE_SIZE = 48


def search_products(
    query: str,
    *,
    page: int = 1,
    page_size: int = API_PAGE_SIZE,
    sort: str = "-score",
) -> dict:
    """Search Verkkokauppa.com products via the search API.

    Args:
        query: Search term.
        page: Page number (1-based).
        page_size: Results per page (default: 48).
        sort: Sort order — ``-score`` (relevance), ``price`` (low-to-high),
              ``-price`` (high-to-low), ``-popularity``, ``-rating``,
              ``-releaseDate``, ``-discountPercentage``.

    Returns:
        Full API response as a dict with ``data``, ``meta``, and optionally
        ``included`` keys.
    """
    session_id = str(uuid.uuid4())

    # The API uses JSON:API filter syntax: filter[q] for query
    params = {
        "sessionId": session_id,
        "private": "true",
        "filter[q]": query,
        "page[size]": str(page_size),
        "page[number]": str(page),
        "sort": sort,
    }

    resp = httpx.get(
        API_BASE,
        params=params,
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict, limit: int = 10) -> list[dict]:
    """Extract a flat list of products from the JSON:API response.

    Args:
        raw: Full API response dict.
        limit: Maximum number of products to return.

    Returns a list of dicts with simplified keys.
    """
    products = []
    for item in raw.get("data", [])[:limit]:
        attrs = item.get("attributes", {})
        price_info = attrs.get("price", {})
        rating_info = attrs.get("rating", {})
        images = attrs.get("images", [])
        relationships = item.get("relationships", {})

        category_data = relationships.get("category", {}).get("data", {})

        product = {
            "product_id": item.get("id", ""),
            "name": attrs.get("name", ""),
            "price_current": price_info.get("current"),
            "price_current_formatted": price_info.get("currentFormatted", ""),
            "price_original": price_info.get("original"),
            "discount_percent": price_info.get("discountPercentage"),
            "category": category_data.get("id", ""),
            "rating": rating_info.get("averageOverallRating"),
            "review_count": rating_info.get("reviewCount", 0),
            "url": f"{SITE_BASE}{attrs.get('href', '')}",
            "image": images[0].get("orig", "") if images else "",
            "bullet_points": attrs.get("bulletPoints", []),
            "description": attrs.get("descriptionShort", ""),
        }
        products.append(product)
    return products


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    price = p.get("price_current")
    original = p.get("price_original")
    discount = p.get("discount_percent")
    category = p.get("category", "")
    rating = p.get("rating")
    review_count = p.get("review_count", 0)
    url = p.get("url", "")

    parts = [f"  {idx}. {name}"]
    if price is not None:
        price_str = f"{price} EUR"
        if original and original != price:
            price_str += f" (was {original} EUR"
            if discount:
                price_str += f", -{discount}%"
            price_str += ")"
        parts.append(f"     Price: {price_str}")
    if rating is not None:
        parts.append(f"     Rating: {rating}/5 ({review_count} reviews)")
    if category:
        parts.append(f"     Category: {category}")
    if url:
        parts.append(f"     URL: {url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on verkkokauppa.com",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of results (default: 10)"
    )
    parser.add_argument(
        "--page", type=int, default=1, help="Page number, 1-based (default: 1)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json", help="Output raw JSON"
    )
    parser.add_argument(
        "--sort",
        default="-score",
        choices=["-score", "price", "-price", "-popularity", "-rating",
                 "-releaseDate", "-discountPercentage"],
        help="Sort order (default: -score = relevance)",
    )
    args = parser.parse_args()

    raw = search_products(
        args.query,
        page=args.page,
        sort=args.sort,
    )

    if args.output_json:
        json.dump(raw, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    products = extract_products(raw, limit=args.limit)
    if not products:
        print(f"No results for '{args.query}'.")
        return

    total = raw.get("meta", {}).get("totalResults", "?")
    print(f"Results for '{args.query}' ({len(products)} shown, {total} total):\n")
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
