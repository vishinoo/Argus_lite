"""One question to OpenStreetMap instead of three.

The first version asked Overpass three separate questions — what is the
building, what is nearby, what is hazardous — and then, to be quick about it,
asked them at the same time. Overpass is a free shared service and answered
all three with 504s.

The fix is not more concurrency, it is fewer questions. Everything wanted from
OSM is one spatial query around one point, so it is sent as one query and the
answer is sorted out here. One round trip, no rate limiting, and roughly three
times faster than the version that worked.

A mirror is tried if the primary is busy, because a demo that depends on one
volunteer-run endpoint being healthy is a demo that fails in front of an
audience.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ic.geo import Point
from ic.tools.base import Source, ToolResult
from ic.tools.web import _BUILDING_TAGS, _HAZARDS, Finding, OSM_BUILDING, OSM_HAZARD

MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "ArgusIncidentCommander/0.1 (hackathon prototype)"
TIMEOUT_S = 30.0

OVERPASS_SOURCE = Source("OpenStreetMap / Overpass", "https://overpass-api.de")

BUILDING_RADIUS_M = 40.0
HAZARD_RADIUS_M = 300.0
# 3 km rather than 4: the extra kilometre roughly doubled the query cost and
# added nothing a dispatcher would act on.
RESOURCE_RADIUS_M = 3000.0

_RESOURCES = ("hospital", "fire_station", "police")

# Beyond this a hydrant is not the one you lay a line from.
HYDRANT_RADIUS_M = 250.0

# Mapped things the incident endangers, rather than things that endanger it.
# These need coordinates: whether a school is in the smoke depends entirely on
# which side of the fire it is.
_EXPOSURE_LABELS = {"school", "hospital", "care home"}

# Answers are cached on disk. Overpass is a free service run by volunteers and
# it rate-limits bursts, which is entirely reasonable of it and fatal to a live
# demo. A warmed cache means the same incident replays instantly and cannot be
# taken down by someone else's traffic.
CACHE_DIR = Path(".cache/survey")
CACHE_TTL_S = 24 * 3600


def _cache_path(point: Point) -> Path:
    """Where this point's survey is cached.

    The key includes a hash of the query itself. Without that, adding a clause
    — hydrants, say — leaves every existing entry silently serving a payload
    that predates it, and the new field reads as "none found" everywhere the
    cache is warm. That is a worse failure than a slow lookup, because it looks
    like an answer.
    """
    query_version = hashlib.sha256(_query(point).encode()).hexdigest()[:8]
    key = f"{point.lat:.4f},{point.lon:.4f}|{query_version}"
    return CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"


def _cached(point: Point) -> dict | None:
    path = _cache_path(point)
    if not path.exists() or time.time() - path.stat().st_mtime > CACHE_TTL_S:
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def _store(point: Point, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(point).write_text(json.dumps(payload))


@dataclass(frozen=True)
class Survey:
    building: ToolResult
    hazards: ToolResult
    """Things that can make the incident worse: fuel, tanks, substations."""
    exposures: ToolResult
    """Things the incident can make worse. Carry coordinates, because whether
    one is in the plume depends on which side of the fire it sits on."""
    nearby: ToolResult
    hydrants: ToolResult


def _query(point: Point) -> str:
    """One request, written to be cheap.

    `nwr` with an alternation costs far less than a clause per tag per type,
    and industrial land-use polygons are dropped entirely — they were the most
    expensive part of the query and the least actionable thing in it.
    """
    lat, lon = point.lat, point.lon
    hazards = "fuel|school|nursing_home|hospital"
    resources = "|".join(_RESOURCES)
    return (
        "[out:json][timeout:15];("
        f'way["building"](around:{BUILDING_RADIUS_M:.0f},{lat},{lon});'
        f'nwr["amenity"~"^({hazards})$"](around:{HAZARD_RADIUS_M:.0f},{lat},{lon});'
        f'nwr["man_made"="storage_tank"](around:{HAZARD_RADIUS_M:.0f},{lat},{lon});'
        f'nwr["emergency"="fire_hydrant"](around:{HYDRANT_RADIUS_M:.0f},{lat},{lon});'
        f'nwr["amenity"~"^({resources})$"](around:{RESOURCE_RADIUS_M:.0f},{lat},{lon});'
        ");out center tags 160;"
    )


def _fetch(query: str) -> dict:
    """Ask each mirror in turn, and name the real failure when none answers.

    A rate-limited Overpass returns an HTML error page with a 200, so a plain
    `json.loads` fails with a decode error that says nothing useful. Being
    throttled is a specific, recoverable condition and it says so.
    """
    last: str = "no mirror attempted"
    for url in MIRRORS:
        try:
            req = urllib.request.Request(
                url, data=query.encode(), headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                raw = r.read().decode()
        except Exception as exc:  # noqa: BLE001 - try the mirror, then report
            last = f"{type(exc).__name__}: {exc}"
            continue
        try:
            return json.loads(raw)
        except ValueError:
            last = (
                "rate limited — the service returned an error page rather than data"
                if raw.lstrip().startswith("<")
                else "unparseable response"
            )
    raise RuntimeError(f"every Overpass mirror refused: {last}")


def _centre(el: dict) -> Point | None:
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    return Point(float(lat), float(lon)) if lat is not None and lon is not None else None


def survey(point: Point) -> Survey:
    """Everything OSM knows around this point, from a single request."""
    from ic.tools.maps import Place

    payload = _cached(point)
    if payload is None:
        payload = _fetch(_query(point))
        _store(point, payload)
    elements = payload.get("elements", [])

    building_tags: dict | None = None
    hazards: list[Finding] = []
    exposures: list = []
    places: list[Place] = []
    hydrants: list[tuple[float, dict]] = []
    seen_hazard: set[str] = set()
    seen_place: set[str] = set()

    for el in elements:
        tags = el.get("tags", {})
        centre = _centre(el)
        if centre is None:
            continue
        distance = point.haversine_m(centre)

        if tags.get("emergency") == "fire_hydrant" and distance <= HYDRANT_RADIUS_M:
            hydrants.append((distance, tags))
            continue

        if tags.get("amenity") in _RESOURCES and distance <= RESOURCE_RADIUS_M:
            name = tags.get("name") or f"unnamed {tags['amenity']}"
            if name not in seen_place:
                seen_place.add(name)
                places.append(Place(name=name, kind=tags["amenity"],
                                    point=centre, distance_m=distance))
            continue

        if "building" in tags and distance <= BUILDING_RADIUS_M and building_tags is None:
            building_tags = tags
            continue

        if distance <= HAZARD_RADIUS_M:
            for key, label in _HAZARDS.items():
                k, v = key.split('"="')
                if tags.get(k) == v:
                    name = tags.get("name", label)
                    if name in seen_hazard:
                        break
                    seen_hazard.add(name)
                    if label in _EXPOSURE_LABELS:
                        exposures.append(Place(name=name, kind=label,
                                               point=centre, distance_m=distance))
                    else:
                        hazards.append(
                            Finding(label, f"{name} — {distance:.0f} m", OSM_HAZARD))
                    break

    places.sort(key=lambda p: p.distance_m)
    exposures.sort(key=lambda p: p.distance_m)
    hydrants.sort(key=lambda h: h[0])
    return Survey(
        building=_building_result(building_tags),
        hazards=_hazard_result(hazards),
        exposures=_exposure_result(exposures),
        nearby=_nearby_result(places),
        hydrants=_hydrant_result(hydrants),
    )


def _exposure_result(exposures: list) -> ToolResult:
    if not exposures:
        return ToolResult(True, f"nothing mapped within {HAZARD_RADIUS_M:.0f} m "
                                "that the incident would put at risk",
                          data=[], sources=(OSM_HAZARD,))
    return ToolResult(
        True,
        "; ".join(f"{p.name} ({p.distance_m:.0f} m)" for p in exposures[:3]),
        data=exposures, sources=(OSM_HAZARD,),
    )


def _hydrant_result(hydrants: list[tuple[float, dict]]) -> ToolResult:
    if not hydrants:
        return ToolResult(
            True, f"no mapped hydrant within {HYDRANT_RADIUS_M:.0f} m",
            data=[], sources=(OVERPASS_SOURCE,),
        )
    described = []
    for distance, tags in hydrants[:3]:
        kind = tags.get("fire_hydrant:type", "hydrant")
        described.append(Finding("water supply", f"{kind} — {distance:.0f} m",
                                 OVERPASS_SOURCE))
    return ToolResult(True, "; ".join(f.value for f in described),
                      data=described, sources=(OVERPASS_SOURCE,))


def _building_result(tags: dict | None) -> ToolResult:
    if not tags:
        return ToolResult(False, "no building record at this location",
                          sources=(OSM_BUILDING,), error="no mapped building within radius")
    findings = [
        Finding(label, str(tags[tag]), OSM_BUILDING)
        for tag, label in _BUILDING_TAGS.items() if label and tag in tags
    ]
    if not findings:
        return ToolResult(False, "building mapped but carries no useful detail",
                          sources=(OSM_BUILDING,),
                          error="building record has no descriptive tags")
    return ToolResult(True, "; ".join(f"{f.field}: {f.value}" for f in findings[:4]),
                      data=findings, sources=(OSM_BUILDING,))


def _hazard_result(hazards: list[Finding]) -> ToolResult:
    if not hazards:
        return ToolResult(True, f"no mapped hazards within {HAZARD_RADIUS_M:.0f} m",
                          data=[], sources=(OSM_HAZARD,))
    return ToolResult(True, "; ".join(h.value for h in hazards[:4]),
                      data=hazards, sources=(OSM_HAZARD,))


def _nearby_result(places: list) -> ToolResult:
    if not places:
        return ToolResult(False, f"nothing within {RESOURCE_RADIUS_M:.0f} m",
                          sources=(OVERPASS_SOURCE,), error="no resources found in radius")
    return ToolResult(
        True,
        f"{len(places)} nearby: " + ", ".join(
            f"{p.name} ({p.distance_m/1000:.1f} km)" for p in places[:3]),
        data=places, sources=(OVERPASS_SOURCE,),
    )
