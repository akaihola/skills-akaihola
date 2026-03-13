#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Resolve HSL-area places using Digitransit geocoding."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API_KEY_ENV_NAMES = (
    "DIGITRANSIT_API_KEY",
    "DIGITRANSIT_SUBSCRIPTION_KEY",
    "API_KEY",
)
API_KEY_HEADER_NAMES = (
    "digitransit-subscription-key",
    "Ocp-Apim-Subscription-Key",
)
DEFAULT_LIMIT = 8
GEOCODER_URL = "https://api.digitransit.fi/geocoding/v1/search"
HSL_BBOX = "24.5,60.1,25.3,60.35"
SECRETS_FILE = Path.home() / ".config" / "secrets" / "digitransit.env"


def load_secret_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if SECRETS_FILE.exists():
        for line in SECRETS_FILE.read_text().splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value
    return values


def auth_headers() -> dict[str, str]:
    secrets = load_secret_values()
    for key_name in API_KEY_ENV_NAMES:
        api_key = os.environ.get(key_name) or secrets.get(key_name)
        if api_key:
            return {API_KEY_HEADER_NAMES[0]: api_key}

    username = os.environ.get("DIGITRANSIT_USERNAME") or secrets.get("DIGITRANSIT_USERNAME")
    password = os.environ.get("DIGITRANSIT_PASSWORD") or secrets.get("DIGITRANSIT_PASSWORD")
    if username and password:
        return {
            "Authorization": httpx.BasicAuth(username, password)._auth_header,
        }
    return {}


def auth_hint() -> str:
    secrets = load_secret_values()
    if any(os.environ.get(name) or secrets.get(name) for name in API_KEY_ENV_NAMES):
        return (
            "Using Digitransit API key auth. If this still fails, verify the key value "
            "and expected header name in the Digitransit portal."
        )
    if os.environ.get("DIGITRANSIT_USERNAME") or secrets.get("DIGITRANSIT_USERNAME"):
        return (
            "Digitransit docs indicate API key auth, not username/password Basic auth. "
            "Set DIGITRANSIT_API_KEY in ~/.config/secrets/digitransit.env."
        )
    return "No Digitransit credentials found. Set DIGITRANSIT_API_KEY in ~/.config/secrets/digitransit.env."


def auth_summary() -> str:
    secrets = load_secret_values()
    if any(os.environ.get(name) or secrets.get(name) for name in API_KEY_ENV_NAMES):
        return "api-key"
    if os.environ.get("DIGITRANSIT_USERNAME") or secrets.get("DIGITRANSIT_USERNAME"):
        return "basic-auth"
    return "none"


def request_with_auth(method: str, url: str, **kwargs: object) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}) or {})
    auth = auth_headers()
    if not auth:
        response = httpx.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    attempts = [auth]
    if API_KEY_HEADER_NAMES[0] in auth:
        api_key = auth[API_KEY_HEADER_NAMES[0]]
        attempts = [{header_name: api_key} for header_name in API_KEY_HEADER_NAMES]

    last_response: httpx.Response | None = None
    for extra_headers in attempts:
        response = httpx.request(method, url, headers={**headers, **extra_headers}, **kwargs)
        last_response = response
        if response.status_code != 401:
            response.raise_for_status()
            return response

    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def explain_auth_failure(exc: httpx.HTTPError) -> None:
    print(auth_hint(), file=sys.stderr)
    if exc.response is not None and exc.response.status_code == 401:
        print(f"Configured auth mode: {auth_summary()}", file=sys.stderr)
        print(
            "Expected Digitransit setup: register in the Digitransit portal, obtain an API key, "
            "and send it as a subscription-key style header.",
            file=sys.stderr,
        )


def search_places(query: str, limit: int = DEFAULT_LIMIT) -> dict:
    params = {
        "text": query,
        "size": str(limit),
        "boundary.rect.min_lon": HSL_BBOX.split(",")[0],
        "boundary.rect.min_lat": HSL_BBOX.split(",")[1],
        "boundary.rect.max_lon": HSL_BBOX.split(",")[2],
        "boundary.rect.max_lat": HSL_BBOX.split(",")[3],
        "lang": "fi",
    }
    resp = request_with_auth("GET", GEOCODER_URL, params=params, timeout=20)
    return resp.json()


def extract_features(payload: dict) -> list[dict]:
    features = payload.get("features", [])
    results: list[dict] = []
    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [None, None])
        label = props.get("label") or props.get("name") or "?"
        results.append(
            {
                "name": props.get("name", label),
                "label": label,
                "layer": props.get("layer", ""),
                "source": props.get("source", ""),
                "id": props.get("id") or props.get("gid") or "",
                "lat": coords[1] if len(coords) > 1 else None,
                "lon": coords[0] if len(coords) > 1 else None,
                "confidence": props.get("confidence"),
            }
        )
    return results


def format_result(item: dict, idx: int) -> str:
    parts = [f"{idx}. {item['label']}"]
    if item.get("layer"):
        parts.append(f"   Layer: {item['layer']}")
    if item.get("source"):
        parts.append(f"   Source: {item['source']}")
    if item.get("lat") is not None and item.get("lon") is not None:
        parts.append(f"   Coordinates: {item['lat']:.6f}, {item['lon']:.6f}")
    if item.get("confidence") is not None:
        parts.append(f"   Confidence: {item['confidence']}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve HSL-area places")
    parser.add_argument("query", help="Place, stop, station, or address")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()

    try:
        payload = search_places(args.query, limit=args.limit)
    except httpx.HTTPError as exc:
        print(f"Error querying Digitransit geocoder: {exc}", file=sys.stderr)
        explain_auth_failure(exc)
        sys.exit(1)

    results = extract_features(payload)
    if args.output_json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    if not results:
        print(f"No HSL-area place matches for '{args.query}'.")
        return

    print(f"Place matches for '{args.query}' ({len(results)} shown):\n")
    for idx, item in enumerate(results, 1):
        print(format_result(item, idx))
        print()


if __name__ == "__main__":
    main()
