"""Where the incident is, and what is near it.

Everything here is keyless and live. Geocoding is Nominatim, nearby resources
are Overpass, and both are OpenStreetMap. That matters for a demo: when the
agent refuses to act on "999999 Unknown Avenue" it is refusing because a real
geocoder really returned nothing, not because a fixture said so.

Travel time is not straight-line distance over an assumed speed. That model
loses to predicting the median on real dispatch data. This uses the affine
form fitted on San Francisco Fire Department records — a fixed cost of about
144 seconds that does not scale with distance (acceleration, signals, one-way
streets, and the walk from a legal stopping place to the door) plus about 96
seconds per kilometre. It is an estimate and is labelled as one, but it is an
estimate with a number behind it.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ic.geo import Point
from ic.tools.base import Source, ToolResult

USER_AGENT = "ArgusIncidentCommander/0.1 (hackathon prototype)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
TIMEOUT_S = 25.0

OSM = Source("OpenStreetMap / Nominatim", "https://openstreetmap.org")
OVERPASS_SOURCE = Source("OpenStreetMap / Overpass", "https://overpass-api.de")

# Fitted on 5,437 SFFD dispatches with a recovered origin. Beats
# predict-the-median; a proportional model does not.
TRAVEL_INTERCEPT_S = 144.0
TRAVEL_S_PER_M = 0.096

# What counts as "the same place" when two sources name a location.
_KINDS = {
    "hospital": 'amenity"="hospital',
    "fire_station": 'amenity"="fire_station',
    "police": 'amenity"="police',
    "fuel": 'amenity"="fuel',
    "school": 'amenity"="school',
}


@dataclass(frozen=True)
class Located:
    point: Point
    display_name: str
    kind: str | None
    importance: float


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    point: Point
    distance_m: float

    @property
    def eta_s(self) -> float:
        return TRAVEL_INTERCEPT_S + TRAVEL_S_PER_M * self.distance_m

    @property
    def eta_text(self) -> str:
        m, s = divmod(int(self.eta_s), 60)
        return f"{m}:{s:02d}"


# Geocodes are cached on disk and never expire within the TTL: an address does
# not move. This exists because Nominatim's DNS stopped resolving for a minute
# during testing — the survey was cached, the geocode was not, so the location
# came back unverified and the entire run correctly refused. A warmed address
# should not depend on somebody else's uptime.
GEOCODE_CACHE_DIR = Path(".cache/geocode")
GEOCODE_TTL_S = 30 * 24 * 3600


def _geocode_cache_path(address: str) -> Path:
    key = " ".join(address.lower().split())
    return GEOCODE_CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"


def _cached_geocode(address: str) -> object | None:
    path = _geocode_cache_path(address)
    try:
        if path.exists() and time.time() - path.stat().st_mtime <= GEOCODE_TTL_S:
            return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    return None


def _store_geocode(address: str, rows: object) -> None:
    try:
        GEOCODE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _geocode_cache_path(address).write_text(json.dumps(rows))
    except OSError:
        pass  # an unwritable cache is not a reason to fail the lookup


def _get(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode())


def geocode(address: str) -> ToolResult:
    """Resolve an address to a point, or report that it could not be.

    The failure path is the important one. An agent that invents a plausible
    location for an address nobody can find will happily send a fire crew to
    it, and everything downstream inherits the error silently.
    """
    if not address or not address.strip():
        return ToolResult(False, "no address given", error="empty address")

    rows = _cached_geocode(address)
    if rows is None:
        url = f"{NOMINATIM}?" + urllib.parse.urlencode(
            {"q": address, "format": "json", "limit": 3, "addressdetails": 1}
        )
        rows = _get(url)
        # Only a match is cached. "No match" stays re-checkable — an address
        # missing from OpenStreetMap today may be added tomorrow, and caching
        # its absence would hide that for a month.
        if rows:
            _store_geocode(address, rows)
    if not rows:
        return ToolResult(
            False,
            f"no geocoder match for {address!r}",
            sources=(OSM,),
            error="address could not be verified",
        )

    top = rows[0]
    located = Located(
        point=Point(lat=float(top["lat"]), lon=float(top["lon"])),
        display_name=top.get("display_name", address),
        kind=top.get("type"),
        importance=float(top.get("importance", 0.0) or 0.0),
    )
    # More than one confident match is a genuine ambiguity, not a tie to break
    # silently. The agent is told, and says so in the brief.
    ambiguous = len(rows) > 1 and _far_apart(rows)
    return ToolResult(
        True,
        f"{located.display_name[:70]}",
        data={"located": located, "ambiguous": ambiguous, "candidates": len(rows)},
        sources=(OSM,),
    )


def _far_apart(rows: list, threshold_m: float = 1000.0) -> bool:
    a = Point(float(rows[0]["lat"]), float(rows[0]["lon"]))
    b = Point(float(rows[1]["lat"]), float(rows[1]["lon"]))
    return a.haversine_m(b) > threshold_m


def nearby(point: Point, kinds: tuple[str, ...], radius_m: float = 4000.0) -> ToolResult:
    """Hospitals, fire stations and other fixed resources around a point."""
    wanted = [k for k in kinds if k in _KINDS]
    if not wanted:
        return ToolResult(False, "no known resource kinds requested",
                          error=f"unknown kinds: {kinds}")

    clauses = "".join(
        f'node["{_KINDS[k]}"](around:{radius_m:.0f},{point.lat},{point.lon});'
        f'way["{_KINDS[k]}"](around:{radius_m:.0f},{point.lat},{point.lon});'
        for k in wanted
    )
    query = f"[out:json][timeout:25];({clauses});out center tags 40;"

    req = urllib.request.Request(
        OVERPASS, data=query.encode(), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        payload = json.loads(r.read().decode())

    places: list[Place] = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        p = Point(lat=float(lat), lon=float(lon))
        places.append(
            Place(
                name=tags.get("name") or f"unnamed {tags.get('amenity','place')}",
                kind=tags.get("amenity", "place"),
                point=p,
                distance_m=point.haversine_m(p),
            )
        )
    places.sort(key=lambda p: p.distance_m)

    # Deduplicate: a hospital mapped as both a node and a building way is one
    # hospital, and counting it twice inflates the picture.
    seen: set[str] = set()
    unique = [p for p in places if not (p.name in seen or seen.add(p.name))]

    if not unique:
        return ToolResult(
            False, f"nothing of {', '.join(wanted)} within {radius_m:.0f} m",
            sources=(OVERPASS_SOURCE,), error="no resources found in radius",
        )
    return ToolResult(
        True,
        f"{len(unique)} nearby: " + ", ".join(f"{p.name} ({p.distance_m/1000:.1f} km)"
                                              for p in unique[:3]),
        data=unique,
        sources=(OVERPASS_SOURCE,),
    )


def nearest(places: list[Place], kind: str) -> Place | None:
    for p in places:
        if p.kind == kind:
            return p
    return None
