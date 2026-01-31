#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Search products on clasohlson.com/fi/ via the Voyado Elevate (Apptus eSales) API.

Usage:
    ./search.py "search term"
    ./search.py "search term" --limit 20
    ./search.py "search term" --json
    ./search.py "search term" --attributes name_fi,baseprice,gridViewImage
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from urllib.parse import quote, urlencode

import httpx

API_BASE = "https://w76e66a6f.api.esales.apptus.cloud/api/v2/panels"

DEFAULT_ATTRIBUTES = (
    "name_fi,baseprice,basepricewithoutvat,gridViewImage,"
    "mainCategoryName_fi,mainCategoryPath_fi,brand,"
    "description_fi,article_number,campaignStatus,"
    "sellingprice,oldPriceWithoutVat"
)

IMAGE_BASE = "https://images.clasohlson.com/medias"


def search_products(
    query: str,
    *,
    limit: int = 10,
    offset: int = 1,
    attributes: str = DEFAULT_ATTRIBUTES,
    market: str = "FI",
) -> dict:
    """Search Clas Ohlson products via the Voyado Elevate API.

    Uses the ``/search`` panel which returns product suggestions, autocomplete,
    category suggestions and more.  The ``product-suggestions`` sub-panel
    contains the actual search results.
    """
    session_key = str(uuid.uuid4())
    customer_key = str(uuid.uuid4())

    # Build URL manually to keep literal commas in search_attributes.
    params = {
        "esales.market": market,
        "esales.sessionKey": session_key,
        "esales.customerKey": customer_key,
        "esales.searchPhrase": query,
        "market": market,
        "search_prefix": query,
        "window_first": str(offset),
        "window_last": str(offset + limit - 1),
    }
    qs = urlencode(params, quote_via=quote)
    qs += f"&search_attributes={attributes}"
    url = f"{API_BASE}/search?{qs}"

    resp = httpx.get(url, timeout=15)
    if resp.status_code >= 500:
        resp.raise_for_status()
    return resp.json()


def extract_products(raw: dict, panel_name: str = "product-suggestions") -> list[dict]:
    """Extract a flat list of products from the API response.

    Args:
        raw: Full API response dict.
        panel_name: Which sub-panel to extract from.  ``product-suggestions``
            contains real search results; ``top-sellers`` contains popular items.
    """
    products = []
    for section in raw.values():
        if not isinstance(section, list):
            continue
        for panel in section:
            if panel.get("name") != panel_name:
                continue
            for product in panel.get("products", []):
                for variant in product.get("variants", []):
                    attrs = variant.get("attributes", {})
                    item = {"key": variant["key"]}
                    for attr_name, values in attrs.items():
                        item[attr_name] = values[0] if len(values) == 1 else values
                    products.append(item)
    return products


def extract_autocomplete(raw: dict) -> list[str]:
    """Extract autocomplete suggestions from the API response."""
    completions: list[str] = []
    for section in raw.values():
        if not isinstance(section, list):
            continue
        for panel in section:
            if panel.get("name") != "autocomplete":
                continue
            for c in panel.get("completions", []):
                q = c.get("query", "")
                if q:
                    completions.append(q)
    return completions


def format_product(p: dict, idx: int) -> str:
    """Format a single product for terminal display."""
    name = p.get("name_fi", "?")
    price = p.get("baseprice", p.get("sellingprice", "?"))
    brand = p.get("brand", "")
    category = p.get("mainCategoryName_fi", "")
    key = p.get("key", "")
    parts = [f"  {idx}. {name}"]
    if brand:
        parts.append(f"     Brand: {brand}")
    if price and price != "?":
        parts.append(f"     Price: {price} EUR")
    if category:
        parts.append(f"     Category: {category}")
    if key:
        article = key.replace("_FI", "")
        parts.append(f"     Article: {article}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search products on clasohlson.com/fi/",
    )
    parser.add_argument("query", help="Search term")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of results (default: 10)"
    )
    parser.add_argument(
        "--offset", type=int, default=1, help="Start position (default: 1)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json", help="Output raw JSON"
    )
    parser.add_argument(
        "--attributes",
        default=DEFAULT_ATTRIBUTES,
        help="Comma-separated attribute list",
    )
    parser.add_argument("--market", default="FI", help="Market code (default: FI)")
    args = parser.parse_args()

    raw = search_products(
        args.query,
        limit=args.limit,
        offset=args.offset,
        attributes=args.attributes,
        market=args.market,
    )

    if args.output_json:
        json.dump(raw, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    products = extract_products(raw)
    if not products:
        print(f"No results for '{args.query}'.")
        return

    completions = extract_autocomplete(raw)
    if completions:
        print(f"Autocomplete: {', '.join(completions)}")
        print()

    print(f"Results for '{args.query}' ({len(products)} shown):\n")
    for i, p in enumerate(products, 1):
        print(format_product(p, i))
        print()


if __name__ == "__main__":
    main()
