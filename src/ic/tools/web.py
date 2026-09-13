"""What public sources say about the place.

Three keyless sources, each doing a different job.

The building's own map record answers what it *is* — storeys, construction,
occupancy, operator, whether it is a care home or a warehouse. This is the
highest-value lookup in the whole agent and the one most people skip, because
it is unglamorous next to a web search.

A hazard scan asks what is *around* it. A filling station across the street,
a gas main, an industrial site: things that change how a fire is fought and
that nobody thinks to search for by name.

Encyclopaedic lookup catches the rest — a notable building, a landmark, a site
with a public history. It is the weakest of the three and is treated that way:
a Wikipedia match on a name is not evidence that the article is about *this*
building, so it is offered as context and never as an established fact.

Every finding carries the source it came from. A claim that cannot name where
it came from does not get made.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ic.geo import Point
from ic.tools.base import Source, ToolResult
from ic.tools.maps import OVERPASS, TIMEOUT_S, USER_AGENT

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI = Source("Wikipedia", "https://en.wikipedia.org")
OSM_BUILDING = Source("OpenStreetMap building record", "https://openstreetmap.org")
OSM_HAZARD = Source("OpenStreetMap surroundings", "https://openstreetmap.org")

# Tags worth telling a crew about, and what they mean in plain words.
_BUILDING_TAGS = {
    "building": "structure type",
    "building:levels": "storeys",
    "building:material": "construction",
    "amenity": "occupancy",
    "shop": "occupancy",
    "office": "occupancy",
    "name": "name on file",
    "operator": "operator",
    "addr:housenumber": None,
    "addr:street": None,
    "roof:material": "roof",
    "access": "access",
    "emergency": "emergency feature",
}

# Things nearby that change how an incident is fought.
_HAZARDS = {
    'amenity"="fuel': "filling station",
    'man_made"="storage_tank': "storage tank",
    'landuse"="industrial': "industrial site",
    'amenity"="school': "school",
    'amenity"="hospital': "hospital",
    'amenity"="nursing_home': "care home",
    'power"="substation': "electrical substation",
}


@dataclass(frozen=True)
class Finding:
    """One thing a public source says, with where it said it."""

    field: str
    value: str
    source: Source


def _overpass(query: str) -> dict:
    req = urllib.request.Request(
        OVERPASS, data=query.encode(), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode())


def building_facts(point: Point, radius_m: float = 40.0) -> ToolResult:
    """What the map record says about the structure at this point."""
    query = (
        f"[out:json][timeout:25];"
        f'(way["building"](around:{radius_m:.0f},{point.lat},{point.lon});'
        f'relation["building"](around:{radius_m:.0f},{point.lat},{point.lon}););'
        f"out center tags 5;"
    )
    payload = _overpass(query)
    elements = payload.get("elements", [])
    if not elements:
        return ToolResult(
            False, "no building record at this location",
            sources=(OSM_BUILDING,),
            error="no mapped building within radius",
        )

    tags = elements[0].get("tags", {})
    findings = [
        Finding(label, str(tags[tag]), OSM_BUILDING)
        for tag, label in _BUILDING_TAGS.items()
        if label and tag in tags
    ]
    if not findings:
        return ToolResult(
            False, "building mapped but carries no useful detail",
            sources=(OSM_BUILDING,), error="building record has no descriptive tags",
        )
    return ToolResult(
        True,
        "; ".join(f"{f.field}: {f.value}" for f in findings[:4]),
        data=findings,
        sources=(OSM_BUILDING,),
    )


def hazard_scan(point: Point, radius_m: float = 300.0) -> ToolResult:
    """What is close enough to matter if this goes badly."""
    clauses = "".join(
        f'node["{t}"](around:{radius_m:.0f},{point.lat},{point.lon});'
        f'way["{t}"](around:{radius_m:.0f},{point.lat},{point.lon});'
        for t in _HAZARDS
    )
    payload = _overpass(f"[out:json][timeout:25];({clauses});out center tags 30;")

    found: list[Finding] = []
    seen: set[str] = set()
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None:
            continue
        for key, label in _HAZARDS.items():
            k, v = key.split('"="')
            if tags.get(k) == v:
                d = point.haversine_m(Point(float(lat), float(lon)))
                name = tags.get("name", label)
                if name in seen:
                    continue
                seen.add(name)
                found.append(Finding(label, f"{name} — {d:.0f} m", OSM_HAZARD))
                break

    if not found:
        # An empty scan is a real answer and is reported as one. "Nothing
        # found" and "did not look" must never read the same on a screen.
        return ToolResult(
            True, f"no mapped hazards within {radius_m:.0f} m",
            data=[], sources=(OSM_HAZARD,),
        )
    return ToolResult(
        True,
        "; ".join(f.value for f in found[:4]),
        data=found,
        sources=(OSM_HAZARD,),
    )


# Words that match everything in a city and therefore identify nothing.
_GENERIC = {
    "san", "francisco", "street", "st", "avenue", "ave", "road", "rd", "the",
    "of", "and", "boulevard", "blvd", "drive", "way", "place", "north", "south",
    "east", "west", "new", "city", "county", "california", "ca", "usa",
}


def _relevant(title: str, context: str) -> bool:
    """Is this article plausibly about *this* place, or merely about the words?

    A search for "1001 Van Ness Avenue, San Francisco" returns the San
    Francisco Chronicle and a local TV station, because those articles contain
    those words. Presenting them as public information about the building is
    exactly the kind of confident irrelevance that makes an agent untrustworthy
    — it is not a lie, and it is not a fact either.

    So a hit is kept only when it names something the geocoder also named.
    """
    t = {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in _GENERIC}
    c = {w for w in re.findall(r"[a-z0-9]+", context.lower()) if w not in _GENERIC}
    if not t:
        return False
    # Every distinctive word in the title has to appear in the place we
    # resolved. "Coterie" passes for the Coterie; "Chronicle" does not.
    return t.issubset(c)


def public_search(query: str, context: str | None = None) -> ToolResult:
    """Encyclopaedic context, offered weakly and filtered hard.

    `context` is the geocoder's own description of the place. Without it there
    is nothing to check a title against, so nothing is returned — an unfiltered
    search is worse than no search.
    """
    url = f"{WIKI_API}?" + urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query,
         "format": "json", "srlimit": 3}
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        payload = json.loads(r.read().decode())

    hits = payload.get("query", {}).get("search", [])
    haystack = context or ""
    hits = [h for h in hits if _relevant(h["title"], haystack)]
    if not hits:
        return ToolResult(
            True,
            "no public article specific to this address "
            "(generic matches discarded as not about this place)",
            data=[], sources=(WIKI,),
        )
    findings = [
        Finding(
            "public reference",
            h["title"],
            Source("Wikipedia", f"https://en.wikipedia.org/wiki/"
                                f"{urllib.parse.quote(h['title'].replace(' ', '_'))}"),
        )
        for h in hits
    ]
    return ToolResult(
        True, "; ".join(f.value for f in findings), data=findings, sources=(WIKI,)
    )
