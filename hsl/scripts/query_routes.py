#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Query HSL routes via Digitransit GraphQL."""

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
FALLBACK_POINTS = {
    "kamppi": (60.169307, 24.932500, "Kamppi, Helsinki"),
    "pasila": (60.198190, 24.933928, "Pasila, Helsinki"),
    "tapiola": (60.176351, 24.805462, "Tapiola, Espoo"),
    "otaniemi": (60.184987, 24.826640, "Otaniemi, Espoo"),
    "hakaniemi": (60.178941, 24.950809, "Hakaniemi, Helsinki"),
    "lentoasema": (60.317222, 24.963333, "Lentoasema, Vantaa"),
}
PLAN_QUERY = """query($from: InputCoordinates!, $to: InputCoordinates!, $numItineraries: Int!, $arriveBy: Boolean) {
  plan(from: $from, to: $to, numItineraries: $numItineraries, arriveBy: $arriveBy) {
    itineraries {
      duration
      walkDistance
      generalizedCost
      legs {
        mode
        startTime
        endTime
        distance
        realTime
        departureDelay
        arrivalDelay
        from {
          name
          stop {
            code
            gtfsId
          }
        }
        to {
          name
          stop {
            code
            gtfsId
          }
        }
        route {
          shortName
          longName
        }
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


def geocode(query: str, limit: int = 5) -> list[dict]:
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
    return resp.json().get("features", [])


def pick_best(query: str) -> dict:
    features = geocode(query)
    if not features:
        raise SystemExit(f"No match found for '{query}'")
    return features[0]


def fallback_point(query: str) -> tuple[float, float, str] | None:
    return FALLBACK_POINTS.get(query.strip().lower())


def point_from_feature(feature: dict) -> tuple[float, float, str]:
    coords = feature.get("geometry", {}).get("coordinates", [])
    props = feature.get("properties", {})
    if len(coords) < 2:
        raise SystemExit(f"Feature missing coordinates: {props.get('label', '?')}")
    return coords[1], coords[0], props.get("label") or props.get("name") or "?"


def build_payload(from_place: str, to_place: str, num_itineraries: int, arrive_by: bool) -> dict:
    from_fallback = fallback_point(from_place)
    to_fallback = fallback_point(to_place)

    if from_fallback and to_fallback:
        from_lat, from_lon, from_label = from_fallback
        to_lat, to_lon, to_label = to_fallback
        resolution = "fallback"
    else:
        from_feature = pick_best(from_place)
        to_feature = pick_best(to_place)
        from_lat, from_lon, from_label = point_from_feature(from_feature)
        to_lat, to_lon, to_label = point_from_feature(to_feature)
        resolution = "geocoded"

    return {
        "resolved": {
            "resolution": resolution,
            "from": {"label": from_label, "lat": from_lat, "lon": from_lon},
            "to": {"label": to_label, "lat": to_lat, "lon": to_lon},
        },
        "request": {
            "url": HSL_ROUTING_URL,
            "method": "POST",
            "content_type": "application/json",
            "query": PLAN_QUERY,
            "variables": {
                "from": {"lat": from_lat, "lon": from_lon},
                "to": {"lat": to_lat, "lon": to_lon},
                "numItineraries": num_itineraries,
                "arriveBy": arrive_by,
            },
        },
    }


def execute_plan_query(payload: dict) -> dict:
    response = request_with_auth(
        "POST",
        HSL_ROUTING_URL,
        json={
            "query": payload["request"]["query"],
            "variables": payload["request"]["variables"],
        },
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    return response.json()


def format_timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, FINLAND_TZ).strftime("%H:%M")


def format_duration(seconds: int | float) -> str:
    total_minutes = round(float(seconds) / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes} min"


def leg_label(leg: dict) -> str:
    mode = leg.get("mode", "?")
    route = leg.get("route") or {}
    short_name = route.get("shortName")
    long_name = route.get("longName")
    if mode == "WALK":
        return "Walk"
    if short_name and long_name:
        return f"{mode.title()} {short_name} ({long_name})"
    if short_name:
        return f"{mode.title()} {short_name}"
    return mode.title()


def delay_text(leg: dict) -> str:
    if not leg.get("realTime"):
        return "scheduled"
    dep = leg.get("departureDelay") or 0
    arr = leg.get("arrivalDelay") or 0
    if dep == 0 and arr == 0:
        return "realtime"
    return f"rt dep {dep // 60:+d} min, arr {arr // 60:+d} min"


def format_itineraries(payload: dict, response: dict) -> str:
    itineraries = response.get("data", {}).get("plan", {}).get("itineraries", [])
    if not itineraries:
        return "No itineraries found."

    resolved = payload["resolved"]
    lines = [
        f"HSL route: {resolved['from']['label']} -> {resolved['to']['label']}",
        f"Resolution: {resolved['resolution']}",
        "",
    ]
    for idx, itinerary in enumerate(itineraries, 1):
        lines.append(
            f"{idx}. {format_duration(itinerary['duration'])}, walk {round(itinerary['walkDistance'])} m"
        )
        for leg in itinerary.get("legs", []):
            start = format_timestamp(leg["startTime"])
            end = format_timestamp(leg["endTime"])
            from_name = (leg.get("from") or {}).get("name", "?")
            to_name = (leg.get("to") or {}).get("name", "?")
            lines.append(
                f"   - {start}-{end} {leg_label(leg)}: {from_name} -> {to_name} ({delay_text(leg)})"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Query HSL route planning")
    parser.add_argument("--from", dest="from_place", required=True, help="Origin place")
    parser.add_argument("--to", dest="to_place", required=True, help="Destination place")
    parser.add_argument("--num-itineraries", type=int, default=3)
    parser.add_argument("--arrive-by", action="store_true")
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()

    try:
        payload = build_payload(
            args.from_place,
            args.to_place,
            args.num_itineraries,
            args.arrive_by,
        )
        response = execute_plan_query(payload)
    except httpx.HTTPError as exc:
        print(f"Error querying Digitransit routing: {exc}", file=sys.stderr)
        explain_auth_failure(exc)
        sys.exit(1)

    if args.output_json:
        json.dump({"payload": payload, "response": response}, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    print(format_itineraries(payload, response))


if __name__ == "__main__":
    main()
