"""The evidence ledger: every claim tied to the record it came from.

"100% of external claims are attributable" is only worth saying if the
attribution is a real link rather than a label. A claim carrying the string
"OpenStreetMap" proves nothing — anything can write that string. A claim
carrying EV-003, where EV-003 is a row holding the tool that ran, the source
it hit, and the raw value it returned, is checkable.
"""

from __future__ import annotations

import pytest

from ic.evidence import Ledger
from ic.tools.base import Source

OSM = Source("OpenStreetMap", "https://openstreetmap.org")


def test_records_are_numbered_in_the_order_they_arrive():
    led = Ledger()
    a = led.record("osm.survey", OSM, "storeys", "13")
    b = led.record("osm.survey", OSM, "occupancy", "social_facility")
    assert (a.id, b.id) == ("EV-001", "EV-002")


def test_a_record_keeps_the_tool_the_source_and_the_raw_value():
    led = Ledger()
    ev = led.record("osm.survey", OSM, "storeys", "13")
    assert ev.tool == "osm.survey"
    assert ev.source is OSM
    assert ev.raw == "13"


def test_a_record_can_be_looked_up_by_id():
    led = Ledger()
    ev = led.record("maps.geocode", OSM, "location", "1001 Van Ness")
    assert led.get(ev.id) is ev


def test_an_unknown_id_resolves_to_nothing_rather_than_raising():
    assert Ledger().get("EV-999") is None


def test_the_ledger_can_be_serialised_for_the_record():
    led = Ledger()
    led.record("osm.survey", OSM, "storeys", "13")
    rows = led.to_list()
    assert rows[0]["id"] == "EV-001"
    assert rows[0]["source"].startswith("OpenStreetMap")


def test_two_ledgers_do_not_share_numbering():
    # Each incident gets its own ledger; EV-001 means this incident's first
    # piece of evidence, not the first since the process started.
    assert Ledger().record("t", OSM, "f", "v").id == Ledger().record("t", OSM, "f", "v").id


def test_the_same_fact_from_the_same_tool_is_one_row_not_two():
    # Occupancy is read once for the building description and again for the
    # people section. Minting two identical rows makes the ledger look like two
    # independent corroborations of a thing observed once, which is the
    # opposite of what an evidence record is for.
    led = Ledger()
    a = led.record("osm.survey", OSM, "occupancy", "social_facility")
    b = led.record("osm.survey", OSM, "occupancy", "social_facility")
    assert a.id == b.id
    assert len(led.records) == 1


def test_the_same_fact_from_a_different_tool_is_a_separate_row():
    # Two sources agreeing is real corroboration and must stay visible.
    led = Ledger()
    a = led.record("osm.survey", OSM, "occupancy", "social_facility")
    b = led.record("permits.lookup", Source("City permits"), "occupancy", "social_facility")
    assert a.id != b.id


def test_a_different_value_for_the_same_fact_is_a_separate_row():
    led = Ledger()
    a = led.record("osm.survey", OSM, "storeys", "13")
    b = led.record("osm.survey", OSM, "storeys", "3")
    assert a.id != b.id


# ── cache invalidation ────────────────────────────────────────────────


def test_changing_the_survey_query_changes_the_cache_key():
    """Adding a clause must not leave stale payloads answering for it.

    Found live: hydrants were added to the Overpass query and every warm cache
    entry kept returning a payload that predated them, so "no mapped hydrant"
    was reported for an address with one 200 m away. A wrong answer that looks
    like an answer.
    """
    import re
    from ic.geo import Point
    from ic.tools import survey as S

    point = Point(37.7849, -122.4219)
    before = S._cache_path(point)
    original = S._query
    try:
        S._query = lambda p: original(p) + 'nwr["emergency"="defibrillator"];'
        after = S._cache_path(point)
    finally:
        S._query = original
    assert before != after
