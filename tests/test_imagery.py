"""An aerial photograph of the place the call came from.

An address is a string. What the building looks like from above — the roof, the
yard, the access, whether it is detached or a terrace — is in a picture and in
no field of any record. It is also the one part of the brief a human reads in
half a second.
"""

from __future__ import annotations

import math
from urllib.parse import parse_qs, urlparse

import pytest

from ic.geo import Point
from ic.imagery import ATTRIBUTION, aerial_view

HERE = Point(53.5186, -113.5210)


def bbox_of(view):
    q = parse_qs(urlparse(view.url).query)
    return tuple(float(v) for v in q["bbox"][0].split(","))


def test_the_frame_is_centred_on_the_incident():
    xmin, ymin, xmax, ymax = bbox_of(aerial_view(HERE))
    assert (xmin + xmax) / 2 == pytest.approx(HERE.lon, abs=1e-9)
    assert (ymin + ymax) / 2 == pytest.approx(HERE.lat, abs=1e-9)


def test_longitude_is_compressed_by_latitude():
    # A degree of longitude is much shorter in Edmonton than at the equator.
    # Ignoring that stretches every building sideways.
    xmin, ymin, xmax, ymax = bbox_of(aerial_view(HERE, size=(400, 400)))
    assert (xmax - xmin) > (ymax - ymin)


def test_ground_aspect_matches_pixel_aspect():
    # Otherwise the provider squashes the image to fit.
    xmin, ymin, xmax, ymax = bbox_of(aerial_view(HERE, size=(640, 320)))
    lat_m = (ymax - ymin) * 111_320
    lon_m = (xmax - xmin) * 111_320 * math.cos(math.radians(HERE.lat))
    assert lon_m / lat_m == pytest.approx(2.0, rel=0.01)


def test_a_wider_span_frames_more_ground():
    narrow = bbox_of(aerial_view(HERE, span_m=100))
    wide = bbox_of(aerial_view(HERE, span_m=400))
    assert (wide[2] - wide[0]) > (narrow[2] - narrow[0])


def test_an_absurd_span_is_clamped():
    # A broken coordinate must not request a picture of a province.
    xmin, _, xmax, _ = bbox_of(aerial_view(HERE, span_m=10_000_000))
    assert (xmax - xmin) < 1.0


def test_the_image_needs_no_key():
    url = aerial_view(HERE).url
    assert "key=" not in url and "token=" not in url


def test_the_imagery_is_attributed():
    assert "Esri" in aerial_view(HERE).attribution
    assert "Esri" in ATTRIBUTION


def test_the_vintage_caveat_travels_with_it():
    # Aerial imagery is routinely a year or more old and the endpoint does not
    # publish a capture date. Somebody reading it as "now" would be looking for
    # a building that may have been demolished.
    assert "date" in aerial_view(HERE).caveat.lower()
