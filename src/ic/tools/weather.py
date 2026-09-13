"""What the air is doing over the incident.

Wind is not decoration on a fire or a gas call. It decides which way the smoke
plume runs, which neighbouring buildings are in it, and which side a crew can
approach from without working inside their own hazard. A brief that lists a
school 200 m away without saying whether it is upwind or downwind has given a
fact and withheld its meaning.

Open-Meteo, keyless, and fast enough to sit inside a one-second run. Humidity
and temperature come along because both bear on fire behaviour.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ic.geo import Point, compass_point
from ic.tools.base import Source, ToolResult

API = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 15.0
OPEN_METEO = Source("Open-Meteo", "https://open-meteo.com")

# Above this, wind is a tactical fact rather than background.
BRISK_KMH = 20.0


@dataclass(frozen=True)
class Conditions:
    temperature_c: float
    wind_kmh: float
    wind_from_deg: float
    """Meteorological convention: the direction the wind blows *from*."""
    humidity_pct: float
    observed_at: str

    @property
    def wind_from(self) -> str:
        return compass_point(self.wind_from_deg)

    @property
    def brisk(self) -> bool:
        return self.wind_kmh >= BRISK_KMH

    @property
    def summary(self) -> str:
        return (f"wind {self.wind_kmh:.0f} km/h from {self.wind_from} "
                f"({self.wind_from_deg:.0f}°), {self.temperature_c:.0f}°C, "
                f"{self.humidity_pct:.0f}% humidity")


def current(point: Point) -> ToolResult:
    """Conditions over the incident right now."""
    url = f"{API}?" + urllib.parse.urlencode({
        "latitude": f"{point.lat:.4f}", "longitude": f"{point.lon:.4f}",
        "current": "temperature_2m,wind_speed_10m,wind_direction_10m,"
                   "relative_humidity_2m",
        "wind_speed_unit": "kmh",
    })
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
        payload = json.loads(r.read().decode())

    now = payload.get("current")
    if not now:
        return ToolResult(False, "no current conditions returned",
                          sources=(OPEN_METEO,), error="weather response had no current block")

    try:
        conditions = Conditions(
            temperature_c=float(now["temperature_2m"]),
            wind_kmh=float(now["wind_speed_10m"]),
            wind_from_deg=float(now["wind_direction_10m"]),
            humidity_pct=float(now["relative_humidity_2m"]),
            observed_at=str(now.get("time", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return ToolResult(False, "weather response not understood",
                          sources=(OPEN_METEO,), error=f"{type(exc).__name__}: {exc}")

    return ToolResult(True, conditions.summary, data=conditions, sources=(OPEN_METEO,))
