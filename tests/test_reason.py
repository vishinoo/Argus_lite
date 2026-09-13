"""Turning what the tools found into something a human can act on."""

from __future__ import annotations

import pytest

from ic.brief import Priority
from ic.geo import Point
from ic.reason import Evidence, Incident, Kind, classify, synthesize
from ic.tools.base import Source, ToolResult
from ic.tools.maps import Located, Place
from ic.tools.web import Finding

OSM = Source("OpenStreetMap", "https://openstreetmap.org")
HERE = Point(37.7849, -122.4219)


def located(**kw):
    return ToolResult(True, "found", data={
        "located": Located(HERE, "1001 Van Ness Avenue, San Francisco", "building", 0.6),
        "ambiguous": kw.get("ambiguous", False), "candidates": 1}, sources=(OSM,))


def building(*pairs):
    return ToolResult(True, "ok", data=[Finding(f, v, OSM) for f, v in pairs], sources=(OSM,))


def places(*specs):
    return ToolResult(True, "ok", data=[
        Place(name=n, kind=k, point=HERE, distance_m=d) for n, k, d in specs], sources=(OSM,))


def hazards(*names):
    return ToolResult(True, "ok", data=[Finding("hazard", n, OSM) for n in names], sources=(OSM,))


def evidence(**kw):
    base = dict(
        geocode=located(),
        building=building(("storeys", "13"), ("occupancy", "social_facility")),
        hazards=hazards("filling station — 80 m"),
        nearby=places(("SFFD Station 3", "fire_station", 300.0),
                      ("CPMC Van Ness", "hospital", 130.0)),
        public=ToolResult(True, "ok", data=[], sources=(OSM,)),
    )
    base.update(kw)
    return Evidence(**base)


def fire():
    return Incident("IC-1", "1001 Van Ness Avenue", "structure fire, smoke from second floor")


# ------------------------------------------------------------- classification


@pytest.mark.parametrize("text,kind", [
    ("structure fire, smoke showing", Kind.FIRE),
    ("possible heart attack, unresponsive", Kind.MEDICAL),
    ("strong smell of gas in the building", Kind.GAS),
    ("missing child last seen an hour ago", Kind.MISSING_PERSON),
    ("man with a knife threatening staff", Kind.ARMED),
    ("something is happening", Kind.UNKNOWN),
])
def test_the_incident_is_classified_from_the_description(text, kind):
    assert classify(text) is kind


# ------------------------------------------------------------- the refusal


def test_an_unverifiable_address_stops_the_brief():
    bad = ToolResult(False, "no match", error="address could not be verified")
    b = synthesize(fire(), evidence(geocode=bad))
    assert b.priority is Priority.UNVERIFIED
    assert b.location_verified is False


def test_an_unverifiable_address_makes_no_claims_about_the_place():
    bad = ToolResult(False, "no match", error="address could not be verified")
    b = synthesize(fire(), evidence(geocode=bad))
    assert b.known == () and b.hazards == ()


def test_an_unverifiable_address_says_what_is_needed():
    bad = ToolResult(False, "no match", error="address could not be verified")
    assert any("confirm" in u.lower() or "verif" in u.lower()
               for u in synthesize(fire(), evidence(geocode=bad)).unknowns)


def test_an_ambiguous_address_is_flagged_not_guessed():
    b = synthesize(fire(), evidence(geocode=located(ambiguous=True)))
    assert any("more than one" in u.lower() or "ambiguous" in u.lower() for u in b.unknowns)


# ------------------------------------------------------------- what it found


def test_building_facts_become_sourced_claims():
    b = synthesize(fire(), evidence())
    assert any("13" in c.text for c in b.known)
    assert all(c.source is not None for c in b.known if c.is_external)


def test_the_caller_account_is_kept_as_the_caller_account():
    b = synthesize(fire(), evidence())
    assert any(c.label == "caller said" for c in b.claims + b.known)


def test_nearby_resources_carry_an_eta():
    b = synthesize(fire(), evidence())
    assert any(":" in c.text for c in b.resources)


def test_a_mapped_hazard_reaches_the_brief():
    b = synthesize(fire(), evidence())
    assert any("filling station" in c.text for c in b.hazards)


# ------------------------------------------------------------- honesty


def test_an_empty_hazard_scan_is_reported_as_nothing_found_not_omitted():
    b = synthesize(fire(), evidence(hazards=ToolResult(True, "none", data=[], sources=(OSM,))))
    text = b.render().lower()
    assert "no mapped hazard" in text or "none found" in text


def test_no_public_information_is_stated_explicitly():
    b = synthesize(fire(), evidence(
        building=ToolResult(False, "nothing", error="no mapped building"),
        public=ToolResult(True, "nothing", data=[], sources=(OSM,))))
    assert any("no" in u.lower() for u in b.unknowns)


def test_a_failed_tool_becomes_an_open_question_not_a_silence():
    b = synthesize(fire(), evidence(
        building=ToolResult(False, "failed", error="no mapped building")))
    assert any("building" in u.lower() for u in b.unknowns)


def test_a_conflict_between_the_caller_and_the_record_is_surfaced():
    # Caller says three floors; the map record says thirteen. Both go in.
    inc = Incident("IC-1", "1001 Van Ness Avenue", "fire in a 3 storey building")
    b = synthesize(inc, evidence())
    assert b.conflicts


def test_an_armed_incident_flags_uncertainty_rather_than_asserting_threat():
    inc = Incident("IC-9", "1001 Van Ness Avenue", "man with a knife threatening staff")
    b = synthesize(inc, evidence())
    assert any("unconfirmed" in u.lower() or "not verified" in u.lower()
               or "caller" in u.lower() for u in b.unknowns)


# ------------------------------------------------------------- reasoning


def test_a_tall_building_produces_an_aerial_consideration():
    b = synthesize(fire(), evidence())
    assert any("aerial" in c.text.lower() or "ladder" in c.text.lower()
               for c in b.considerations)


def test_a_care_occupancy_raises_an_evacuation_consideration():
    b = synthesize(fire(), evidence())
    assert any("evacu" in c.text.lower() or "assist" in c.text.lower()
               for c in b.considerations)


def test_a_medical_incident_surfaces_the_nearest_emergency_department():
    inc = Incident("IC-2", "1001 Van Ness Avenue", "unresponsive patient, possible cardiac arrest")
    b = synthesize(inc, evidence())
    assert any("hospital" in c.text.lower() or "CPMC" in c.text for c in b.resources)


def test_every_recommendation_is_marked_advisory():
    assert "advisory" in synthesize(fire(), evidence()).render().lower()


def test_nothing_in_the_brief_is_an_unsourced_external_claim():
    # The headline reliability number, asserted structurally.
    assert synthesize(fire(), evidence()).unsupported == ()


# ── phrasings the evaluation suite caught us missing ───────────────────
#
# Each of these was classified UNKNOWN by the first version. "Shots reported"
# reaching an armed-incident workflow as an unclassified call is the kind of
# miss that matters, and a regex written from one example sentence is how it
# happens.

@pytest.mark.parametrize("text,kind", [
    ("Shots reported at 1001 Van Ness Avenue", Kind.ARMED),
    ("Shot fired at 1001 Van Ness Avenue", Kind.ARMED),
    ("Fumes reported at 1001 Van Ness Avenue", Kind.GAS),
    ("Vulnerable adult has not returned to 1001 Van Ness Avenue", Kind.MISSING_PERSON),
    ("Child separated from parents at 1001 Van Ness Avenue", Kind.MISSING_PERSON),
])
def test_the_classifier_handles_the_phrasings_the_suite_found(text, kind):
    assert classify(text) is kind


def test_widening_the_patterns_did_not_swallow_unrelated_calls():
    # "shot" must not catch "gunshot residue training exercise" style noise,
    # and the guard against over-matching is that plain descriptions stay
    # unclassified rather than being forced into a category.
    assert classify("noise complaint at 1001 Van Ness Avenue") is Kind.UNKNOWN


def test_an_unspecified_building_tag_is_not_reported_as_a_finding():
    # OSM's `building=yes` means "this is a building, type unspecified". Showing
    # it as "structure type: yes" is noise dressed as intelligence.
    from ic.cases import _building
    from ic.reason import build_picture as _bp
    inc = Incident("IC-T", "1001 Van Ness Avenue", "fire")
    picture = _bp(inc, evidence(building=_building(("structure type", "yes"),
                                                   ("storeys", "13"))))
    building = next(a for a in picture.situation if a.field == "building")
    assert "structure type: yes" not in (building.value or "")
    assert "13" in (building.value or "")


# ── neither hazard path may claim the site is safe ────────────────────
#
# Two branches produce the hazards row: one when the scan returns only
# exposures, one when it returns nothing at all. Only the first got corrected
# when the wording was fixed, so the empty-scan case went on reading as
# "no hazards" — which is a claim this system cannot make. It searched a map of
# the surroundings; it knows nothing about what is inside the building.

@pytest.mark.parametrize("hazards_result", [
    "empty_list",     # scan ran, found nothing at all
    "exposures_only",  # scan ran, found only things that are not hazards
])
def test_no_hazard_path_claims_the_site_is_free_of_hazards(hazards_result):
    from ic.cases import _evidence, _hazards, _exposures
    from ic.reason import build_picture

    over = ({"hazards": _hazards(), "exposures": _exposures()}
            if hazards_result == "empty_list"
            else {"hazards": _hazards(),
                  "exposures": _exposures(("A School", "school", 200.0, 0.0, 0.002))})
    picture = build_picture(
        Incident("IC-H", "1001 Van Ness Avenue", "structure fire"),
        _evidence(**over))

    row = next(a for a in picture.threats if "hazard" in a.field)
    text = f"{row.value} {row.evidence}".lower()
    assert "does not establish" in text, (
        f"the {hazards_result} path reads as an all-clear: {row.value!r}")
