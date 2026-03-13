# HSL / Digitransit API Notes

This note captures the current state of the official APIs for a reusable HSL skill.

## Confirmed endpoints

### Routing GraphQL

- `https://api.digitransit.fi/routing/v2/hsl/gtfs/v1`
- Method: `POST`
- Content-Type: `application/json` or `application/graphql`
- Docs indicate registration and API keys are required

### Geocoding

Digitransit exposes a separate geocoding API for address and place lookup. In practice,
this is the natural first step for turning user text like `Kamppi` or `Pasila asema`
into coordinates or stop-like candidates.

## What was verified

Live probes against the HSL routing GraphQL endpoint returned `401 Access Denied`
for unauthenticated requests in this environment.

The Digitransit developer docs and API portal indicate that access is API-key based.
The portal is powered by Azure API Management, so subscription-key style headers are
likely required.

That means an open-source skill can still provide value by:
- resolving free-text places
- preparing canonical GraphQL payloads
- becoming fully live once credentials are added

## Query shapes to support

These GraphQL operations are the core targets for a future authenticated version.

### Place search

```graphql
query($query: String!) {
  places(name: $query) {
    name
    lat
    lon
    ... on Stop {
      gtfsId
      code
      vehicleMode
      desc
    }
  }
}
```

### Stop search with departures

```graphql
query($name: String!) {
  stops(name: $name) {
    gtfsId
    name
    code
    vehicleMode
    lat
    lon
    stoptimesWithoutPatterns(numberOfDepartures: 5) {
      scheduledDeparture
      realtimeDeparture
      serviceDay
      headsign
      realtime
    }
  }
}
```

### Itinerary planning

```graphql
query($from: InputCoordinates!, $to: InputCoordinates!) {
  plan(from: $from, to: $to, numItineraries: 3) {
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
}
```

## Open questions

- which exact header name the Digitransit portal expects for this account's API key
- whether HSL stop departures should be queried through GraphQL only or a companion endpoint
- how best to constrain place resolution to HSL-only geography when the geocoder returns broader results
