---
name: hsl
description: >-
  Query Helsinki region public transport routes and departures via HSL/Digitransit.
  Use when the user asks about HSL timetables, next departures, route planning,
  stops, stations, trams, metro, buses, ferries, or local train connections in
  the Helsinki region.
---

# HSL / Digitransit Transit Skill

Query HSL public transport data using Digitransit APIs.

This skill is designed for:
- stop and station lookup
- next departures from a stop
- route planning between two places in the HSL area

## API Notes

The official HSL routing backend is Digitransit GraphQL:

- Endpoint: `https://api.digitransit.fi/routing/v2/hsl/gtfs/v1`
- Method: `POST`
- Content type: `application/json` or `application/graphql`
- Registration and API keys are required by Digitransit docs

At implementation time in this environment, both direct unauthenticated
Digitransit GraphQL routing requests and geocoding requests returned HTTP 401.
The official auth model appears to be API-key based via the Digitransit portal,
not username/password Basic auth. This skill now tries subscription-key style
headers and becomes live once a valid API key is configured.

## Tools

### `scripts/lookup_places.py`

Resolve place names, addresses, and stop names in the HSL area.

```bash
./scripts/lookup_places.py Kamppi
./scripts/lookup_places.py "Pasila asema" --limit 8
./scripts/lookup_places.py Tapiola --json
```

Use this when:
- the user mentions a stop, station, address, district, or landmark
- you need coordinates before route planning
- you need candidate HSL stops to disambiguate a place name

### `scripts/query_routes.py`

Live HSL route planning between two places.

```bash
./scripts/query_routes.py --from "Kamppi" --to "Tapiola"
./scripts/query_routes.py --from "Hakaniemi" --to "Lentoasema" --arrive-by
./scripts/query_routes.py --from "Pasila" --to "Otaniemi" --json
```

This script:
- resolves route endpoints via geocoding or built-in HSL place fallbacks
- calls Digitransit GraphQL live
- prints human-friendly itineraries by default
- emits full payload + response with `--json`

Use this when:
- the user asks for an HSL route from A to B
- you want live itinerary options with real-time delay info
- you need raw Digitransit output for debugging with `--json`

### `scripts/next_departures.py`

Live next departures from an HSL stop or station.

```bash
./scripts/next_departures.py Kamppi
./scripts/next_departures.py "Tapiola" --departures 8 --mode metro
./scripts/next_departures.py "Pasila" --stop-id HSL:1040417 --json
```

This script:
- queries HSL stop departures live from Digitransit GraphQL
- picks the best-matching stop for a free-text stop name
- supports `--mode` to prefer bus, tram, rail, metro, or ferry stops
- supports `--stop-id` for an exact GTFS stop match
- prints human-friendly departures by default
- emits raw stop data with `--json`

Use this when:
- the user asks for next departures from a stop or station
- the user wants tram, bus, metro, ferry, or local train departures at a named HSL stop
- you need the stop code / GTFS ID alongside departures

Use `lookup_places.py` first if the stop name is ambiguous.

Use this when:
- the user asks for an HSL route from A to B
- you want normalized coordinates and a ready-to-send routing query

## Agent Instructions

When the user asks about HSL transit:

1. Resolve ambiguous place names with `lookup_places.py`
2. If the user wants a route, run `query_routes.py`
3. If the user wants departures from a stop or station, run `next_departures.py`
4. Be explicit when a result is based on fallback place resolution versus live
   Digitransit routing or departure data

## Known limitations

- Free-text stop matching for departures is best-effort and may still need
  `lookup_places.py` first for ambiguous names.
- Built-in fallback coordinates exist only for a small set of common places.

## Confirmed implementation notes

From the official Digitransit docs and live probing:
- HSL routing GraphQL endpoint: `https://api.digitransit.fi/routing/v2/hsl/gtfs/v1`
- Request method: `POST`
- Direct unauthenticated routing requests returned `401 Access Denied`
- Digitransit docs state registration is required
- Geocoding is the right companion API for resolving free-text places before
  route planning

## Suggested GraphQL operations

The skill scaffold is built around these likely Digitransit GraphQL operations:

- `plan(from: ..., to: ..., numItineraries: ...)`
- `stops(name: ...)`
- `stop(id: ...)`
- `routes(name: ...)`
- `places(name: ...)`

These are included as implementation targets in `references/api.md` and in the
route query scaffold.
