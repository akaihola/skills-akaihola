#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Show next departures from an HSL stop via Digitransit GraphQL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
GEOCODER_URL = "https://api.digitransit.fi/geocoding/v1/search"
HSL_ROUTING_URL = "https://api.digitransit.fi/routing/v2/hsl/gtfs/v1"
HSL_BBOX = "24.5,60.1,25.3,60.35"
SECRETS_FILE = Path.home() / ".config" / "secrets" / "digitransit.env"
FINLAND_TZ = ZoneInfo("Europe/Helsinki")
MODE_ALIASES = {
    "bus": "BUS",
    "tram": "TRAM",
    "rail": "RAIL",
    "train": "RAIL",
    "subway": "SUBWAY",
    "metro": "SUBWAY",
    "ferry": "FERRY",
}
STOP_QUERY = """query($name: String!, $departures: Int!) {
  stops(name: $name) {
    gtfsId
    name
    code
    vehicleMode
    lat
    lon
    stoptimesWithoutPatterns(numberOfDepartures: $departures) {
      scheduledDeparture
      realtimeDeparture
      serviceDay
      headsign
      realtime
      trip {
        routeShortName
      }
    }
  }
}"""


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
    return {}


def auth_hint() -> str:
    secrets = load_secret_values()
    if any(os.environ.get(name) or secrets.get(name) for name in API_KEY_ENV_NAMES):
        return (
            "Using Digitransit API key auth. If this still fails, verify the key value "
            "and expected header name in the Digitransit portal."
        )
    return "No Digitransit credentials found. Set DIGITRANSIT_API_KEY in ~/.config/secrets/digitransit.env."


def request_with_auth(method: str, url: str, **kwargs: object) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}) or {})
    auth = auth_headers()
    attempts = [auth] if auth else [{}]
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
        print(
            "Expected Digitransit setup: register in the Digitransit portal, obtain an API key, "
            "and send it as a subscription-key style header.",
            file=sys.stderr,
        )


def lookup_place(query: str, limit: int = 8) -> list[dict]:
    params = {
        "text": query,
        "size": str(limit),
        "boundary.rect.min_lon": HSL_BBOX.split(",")[0],
        "boundary.rect.min_lat": HSL_BBOX.split(",")[1],
        "boundary.rect.max_lon": HSL_BBOX.split(",")[2],
        "boundary.rect.max_lat": HSL_BBOX.split(",")[3],
        "lang": "fi",
    }
    response = request_with_auth("GET", GEOCODER_URL, params=params, timeout=20)
    return response.json().get("features", [])


def fetch_stops(name: str, departures: int) -> list[dict]:
    response = request_with_auth(
        "POST",
        HSL_ROUTING_URL,
        json={
            "query": STOP_QUERY,
            "variables": {"name": name, "departures": departures},
        },
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    return response.json().get("data", {}).get("stops", [])


def normalize_mode(mode: str | None) -> str | None:
    if not mode:
        return None
    return MODE_ALIASES.get(mode.strip().lower(), mode.strip().upper())


def stop_score(stop: dict, query: str, preferred_mode: str | None, place_names: set[str]) -> tuple[int, int, int, int, str]:
    stop_name = stop.get("name", "").strip().lower()
    query_norm = query.strip().lower()
    mode = (stop.get("vehicleMode") or "").upper()
    departures = len(stop.get("stoptimesWithoutPatterns", []))

    exact = 1 if stop_name == query_norm else 0
    prefix = 1 if stop_name.startswith(query_norm) else 0
    mode_match = 1 if preferred_mode and mode == preferred_mode else 0
    place_match = 1 if stop_name in place_names else 0
    return (mode_match, exact, place_match, departures, stop_name if prefix else "~" + stop_name)


def pick_stop(query: str, departures: int, preferred_mode: str | None) -> dict:
    stops = fetch_stops(query, departures)
    if not stops:
        raise SystemExit(f"No stops found for '{query}'")

    if preferred_mode:
        filtered = [stop for stop in stops if (stop.get("vehicleMode") or "").upper() == preferred_mode]
        if filtered:
            stops = filtered

    places = lookup_place(query)
    place_names = {
        (feature.get("properties", {}).get("name") or "").strip().lower()
        for feature in places
    }

    ranked = sorted(
        stops,
        key=lambda stop: stop_score(stop, query, preferred_mode, place_names),
        reverse=True,
    )
    return ranked[0]


def format_departure(service_day: int, departure_seconds: int) -> str:
    ts = service_day + departure_seconds
    return datetime.fromtimestamp(ts, FINLAND_TZ).strftime("%H:%M")


def departure_delay_minutes(item: dict) -> int:
    return round((item["realtimeDeparture"] - item["scheduledDeparture"]) / 60)


def format_stop(stop: dict) -> str:
    lines = [
        f"Next departures at {stop.get('name', '?')} ({stop.get('code', '?')}, {stop.get('vehicleMode', '?')})",
        f"GTFS ID: {stop.get('gtfsId', '?')}",
        "",
    ]
    departures = stop.get("stoptimesWithoutPatterns", [])
    if not departures:
        lines.append("No upcoming departures found.")
        return "\n".join(lines)

    for idx, item in enumerate(departures, 1):
        route = (item.get("trip") or {}).get("routeShortName") or "?"
        headsign = item.get("headsign") or "?"
        sched = format_departure(item["serviceDay"], item["scheduledDeparture"])
        real = format_departure(item["serviceDay"], item["realtimeDeparture"])
        if item.get("realtime"):
            delay = departure_delay_minutes(item)
            status = "on time" if delay == 0 else f"{delay:+d} min"
        else:
            status = "scheduled"
        lines.append(f"{idx}. {real} ({sched})  {route} -> {headsign}  [{status}]")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Show next departures from an HSL stop")
    parser.add_argument("stop", help="Stop or station name")
    parser.add_argument("--departures", type=int, default=5, help="Number of departures")
    parser.add_argument("--mode", choices=sorted(MODE_ALIASES), help="Prefer a vehicle mode")
    parser.add_argument("--stop-id", help="Exact GTFS ID to use instead of name matching")
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()

    preferred_mode = normalize_mode(args.mode)

    try:
        if args.stop_id:
            stops = fetch_stops(args.stop, args.departures)
            stop = next((item for item in stops if item.get("gtfsId") == args.stop_id), None)
            if stop is None:
                raise SystemExit(f"No stop found with GTFS ID '{args.stop_id}' for '{args.stop}'")
        else:
            stop = pick_stop(args.stop, args.departures, preferred_mode)
    except httpx.HTTPError as exc:
        print(f"Error querying Digitransit stop data: {exc}", file=sys.stderr)
        explain_auth_failure(exc)
        sys.exit(1)

    if args.output_json:
        json.dump(stop, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    print(format_stop(stop))


if __name__ == "__main__":
    main()
