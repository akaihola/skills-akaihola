#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on bauhaus.fi via the Algolia search API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
    ./search.py "search term" --sort price_asc
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import httpx

ALGOLIA_APP_ID = "PR1NXR88J1"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes"
SEARCH_PAGE_URL = "https://www.bauhaus.fi/catalogsearch/result/?q=test"
SITE_BASE = "https://www.bauhaus.fi"
DEFAULT_LIMIT = 10

SORT_INDICES = {
    "relevance": "nordic_production_fi_products",
    "price_asc": "nordic_production_fi_products_price_group_0_asc",
    "price_desc": "nordic_production_fi_products_price_group_0_desc",
    "newest": "nordic_production_fi_products_created_at_desc",
}


def _fetch_api_key() -> str:
    """Fetch the current Algolia API key from the Bauhaus search page."""
    resp = httpx.get(
        SEARCH_PAGE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0",
        },
        timeout=15,
        follow_redirects=True,
    )
    resp.raise_for_status()
    match = re.search(r'"apiKey"\s*:\s*"([^"]+)"', resp.text)
    if match:
        return match.group(1)
    msg = "Could not extract Algolia API key from Bauhaus search page"
    raise RuntimeError(msg)


def search_products(
    query: str,
    *,
    limit: int = 10,
    page: int = 0,
    sort: str = "relevance",
    api_key: str | None = None,
) -> dict:
    """Search Bauhaus products via Algolia."""
    if api_key is None:
        api_key = _fetch_api_key()

    index = SORT_INDICES.get(sort, SORT_INDICES["relevance"])

    resp = httpx.post(
        f"{ALGOLIA_URL}/{index}/query",
        json={
            "query": query,
            "hitsPerPage": limit,
            "page": page,
        },
        headers={
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
            "X-Algolia-API-Key": api_key,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict, limit: int = 10) -> list[dict]:
    """Extract flat product list from the Algolia response."""
    hits = raw.get("hits", [])
    products = []
    for hit in hits[:limit]:
        # Extract price — Bauhaus uses group_0 for consumer pricing
        price_data = hit.get("price", {}).get("EUR", {})
        price = price_data.get("group_0", price_data.get("default", ""))
        price_formatted = price_data.get(
            "group_0_default_formatted",
            price_data.get("default_formated", ""),
        )

        products.append({
            "name": hit.get("name", ""),
            "sku": hit.get("sku", ""),
            "ean": hit.get("ean", ""),
            "brand": hit.get("brand", ""),
            "url": hit.get("url", ""),
            "price": price,
            "price_formatted": price_formatted,
            "thumbnail_url": hit.get("thumbnail_url", ""),
            "categories": hit.get("categories_without_path", []),
            "in_stock": hit.get("in_stock", None),
            "color": hit.get("primarycolor", ""),
            "web_stock": hit.get("web_in_stock_text", ""),
            "store_stock": hit.get("physic_in_stock_text", ""),
        })
    return products


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    brand = p.get("brand", "")
    price = p.get("price_formatted", "") or p.get("price", "")
    sku = p.get("sku", "")
    url = p.get("url", "")
    in_stock = p.get("in_stock")
    color = p.get("color", "")
    web_stock = p.get("web_stock", "")
    store_stock = p.get("store_stock", "")
    categories = p.get("categories", [])

    parts = [f"  {idx}. {name}"]
    if brand:
        parts.append(f"     Brand: {brand}")
    if price:
        parts.append(f"     Price: {price}")
    if color:
        parts.append(f"     Color: {color}")
    if sku:
        parts.append(f"     SKU: {sku}")
    if categories:
        parts.append(f"     Category: {' > '.join(categories[:3])}")
    if in_stock is not None:
        stock_text = "In stock" if in_stock else "Out of stock"
        parts.append(f"     Stock: {stock_text}")
    if web_stock:
        parts.append(f"     Web: {web_stock}")
    if store_stock:
        parts.append(f"     Store: {store_stock}")
    if url:
        full_url = url if url.startswith("http") else f"{SITE_BASE}{url}"
        parts.append(f"     URL: {full_url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on bauhaus.fi",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Number of results (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=0,
        help="Page number, 0-based (default: 0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON",
    )
    parser.add_argument(
        "--sort",
        choices=list(SORT_INDICES.keys()),
        default="relevance",
        help="Sort order (default: relevance)",
    )
    args = parser.parse_args()

    raw = search_products(
        args.query,
        limit=args.limit,
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

    total = raw.get("nbHits", "?")
    total_pages = raw.get("nbPages", "?")
    current_page = raw.get("page", 0)
    print(
        f"Results for '{args.query}' ({len(products)} shown, {total} total, "
        f"page {current_page + 1}/{total_pages}):\n"
    )
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
