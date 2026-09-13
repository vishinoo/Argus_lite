"""The EMS recommendations: what a medical call needs that a fire call does not."""

import pytest

from ic.ems import recommendations
from ic.schema import Status


def fields(items):
    return {a.field: a for a in items}


def test_a_fire_call_gets_no_ems_recommendations():
    # The fire picture already carries aerial access and upwind approach. EMS
    # advice on a structure fire would be a section nobody reads.
    assert recommendations("fire", "structure fire", storeys=13, hospital=None) == ()


def test_a_multi_storey_building_raises_stretcher_access():
    out = fields(recommendations("medical", "cardiac arrest", storeys=13, hospital=None))
    assert "ems_access" in out
    assert out["ems_access"].status is Status.INFERRED
    assert "13" in out["ems_access"].value


def test_stretcher_access_does_not_claim_to_know_the_patient_floor():
    # `building:levels` is a fact about the building. Which floor the patient is
    # on is not established by any source consulted, and an EMS crew planning a
    # carry needs to know that is still open rather than assume the worst case
    # was computed for them.
    out = fields(recommendations("medical", "cardiac arrest", storeys=13, hospital=None))
    text = f"{out['ems_access'].value} {out['ems_access'].evidence}".lower()
    assert "not established" in text or "not known" in text


def test_a_ground_floor_building_raises_no_carry():
    out = fields(recommendations("medical", "fall", storeys=1, hospital=None))
    assert "ems_access" not in out


@pytest.mark.parametrize("described", [
    "cardiac arrest, CPR in progress",
    "patient is unresponsive and not breathing",
    "choking, turning blue",
])
def test_a_time_critical_presentation_is_flagged(described):
    out = fields(recommendations("medical", described, storeys=None,
                                 hospital="CPMC Van Ness — 0.1 km, est. 2:36"))
    assert "transport" in out
    assert "CPMC Van Ness" in out["transport"].value


def test_an_ordinary_medical_call_does_not_claim_time_critical():
    out = fields(recommendations("medical", "ankle injury, patient conscious",
                                 storeys=None,
                                 hospital="CPMC Van Ness — 0.1 km, est. 2:36"))
    assert "TIME-CRITICAL" not in (out.get("transport").value if out.get("transport") else "")


def test_no_hospital_means_no_transport_recommendation():
    # Recommending transport to a hospital that was never found is exactly the
    # kind of confident nonsense the rest of this system exists to prevent.
    out = fields(recommendations("medical", "cardiac arrest", storeys=None, hospital=None))
    assert "transport" not in out


def test_recommendations_are_never_verified():
    # These are advisory. Nothing here is an external record, so nothing here
    # may wear the state that means one.
    for kind, desc, st, hosp in [
        ("medical", "cardiac arrest", 13, "CPMC — 0.1 km"),
        ("medical", "fall", 1, None),
    ]:
        for a in recommendations(kind, desc, storeys=st, hospital=hosp):
            assert a.status is not Status.VERIFIED


def test_transport_does_not_claim_an_emergency_department():
    # OpenStreetMap's `amenity=hospital` covers counselling clinics and
    # outpatient surgery centres. Live, this recommended transporting a cardiac
    # arrest to "Cityscape Counseling" and called it the nearest emergency
    # department — an unsupported claim of exactly the kind the rest of this
    # system exists to refuse, and a dangerous one.
    out = fields(recommendations("medical", "cardiac arrest", storeys=None,
                                 hospital="Cityscape Counseling — 1.2 km"))
    assert "emergency department" not in out["transport"].value.lower()


def test_transport_says_that_capability_is_unestablished():
    out = fields(recommendations("medical", "cardiac arrest", storeys=None,
                                 hospital="Cityscape Counseling — 1.2 km"))
    text = f"{out['transport'].value} {out['transport'].evidence}".lower()
    assert "not established" in text


# ── the floor the patient is on ───────────────────────────────────────
#
# The building record gives the building's height. The caller gives the thing
# that actually decides the carry, and says it in whatever form they like.


@pytest.mark.parametrize("said", [
    "patient is on the 9th floor",
    "patient is on the ninth floor",
    "patient on floor 9",
    "cardiac arrest, 9th floor",
])
def test_a_reported_floor_is_read_however_it_is_phrased(said):
    from ic.ems import patient_floor
    assert patient_floor(said) == 9


def test_a_ground_floor_report_is_read_as_ground():
    from ic.ems import patient_floor
    assert patient_floor("patient is on the ground floor") == 0


def test_no_floor_mentioned_reads_as_unknown():
    from ic.ems import patient_floor
    assert patient_floor("cardiac arrest, CPR in progress") is None


def test_a_reported_floor_drives_the_carry_even_with_no_building_record():
    # Willis Tower carries no storeys tag, so the building record said nothing
    # and the caller's "ninth floor" went unread. The caller is the better
    # source here anyway: the building's height was never the question.
    out = fields(recommendations("medical", "cardiac arrest, patient on the 9th floor",
                                 storeys=None, hospital=None))
    assert "ems_access" in out
    assert "9" in out["ems_access"].value


def test_the_reported_floor_is_marked_as_the_callers_word():
    out = fields(recommendations("medical", "cardiac arrest, patient on the 9th floor",
                                 storeys=None, hospital=None))
    assert "caller" in out["ems_access"].evidence.lower()


def test_a_ground_floor_patient_raises_no_carry():
    out = fields(recommendations("medical", "patient on the ground floor",
                                 storeys=20, hospital=None))
    assert "ems_access" not in out
