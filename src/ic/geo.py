"""Coordinates, and distance between them.

Carried over from ARGUS unchanged: (lat, lon) always in that order, and a
haversine that returns metres. Every mixed-up coordinate bug this avoids is
one nobody has to find at 2am during a demo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class Point:
    """A WGS84 coordinate. Always (lat, lon) — never (lon, lat)."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"latitude out of range: {self.lat}")
        if not -180.0 <= self.lon <= 180.0:
            raise ValueError(f"longitude out of range: {self.lon}")

    def haversine_m(self, other: Point) -> float:
        """Great-circle distance in meters."""
        lat1, lon1 = math.radians(self.lat), math.radians(self.lon)
        lat2, lon2 = math.radians(other.lat), math.radians(other.lon)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(origin: "Point", target: "Point") -> float:
    """Compass bearing from one point to another, 0 = north, clockwise."""
    lat1, lat2 = math.radians(origin.lat), math.radians(target.lat)
    dlon = math.radians(target.lon - origin.lon)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


_POINTS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def compass_point(degrees: float) -> str:
    """A bearing as a compass point. A crew reads "WNW", not "283 degrees"."""
    return _POINTS[int((degrees % 360) / 22.5 + 0.5) % 16]


# Smoke and gas travel in a plume, not a line. Thirty degrees either side of
# the wind axis is a conventional first approximation and errs towards
# including something rather than excluding it.
DOWNWIND_ARC_DEG = 30.0


def is_downwind(incident: "Point", other: "Point", wind_from_deg: float,
                arc_deg: float = DOWNWIND_ARC_DEG) -> bool:
    """Is `other` in the plume from `incident`?

    Meteorological convention: `wind_from_deg` is the direction the wind blows
    *from*. The plume therefore runs towards the opposite bearing. Getting this
    inverted would put the exposures on the wrong side of a fire and send the
    approach into the smoke, so the convention is named here rather than
    assumed.
    """
    downwind_axis = (wind_from_deg + 180.0) % 360.0
    difference = abs((bearing_deg(incident, other) - downwind_axis + 180.0) % 360.0 - 180.0)
    return difference <= arc_deg
