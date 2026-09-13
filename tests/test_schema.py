"""The incident schema: what Argus is required to determine, and how sure it is."""

from __future__ import annotations

import pytest

from ic.schema import (
    Assessment,
    Band,
    Picture,
    Status,
    required_for,
)
from ic.reason import Kind
from ic.tools.base import Source

OSM = Source("OpenStreetMap", "https://openstreetmap.org")


# ------------------------------------------------------------- the four states


def test_a_verified_assessment_must_name_a_source():
    # VERIFIED is the only status that asserts the world. It has to be able to
    # say who says so.
    with pytest.raises(ValueError):
        Assessment.verified("storeys", "13", "building record", source=None)


def test_a_reported_assessment_is_the_caller_and_needs_no_source():
    a = Assessment.reported("occupancy", "possible occupants inside")
    assert a.status is Status.REPORTED
    assert a.source is None


def test_an_inferred_assessment_records_what_it_came_from():
    a = Assessment.inferred("access", "aerial required", "13 storeys", 0.7)
    assert a.status is Status.INFERRED
    assert "13 storeys" in a.evidence


def test_an_unknown_field_carries_no_value_and_claims_nothing():
    a = Assessment.unknown("hazmat", "no source consulted holds this")
    assert a.status is Status.UNKNOWN
    assert a.value is None
    assert a.confidence == 0.0


def test_reported_never_becomes_verified_by_being_useful():
    a = Assessment.reported("occupancy", "someone may still be inside")
    assert a.status is not Status.VERIFIED


# ------------------------------------------------------------- confidence band


@pytest.mark.parametrize("status,band", [
    (Status.VERIFIED, Band.HIGH),
    (Status.REPORTED, Band.LOW),
    (Status.UNKNOWN, Band.NONE),
])
def test_the_band_follows_the_status(status, band):
    made = {
        Status.VERIFIED: Assessment.verified("f", "v", "e", OSM),
        Status.REPORTED: Assessment.reported("f", "v"),
        Status.UNKNOWN: Assessment.unknown("f", "e"),
    }[status]
    assert made.band is band


def test_an_inference_from_strong_evidence_bands_medium():
    assert Assessment.inferred("f", "v", "e", 0.75).band is Band.MEDIUM


# ------------------------------------------------------------- the picture


def picture(**kw):
    base = dict(
        situation=(Assessment.verified("location", "1001 Van Ness", "geocoder", OSM),),
        people=(Assessment.reported("occupancy", "someone may be inside"),),
        threats=(),
        resources=(Assessment.verified("fire_station", "SFFD 3 — 0.3 km", "OSM", OSM),),
    )
    base.update(kw)
    return Picture(**base)


def test_the_picture_separates_what_is_verified_from_what_is_reported():
    p = picture()
    assert len(p.by_status(Status.VERIFIED)) == 2
    assert len(p.by_status(Status.REPORTED)) == 1


def test_every_verified_item_in_a_picture_is_attributable():
    assert picture().attribution_rate == 1.0


def test_an_empty_section_is_not_the_same_as_a_missing_one():
    # "We looked and found nothing" and "we never looked" must not render
    # identically, or the reader cannot tell diligence from silence.
    p = picture(threats=(Assessment.unknown("hazmat", "not consulted"),))
    assert p.unknown_fields == ("hazmat",)


# --------------------------------------------------- the schema drives the work


def test_a_fire_requires_building_and_access_to_be_determined():
    assert "building" in required_for(Kind.FIRE)
    assert "access" in required_for(Kind.FIRE)


def test_a_medical_incident_requires_the_nearest_hospital():
    assert "hospital" in required_for(Kind.MEDICAL)


def test_an_armed_incident_requires_the_threat_to_be_characterised():
    assert "threat" in required_for(Kind.ARMED)


def test_the_gaps_are_the_fields_the_schema_wants_and_the_picture_lacks():
    # This is the mechanism that makes investigation goal-driven rather than a
    # fixed script: what is still UNKNOWN is what the agent goes and looks for.
    p = picture()
    gaps = p.gaps(Kind.FIRE)
    assert "building" in gaps
    assert "location" not in gaps


def test_a_field_already_determined_is_not_a_gap():
    p = picture(situation=(
        Assessment.verified("location", "x", "geocoder", OSM),
        Assessment.verified("building", "3 storey commercial", "record", OSM),
    ))
    assert "building" not in p.gaps(Kind.FIRE)


def test_a_field_explicitly_unknown_is_still_a_gap_worth_reporting():
    p = picture(threats=(Assessment.unknown("hazmat", "not consulted"),))
    assert "hazmat" in p.unknown_fields


def test_completeness_measures_how_much_of_the_schema_was_answered():
    thin = picture()
    assert 0.0 < thin.completeness(Kind.FIRE) < 1.0


# ── the caller's report is never suppressed by a map tag ───────────────
#
# Found by reading a live run. The caller said "someone may still be inside";
# the PEOPLE section showed only `occupancy: social_facility` from the building
# record, and the trapped-person report had been dropped — because the two were
# competing for one field in an if/elif.
#
# They are not the same question. What a building is *used for* is a property
# record. Who is inside it *right now* is the caller, and in a fire it is the
# single most operationally urgent thing anyone will say.

from ic.reason import Incident, build_picture
from ic.cases import _evidence
from ic.schema import Status as _S


def _people(text):
    return {a.field: a for a in build_picture(
        Incident("IC-T", "1001 Van Ness Avenue", text), _evidence()).people}


def test_a_reported_occupant_survives_a_building_record_that_names_occupancy():
    people = _people("structure fire, someone may still be inside")
    assert "persons_reported" in people
    assert people["persons_reported"].status is _S.REPORTED


def test_the_building_use_is_still_verified_alongside_it():
    people = _people("structure fire, someone may still be inside")
    assert people["occupancy"].status is _S.VERIFIED
    assert people["occupancy"].value == "social_facility"


def test_a_reported_occupant_is_never_promoted_to_verified():
    people = _people("someone may still be inside")
    assert people["persons_reported"].status is not _S.VERIFIED


def test_no_mention_of_people_means_no_reported_occupant_field():
    # Silence is not a report. Inventing one would be worse than omitting it.
    assert "persons_reported" not in _people("smoke showing from the roof")


def test_the_reported_occupant_keeps_the_callers_own_words():
    people = _people("two children may be trapped on the ninth floor")
    assert "trapped" in (people["persons_reported"].value or "")


def test_the_reported_occupant_carries_only_the_clause_about_people():
    # Echoing the whole description duplicates the report line above it and
    # truncates to uselessness on screen. The useful part is the clause the
    # caller used about a person.
    people = _people(
        "Structure fire at 1001 Van Ness Avenue. Caller reports smoke from the "
        "second floor and someone may still be inside."
    )
    value = people["persons_reported"].value or ""
    assert "someone may still be inside" in value
    assert "Structure fire at" not in value


# ── contradiction is a state, not a footnote ──────────────────────────


def test_a_contradicted_field_carries_both_accounts():
    from ic.schema import Assessment as A
    a = A.contradicted("building", "caller says 3 storeys", "record says 13",
                       "the two sources disagree")
    assert "3" in a.value and "13" in a.value


def test_a_contradicted_field_is_not_verified():
    from ic.schema import Assessment as A, Status as S
    a = A.contradicted("building", "caller: 3", "record: 13", "disagree")
    assert a.status is S.CONTRADICTED
    assert a.band.value == "Low"


# ── what no source can answer before units arrive ─────────────────────
#
# The first version reported "0 unknown" on a structure fire, which is worse
# than useless — nobody knew whether a fire was actually burning, whether
# anyone was trapped, or what the severity was. A completeness score that
# reaches 100% while those are open is measuring the wrong thing.


def test_a_fire_has_questions_no_public_source_can_answer():
    from ic.schema import unverifiable_for
    fields = unverifiable_for("fire")
    assert "persons_trapped" in fields
    assert "severity" in fields


def test_every_incident_kind_has_at_least_one_open_question():
    from ic.schema import unverifiable_for
    for kind in ("fire", "medical", "gas", "armed", "missing person"):
        assert unverifiable_for(kind), kind


def test_unverifiable_fields_are_separate_from_the_required_ones():
    # Required fields are what Argus should go and find. Unverifiable fields
    # are what it must admit it cannot. Mixing them would make the agent chase
    # answers that do not exist.
    from ic.schema import required_for, unverifiable_for
    assert not (set(required_for("fire")) & set(unverifiable_for("fire")))


# ── attribution as a link, not a label ────────────────────────────────


def test_a_verified_assessment_carries_the_evidence_id_it_rests_on():
    from ic.schema import Assessment as A
    from ic.tools.base import Source
    src = Source("OpenStreetMap")
    a = A.verified("storeys", "13", "building record", src, evidence_ids=("EV-003",))
    assert a.evidence_ids == ("EV-003",)


def test_an_inference_names_the_evidence_it_was_drawn_from():
    from ic.schema import Assessment as A
    a = A.inferred("access", "ladder company", "13 storeys", 0.75,
                   evidence_ids=("EV-003",))
    assert "EV-003" in a.evidence_ids


def test_a_reported_item_has_no_evidence_id_because_the_caller_is_the_source():
    from ic.schema import Assessment as A
    assert A.reported("persons_reported", "someone inside").evidence_ids == ()


def test_the_picture_reports_how_many_verified_items_trace_to_evidence():
    from ic.schema import Assessment as A, Picture
    from ic.tools.base import Source
    src = Source("OSM")
    p = Picture(situation=(
        A.verified("a", "1", "e", src, evidence_ids=("EV-001",)),
        A.verified("b", "2", "e", src, evidence_ids=("EV-002",)),
    ))
    assert p.traceability == 1.0


def test_a_verified_item_with_no_evidence_id_drags_traceability_down():
    # The source string alone is a label. Anything can write "OpenStreetMap".
    from ic.schema import Assessment as A, Picture
    from ic.tools.base import Source
    src = Source("OSM")
    p = Picture(situation=(
        A.verified("a", "1", "e", src, evidence_ids=("EV-001",)),
        A.verified("b", "2", "e", src),
    ))
    assert p.traceability == 0.5


# ── an open question has to earn its line ─────────────────────────────
#
# The list is read under pressure, and every entry that restates the call
# pushes the ones that decide the incident further down it.


def test_an_open_question_does_not_restate_the_call():
    from ic.schema import unverifiable_for
    # Somebody has rung to report a fire. "Is there a fire?" is not a finding,
    # and crews roll on the report either way.
    assert "fire_confirmed" not in unverifiable_for("fire")
    assert "leak_confirmed" not in unverifiable_for("gas")


def test_the_questions_that_decide_the_incident_survive():
    from ic.schema import unverifiable_for
    fire = unverifiable_for("fire")
    for field in ("persons_trapped", "severity", "hazmat", "current_access"):
        assert field in fire


def test_an_armed_call_still_asks_whether_there_is_a_weapon():
    from ic.schema import unverifiable_for
    # Deliberately not symmetrical with fire. "Shots heard" and "an armed
    # person is present" are different scenes with different approaches, so
    # confirming the weapon changes what police do; confirming a fire does not
    # change what an engine does.
    assert "weapon_confirmed" in unverifiable_for("armed")


def test_occupancy_is_not_an_obligation_the_map_cannot_meet():
    from ic.schema import required_for
    # What a building is *used for* is worth showing when a record has it, and
    # it still drives the evacuation-assistance consideration. But most
    # addresses carry no such tag, so requiring it scored every ordinary
    # incident as incomplete for a fact that changes nothing about the response.
    for kind in ("fire", "medical", "armed", "missing person"):
        assert "occupancy" not in required_for(kind)
