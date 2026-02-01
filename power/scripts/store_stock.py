#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Look up per-store stock for a Power.fi product.

Usage:
    ./store_stock.py 3060434
    ./store_stock.py 3060434 --postal-code 00100
    ./store_stock.py 3060434 --json
    ./store_stock.py 3060434 --store "Itis"
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

API_BASE = "https://www.power.fi/api/v2/products"


def get_store_stock(
    product_id: int | str,
    *,
    postal_code: str = "",
) -> list[dict]:
    """Fetch per-store stock for a product.

    Args:
        product_id: Power.fi product ID (numeric).
        postal_code: Optional postal code to sort stores by distance.

    Returns:
        List of store dicts from the API.
    """
    url = f"{API_BASE}/{product_id}/stores"
    params = {}
    if postal_code:
        params["postalCode"] = postal_code

    resp = httpx.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def format_store(store: dict, idx: int) -> str:
    """Format a single store entry for terminal display."""
    name = store.get("name", "?")
    city = store.get("city", "")
    address = store.get("address", "")
    stock = store.get("storeStockCount", 0)
    display_stock = store.get("storeDisplayStock", 0)
    availability = store.get("storeAvailability", 0)
    cnc = store.get("clickNCollect", False)
    distance = store.get("distance")
    schedule = store.get("workingSchedule", [])

    avail_map = {0: "Not available", 1: "Low stock", 2: "In stock"}
    avail_text = avail_map.get(availability, f"Unknown ({availability})")

    parts = [f"  {idx}. {name}"]
    if city or address:
        parts.append(f"     Address: {address}, {city}")
    parts.append(f"     Stock: {stock} pcs ({avail_text})")
    if cnc:
        parts.append("     Click & Collect: Yes")
    if distance is not None:
        parts.append(f"     Distance: {distance} km")
    if schedule:
        today = schedule[0]
        parts.append(f"     Today: {today.get('hours', '?')}")

    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Look up per-store stock for a Power.fi product",
    )
    parser.add_argument("product_id", help="Product ID (numeric)")
    parser.add_argument(
        "--postal-code",
        default="00100",
        help="Postal code to sort by distance (default: 00100 Helsinki)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON",
    )
    parser.add_argument(
        "--store",
        default="",
        help="Filter stores by name (case-insensitive substring match)",
    )
    parser.add_argument(
        "--in-stock",
        action="store_true",
        help="Show only stores with stock > 0",
    )
    args = parser.parse_args()

    stores = get_store_stock(args.product_id, postal_code=args.postal_code)

    if args.output_json:
        json.dump(stores, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    if args.store:
        needle = args.store.lower()
        stores = [s for s in stores if needle in s.get("name", "").lower()]

    if args.in_stock:
        stores = [s for s in stores if s.get("storeStockCount", 0) > 0]

    if not stores:
        print("No matching stores found.")
        return

    print(f"Store stock for product {args.product_id} ({len(stores)} stores):\n")
    for i, store in enumerate(stores, 1):
        print(format_store(store, i))
        print()


if __name__ == "__main__":
    main()
