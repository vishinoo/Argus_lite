"""The approach has to be the approach for *this* kind of incident.

A report of shots fired came back with the wind speed and the nearest hydrant.
Those are fire answers. On a police call they are noise in the one column a
dispatcher is meant to act from, and they crowd out the things that would
actually help.
"""

from ic.reason import Incident, build_picture
from ic.tools.base import ToolResult
from ic.tools.web import Finding
from ic.tools.weather import OPEN_METEO, Conditions
from tests.test_reason import evidence, places

WIND = ToolResult(True, "w", data=Conditions(
    temperature_c=15, wind_kmh=25, wind_from_deg=270, humidity_pct=70,
    observed_at=""), sources=(OPEN_METEO,))

HYDRANTS = ToolResult(True, "h", data=[Finding("hydrant", "pillar — 90 m", OPEN_METEO)],
                      sources=(OPEN_METEO,))


def approach(description, **ev):
    """The approach column, with weather and hydrants available to every kind.

    Supplying both is the point: the question is not whether the evidence
    exists, it is whether this discipline should be shown it.
    """
    base = {"weather": WIND, "hydrants": HYDRANTS}
    base.update(ev)
    p = build_picture(Incident("IC-1", "350 5th Avenue", description), evidence(**base))
    return {a.field: a for a in p.approach}


# ── fire keeps everything it had ──────────────────────────────────────


def test_a_fire_gets_wind_water_and_who_is_responding():
    got = approach("structure fire, smoke showing")
    for field in ("approach", "conditions", "water supply", "responding"):
        assert field in got, f"fire lost {field}"


# ── police ────────────────────────────────────────────────────────────


def test_a_shooting_gets_no_weather():
    # Wind decides a plume. There is no plume.
    assert "conditions" not in approach("Shots reported, one person down")


def test_a_shooting_gets_no_hydrant_and_no_engine():
    got = approach("Shots reported, one person down")
    assert "water supply" not in got
    assert "responding" not in got


def test_a_shooting_gets_the_nearest_police_station():
    got = approach("Shots reported, one person down",
                   nearby=places(("Midtown South Precinct", "police", 400.0)))
    assert "police_response" in got
    assert "Midtown South" in got["police_response"].value


def test_a_shooting_near_a_school_gets_containment():
    got = approach("Shots reported, one person down",
                   exposures=places(("Sacred Heart School", "school", 207.0)))
    assert "containment" in got


# ── ems ───────────────────────────────────────────────────────────────


def test_a_medical_call_gets_no_weather_or_hydrant():
    got = approach("cardiac arrest, patient unresponsive, on the 9th floor")
    assert "conditions" not in got
    assert "water supply" not in got


def test_a_medical_call_gets_access_and_transport():
    got = approach("cardiac arrest, patient unresponsive, on the 9th floor")
    assert "ems_access" in got
    assert "transport" in got


def test_a_fire_gets_no_police_or_ems_rows():
    got = approach("structure fire, smoke showing")
    for field in ("police_response", "containment", "ems_access", "transport"):
        assert field not in got


def test_a_police_station_is_not_listed_as_a_resource_on_every_incident():
    # It is fetched for armed calls and surfaced there as `police_response`.
    # Listing it under RESOURCES as well put a police station on every
    # structure fire and named the same station twice on a shooting.
    p = build_picture(Incident("IC-1", "1001 Van Ness", "structure fire, smoke showing"),
                      evidence(nearby=places(("Midtown South Precinct", "police", 400.0),
                                             ("SFFD Station 3", "fire_station", 300.0))))
    assert "police" not in {a.field for a in p.resources}
    assert "fire_station" in {a.field for a in p.resources}


def test_a_shooting_names_the_station_once():
    p = build_picture(Incident("IC-1", "350 5th Ave", "Shots reported, one person down"),
                      evidence(nearby=places(("Midtown South Precinct", "police", 400.0))))
    named = [a.field for a in p.all if "police" in a.field]
    assert named == ["police_response"]
