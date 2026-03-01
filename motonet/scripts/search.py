#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on motonet.fi via the Motonet search API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
    ./search.py "search term" --page 2
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote as url_quote

import httpx

API_URL = "https://www.motonet.fi/api/search/products"
SITE_BASE = "https://www.motonet.fi"
# The API enforces pageSize=30; we slice client-side for smaller limits
API_PAGE_SIZE = 30


def search_products(
    query: str,
    *,
    limit: int = 10,
    page: int = 1,
) -> dict:
    """Search Motonet products via the internal search API.

    Args:
        query: Search term.
        limit: Number of results to return (max 30).
        page: Page number (1-based).

    Returns:
        Full API response as a dict with ``products``, ``pagination``,
        and ``facets`` keys.
    """
    payload = {
        "q": query,
        "page": page,
        "pageSize": API_PAGE_SIZE,
    }

    resp = httpx.post(
        f"{API_URL}?locale=fi",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict, limit: int = 10) -> list[dict]:
    """Extract the flat product list from the API response.

    Args:
        raw: Full API response dict.
        limit: Maximum number of products to return.

    Returns:
        List of product dicts, each with a computed ``url`` field.
    """
    products = raw.get("products", [])
    result = []
    for p in products[:limit]:
        # Build product URL from name and ID
        slug = _slugify(p.get("name", ""))
        product_id = p.get("id", "")
        if slug and product_id:
            p["url"] = f"{SITE_BASE}/tuote/{slug}?product={product_id}"
        else:
            p["url"] = ""
        result.append(p)
    return result


def _slugify(text: str) -> str:
    """Convert product name to URL-friendly slug."""
    import re
    import unicodedata

    # Normalize unicode characters
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase, replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-")


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    price = p.get("price", "?")
    brand = p.get("brand", "")
    category = p.get("categoryName", "")
    product_id = p.get("id", "")
    url = p.get("url", "")
    webshop_only = p.get("webshopOnly", False)

    parts = [f"  {idx}. {name}"]
    if brand:
        parts.append(f"     Brand: {brand}")
    if price and price != "?":
        parts.append(f"     Price: {price} EUR")
    if category:
        parts.append(f"     Category: {category}")
    if product_id:
        parts.append(f"     Code: {product_id}")
    if webshop_only:
        parts.append(f"     ⚠ Webshop only")
    if url:
        parts.append(f"     URL: {url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on motonet.fi",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of results (default: 10, max: 30)"
    )
    parser.add_argument(
        "--page", type=int, default=1, help="Page number, 1-based (default: 1)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json", help="Output raw JSON"
    )
    args = parser.parse_args()

    limit = min(args.limit, API_PAGE_SIZE)

    raw = search_products(
        args.query,
        limit=limit,
        page=args.page,
    )

    if args.output_json:
        json.dump(raw, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    products = extract_products(raw, limit=limit)
    if not products:
        print(f"No results for '{args.query}'.")
        return

    pagination = raw.get("pagination", {})
    total = pagination.get("totalCount", "?")
    page_count = pagination.get("pageCount", "?")
    current_page = pagination.get("page", args.page)

    print(f"Results for '{args.query}' ({len(products)} shown, {total} total, "
          f"page {current_page}/{page_count}):\n")
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
