"""The approach agent: which side to come in from, and what is in the plume."""

from __future__ import annotations

import pytest

from ic.approach import plan_approach
from ic.geo import Point
from ic.tools.maps import Place
from ic.tools.weather import Conditions

HERE = Point(37.7849, -122.4219)


def conditions(wind_from=270.0, kmh=25.0):
    return Conditions(temperature_c=17.0, wind_kmh=kmh, wind_from_deg=wind_from,
                      humidity_pct=60.0, observed_at="2026-09-13T01:00")


def place(name, kind, dlat=0.0, dlon=0.0):
    p = Point(HERE.lat + dlat, HERE.lon + dlon)
    return Place(name=name, kind=kind, point=p, distance_m=HERE.haversine_m(p))


STATION = place("SFFD Station 3", "fire_station", dlat=0.003)


# ── the approach side ─────────────────────────────────────────────────


def test_the_approach_is_from_upwind():
    # Wind from the west means you come in from the west and work with it at
    # your back, not from the east through your own smoke.
    plan = plan_approach(HERE, conditions(wind_from=270), [STATION], [], [])
    assert plan.approach_from == "W"


def test_the_approach_bearing_is_the_wind_source():
    plan = plan_approach(HERE, conditions(wind_from=283), [STATION], [], [])
    assert plan.approach_bearing_deg == pytest.approx(283)


def test_without_weather_no_approach_side_is_claimed():
    # Guessing a side with no wind data would be worse than saying nothing:
    # a crew could stage downwind on the strength of it.
    plan = plan_approach(HERE, None, [STATION], [], [])
    assert plan.approach_from is None
    assert "wind" in plan.caveat.lower()


def test_light_wind_is_reported_as_not_decisive():
    plan = plan_approach(HERE, conditions(kmh=3), [STATION], [], [])
    assert plan.wind_decisive is False


def test_brisk_wind_is_decisive():
    assert plan_approach(HERE, conditions(kmh=30), [STATION], [], []).wind_decisive is True


# ── the plume ─────────────────────────────────────────────────────────


def test_an_exposure_downwind_is_identified():
    east = place("Sacred Heart School", "school", dlon=0.004)
    plan = plan_approach(HERE, conditions(wind_from=270), [STATION], [east], [])
    assert "Sacred Heart School" in " ".join(plan.downwind)


def test_an_exposure_upwind_is_not_in_the_plume():
    west = place("Upwind School", "school", dlon=-0.004)
    plan = plan_approach(HERE, conditions(wind_from=270), [STATION], [west], [])
    assert plan.downwind == ()


def test_no_weather_means_no_plume_claim():
    east = place("Sacred Heart School", "school", dlon=0.004)
    assert plan_approach(HERE, None, [STATION], [east], []).downwind == ()


# ── water and the responding station ──────────────────────────────────


def test_the_nearest_hydrant_is_carried():
    plan = plan_approach(HERE, conditions(), [STATION], [], ["pillar — 104 m"])
    assert "104 m" in (plan.water_supply or "")


def test_no_mapped_hydrant_is_stated_rather_than_omitted():
    plan = plan_approach(HERE, conditions(), [STATION], [], [])
    assert plan.water_supply is None
    assert any("hydrant" in n.lower() for n in plan.notes)


def test_the_responding_station_and_its_side_are_reported():
    plan = plan_approach(HERE, conditions(), [STATION], [], [])
    assert "Station 3" in (plan.responding or "")
    assert plan.station_bearing_from is not None


def test_with_no_station_the_plan_says_so_instead_of_inventing_one():
    plan = plan_approach(HERE, conditions(), [], [], [])
    assert plan.responding is None


# ── honesty ───────────────────────────────────────────────────────────


def test_the_plan_is_always_advisory_and_says_wind_shifts():
    plan = plan_approach(HERE, conditions(), [STATION], [], [])
    assert "shift" in plan.caveat.lower() or "advisory" in plan.caveat.lower()


def test_the_plan_renders_assessments_that_carry_their_reasoning():
    plan = plan_approach(HERE, conditions(wind_from=270), [STATION], [], [])
    items = plan.assessments()
    assert items and all(a.evidence for a in items)


# ── the plume actually reaches the exposures ──────────────────────────
#
# Regression. Exposures were returned by the hazard scan as coordinate-less
# findings, while the plume test read from the resources list — which only ever
# holds hospitals and fire stations. So the school was never tested, and
# "in the plume" could not appear however the wind blew. The section rendered,
# the analysis silently did nothing.


def test_a_downwind_school_reaches_the_picture_from_a_full_run():
    from ic.cases import STANDARD, _geo
    from ic.reason import Evidence, Incident, build_picture
    from ic.tools.base import ToolResult
    from ic.tools.weather import Conditions

    wind = ToolResult(True, "w", data=Conditions(
        temperature_c=15, wind_kmh=25, wind_from_deg=270,
        humidity_pct=70, observed_at=""), sources=(__import__(
            "ic.tools.weather", fromlist=["OPEN_METEO"]).OPEN_METEO,))

    evidence = Evidence(geocode=_geo(), **{**STANDARD, "weather": wind})
    picture = build_picture(
        Incident("IC-P", "1001 Van Ness Avenue", "structure fire"), evidence)

    plume = [a for a in picture.approach if a.field == "in the plume"]
    assert plume, "the school east of the incident should be in a westerly plume"
    assert "Sacred Heart" in (plume[0].value or "")


def test_an_exposure_still_appears_even_when_it_is_not_in_the_plume():
    # Upwind is not "irrelevant" — it is still a building beside a fire.
    from ic.cases import STANDARD, _geo
    from ic.reason import Evidence, Incident, build_picture

    evidence = Evidence(geocode=_geo(), **STANDARD)
    picture = build_picture(
        Incident("IC-P", "1001 Van Ness Avenue", "structure fire"), evidence)
    assert any("Sacred Heart" in (a.value or "") for a in picture.exposures)
