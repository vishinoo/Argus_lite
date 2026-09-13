"""Compass work: which way is the fire going, and which way should you come in."""

from __future__ import annotations

import pytest

from ic.geo import Point, bearing_deg, compass_point, is_downwind

HERE = Point(37.7849, -122.4219)


def test_due_north_is_zero_degrees():
    north = Point(HERE.lat + 0.01, HERE.lon)
    assert bearing_deg(HERE, north) == pytest.approx(0, abs=1)


def test_due_east_is_ninety_degrees():
    east = Point(HERE.lat, HERE.lon + 0.01)
    assert bearing_deg(HERE, east) == pytest.approx(90, abs=1)


def test_due_south_is_one_eighty():
    south = Point(HERE.lat - 0.01, HERE.lon)
    assert bearing_deg(HERE, south) == pytest.approx(180, abs=1)


def test_bearings_are_always_positive():
    west = Point(HERE.lat, HERE.lon - 0.01)
    assert 0 <= bearing_deg(HERE, west) < 360


@pytest.mark.parametrize("deg,point", [
    (0, "N"), (45, "NE"), (90, "E"), (180, "S"), (283, "WNW"), (359, "N"),
])
def test_degrees_read_as_a_compass_point(deg, point):
    assert compass_point(deg) == point


# ── downwind ──────────────────────────────────────────────────────────
#
# Meteorological convention: a wind direction of 283 means the wind is coming
# *from* 283. Getting this backwards would send a crew into the smoke and put
# the exposures on the wrong side of the incident, so it is worth a test that
# states the convention out loud.


def test_something_opposite_the_wind_source_is_downwind():
    # Wind from the west (270). Everything east of the incident is downwind.
    east = Point(HERE.lat, HERE.lon + 0.005)
    assert is_downwind(HERE, east, wind_from_deg=270) is True


def test_something_on_the_windward_side_is_not_downwind():
    west = Point(HERE.lat, HERE.lon - 0.005)
    assert is_downwind(HERE, west, wind_from_deg=270) is False


def test_something_at_right_angles_to_the_wind_is_not_downwind():
    north = Point(HERE.lat + 0.005, HERE.lon)
    assert is_downwind(HERE, north, wind_from_deg=270) is False


def test_the_downwind_cone_has_width_because_wind_is_not_a_laser():
    # 30 degrees off the axis is still in the plume.
    slightly_off = Point(HERE.lat + 0.002, HERE.lon + 0.005)
    assert is_downwind(HERE, slightly_off, wind_from_deg=270) is True
