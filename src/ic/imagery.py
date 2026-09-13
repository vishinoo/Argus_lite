"""What the place actually looks like from above.

An address is a string. Whether the building is detached or a terrace, where
the yard is, whether a crew can get an appliance down the side of it — none of
that is in any field of any record, and all of it is in a photograph. It is
also the part of a brief a human reads in half a second, which is worth more
than it sounds when the reading happens under pressure.

Nothing is fetched here. This computes the URL that frames a point, and the
browser loads it from the provider directly. The image never passes through
this process, never enters the payload, and never needs caching.

The framing is the whole job, and it is wrong in two ways by default. A degree
of longitude is much shorter in Edmonton than at the equator, so a bounding box
built from equal degrees hands back a building stretched sideways. And the
ground covered has to have the same aspect ratio as the image requested, or the
provider squashes the result to fit. Both are handled once, here.

On honesty: the photograph is a real record of those coordinates, so it is
evidence. What it is not is current. Aerial imagery is commonly a year or more
old and this endpoint publishes no capture date, so the caveat travels with the
picture rather than being left for the reader to assume.
"""

from __future__ import annotations

import math
import urllib.parse
from dataclasses import dataclass

from ic.geo import Point

BASE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/export"
)

ATTRIBUTION = (
    "Imagery © Esri — Source: Esri, Maxar, Earthstar Geographics, "
    "and the GIS User Community"
)

CAVEAT = (
    "Aerial imagery of these coordinates. The provider publishes no capture "
    "date through this endpoint, so it may be a year or more old — read it as "
    "the building's shape and access, not as the scene right now."
)

# Wide enough to show the building and how you reach it, tight enough that the
# building is still the subject.
DEFAULT_SPAN_M = 160.0
DEFAULT_SIZE = (720, 360)

# A broken coordinate must not turn into a request for a picture of a province.
MAX_SPAN_M = 1200.0

_M_PER_DEGREE_LAT = 111_320.0


@dataclass(frozen=True)
class AerialView:
    url: str
    center: Point
    span_m: float
    width: int
    height: int
    attribution: str = ATTRIBUTION
    caveat: str = CAVEAT

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "lat": self.center.lat,
            "lon": self.center.lon,
            "span_m": self.span_m,
            "width": self.width,
            "height": self.height,
            "attribution": self.attribution,
            "caveat": self.caveat,
        }


def aerial_view(
    center: Point,
    span_m: float = DEFAULT_SPAN_M,
    size: tuple[int, int] = DEFAULT_SIZE,
) -> AerialView:
    """An aerial photograph framed on `center`, `span_m` metres wide."""
    if span_m <= 0:
        raise ValueError(f"span must be positive, got {span_m}")
    span = min(span_m, MAX_SPAN_M)
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive, got {size}")

    # Longitude degrees shrink towards the poles; latitude degrees do not.
    m_per_degree_lon = _M_PER_DEGREE_LAT * math.cos(math.radians(center.lat))
    half_lon = (span / 2) / m_per_degree_lon
    # Match ground aspect to pixel aspect so nothing is squashed.
    half_lat = (span * height / width / 2) / _M_PER_DEGREE_LAT

    query = urllib.parse.urlencode({
        "bbox": (
            f"{center.lon - half_lon},{center.lat - half_lat},"
            f"{center.lon + half_lon},{center.lat + half_lat}"
        ),
        "bboxSR": "4326",
        "imageSR": "3857",
        "size": f"{width},{height}",
        "format": "jpg",
        "f": "image",
    })
    return AerialView(
        url=f"{BASE_URL}?{query}",
        center=center,
        span_m=span,
        width=width,
        height=height,
    )
