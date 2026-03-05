#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on puuilo.fi via the Algolia search API.

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

ALGOLIA_APP_ID = "HH40ESW4PH"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes"
SEARCH_PAGE_URL = "https://www.puuilo.fi/catalogsearch/result/?q=test"
SITE_BASE = "https://www.puuilo.fi"
DEFAULT_LIMIT = 10

SORT_INDICES = {
    "relevance": "puuilo_fi_products",
    "popular": "puuilo_fi_products_views_desc",
    "newest": "puuilo_fi_products_created_at_desc",
    "price_asc": "puuilo_fi_products_price_default_asc",
    "price_desc": "puuilo_fi_products_price_default_desc",
    "name_asc": "puuilo_fi_products_name_asc",
    "name_desc": "puuilo_fi_products_name_desc",
}


def _fetch_api_key() -> str:
    """Fetch the current Algolia API key from the Puuilo search page."""
    resp = httpx.get(
        SEARCH_PAGE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:137.0) Gecko/20100101 Firefox/137.0",
        },
        timeout=15,
        follow_redirects=True,
    )
    resp.raise_for_status()

    # The config is JSON-encoded inside JSON.parse('...') with unicode escapes
    # First try: direct "apiKey":"value" pattern
    match = re.search(r'"apiKey"\s*:\s*"([^"]+)"', resp.text)
    if match:
        return match.group(1)

    # Second try: unicode-escaped version inside JSON.parse
    # \u0022apiKey\u0022\u003A\u0022<KEY>\u0022
    match = re.search(
        r'\\u0022apiKey\\u0022\\u003A\\u0022([^\\]+?)\\u0022',
        resp.text,
    )
    if match:
        return match.group(1)

    # Third try: decode the whole algoliaConfig block
    match = re.search(r"algoliaConfig\s*=\s*JSON\.parse\('(.+?)'\)", resp.text)
    if match:
        import codecs
        decoded = codecs.decode(match.group(1), "unicode_escape")
        key_match = re.search(r'"apiKey"\s*:\s*"([^"]+)"', decoded)
        if key_match:
            return key_match.group(1)

    msg = "Could not extract Algolia API key from Puuilo search page"
    raise RuntimeError(msg)


def search_products(
    query: str,
    *,
    limit: int = 10,
    page: int = 0,
    sort: str = "relevance",
    api_key: str | None = None,
) -> dict:
    """Search Puuilo products via Algolia."""
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
        # Extract price
        price_data = hit.get("price", {}).get("EUR", {})
        price = price_data.get("default", "")
        price_formatted = price_data.get("default_formated", "")

        products.append({
            "name": hit.get("name", ""),
            "sku": hit.get("sku", ""),
            "url": hit.get("url", ""),
            "price": price,
            "price_formatted": price_formatted,
            "thumbnail_url": hit.get("thumbnail_url", ""),
            "image_url": hit.get("image_url", ""),
            "categories": hit.get("categories_without_path", []),
            "in_stock": hit.get("in_stock", None),
        })
    return products


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name", "?")
    price = p.get("price_formatted", "") or p.get("price", "")
    sku = p.get("sku", "")
    url = p.get("url", "")
    in_stock = p.get("in_stock")
    categories = p.get("categories", [])

    parts = [f"  {idx}. {name}"]
    if price:
        parts.append(f"     Price: {price}")
    if sku:
        parts.append(f"     SKU: {sku}")
    if categories:
        parts.append(f"     Category: {' > '.join(categories[:3])}")
    if in_stock is not None:
        stock_text = "In stock" if in_stock else "Out of stock"
        parts.append(f"     Stock: {stock_text}")
    if url:
        full_url = url if url.startswith("http") else f"{SITE_BASE}{url}"
        parts.append(f"     URL: {full_url}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on puuilo.fi",
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
