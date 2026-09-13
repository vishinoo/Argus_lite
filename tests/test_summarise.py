"""Letting a model write the prose, and checking it did not invent anything.

The model never sees raw tool output and is never the source of a fact. It is
handed fields Argus has already established and asked to restate them. Then the
restatement is checked back against those fields: any number or name that was
not in the evidence means the summary is rejected and the deterministic one is
used instead.

That check is the whole reason a model is allowed near this at all.
"""

from __future__ import annotations

import pytest

from ic.schema import Assessment, Picture
from ic.summarise import (
    deterministic_summary,
    grounded,
    summarise,
)
from ic.tools.base import Source

OSM = Source("OpenStreetMap")


def picture():
    return Picture(
        situation=(
            Assessment.verified("location", "1001 Van Ness Avenue, San Francisco",
                                "geocoder", OSM),
            Assessment.verified("building", "storeys: 13; occupancy: social_facility",
                                "record", OSM),
        ),
        people=(Assessment.reported("persons_reported", "someone may still be inside"),),
        resources=(Assessment.verified("fire_station", "SFFD Station 3 — 0.3 km",
                                       "record", OSM),),
    )


# ── the grounding check ───────────────────────────────────────────────


def test_a_faithful_restatement_is_grounded():
    ok, offending = grounded(
        "13 storeys at 1001 Van Ness Avenue; SFFD Station 3 is 0.3 km away.",
        picture())
    assert ok, offending


def test_an_invented_number_is_caught():
    # The classic failure: a plausible figure nobody supplied.
    ok, offending = grounded("The building has 40 storeys.", picture())
    assert not ok and "40" in offending


def test_an_invented_name_is_caught():
    ok, offending = grounded(
        "Engine 9 from Presidio Station is responding.", picture())
    assert not ok


def test_an_invented_distance_is_caught():
    ok, offending = grounded("SFFD Station 3 is 7.4 km away.", picture())
    assert not ok and "7.4" in offending


def test_ordinary_english_does_not_trip_the_check():
    # The check must not fire on connective prose, or it rejects everything and
    # the model may as well not be there.
    ok, offending = grounded(
        "A fire is reported at 1001 Van Ness Avenue, where someone may still be "
        "inside. The building has 13 storeys.", picture())
    assert ok, offending


def test_case_and_punctuation_do_not_matter():
    ok, _ = grounded("STOREYS: 13. Van Ness Avenue.", picture())
    assert ok


# ── what the model is allowed to see ──────────────────────────────────


def test_the_prompt_contains_only_established_fields():
    from ic.summarise import build_prompt
    prompt = build_prompt(picture(), "structure fire")
    assert "1001 Van Ness Avenue" in prompt
    assert "13" in prompt


def test_the_prompt_marks_what_is_only_reported():
    from ic.summarise import build_prompt
    prompt = build_prompt(picture(), "structure fire")
    assert "REPORTED" in prompt


# ── the fallback ──────────────────────────────────────────────────────


def test_without_an_api_key_the_deterministic_summary_is_used(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = summarise(picture(), "structure fire")
    assert result.source == "template"
    assert result.text


def test_the_deterministic_summary_states_only_what_is_established():
    text = deterministic_summary(picture(), "structure fire")
    ok, offending = grounded(text, picture())
    assert ok, offending


def test_the_deterministic_summary_separates_reported_from_verified():
    text = deterministic_summary(picture(), "structure fire")
    assert "reported" in text.lower()


def test_a_summary_always_says_where_it_came_from():
    result = summarise(picture(), "structure fire")
    assert result.source in {"model", "template"}
    assert result.label
