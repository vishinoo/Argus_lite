"""A call is not one sentence. Information keeps arriving while the line is open.

The first version took a single description and produced one picture, which is
a transcription of how a demo works rather than how a call works. A dispatcher
learns the building is bigger than they thought, that someone got out, that the
smoke has changed colour — and each of those either fills a gap or contradicts
something already recorded.
"""

from ic.reason import Incident, build_picture, classify
from ic.schema import Status
from tests.test_reason import evidence, building


def picture(description, *updates):
    return build_picture(
        Incident("IC-1", "1 Market Street", description, updates=updates),
        evidence(),
    )


def fields(p):
    return {a.field: a for a in p.all}


def test_an_incident_with_no_updates_is_unchanged():
    p = picture("structure fire, smoke showing")
    assert fields(p)["report"].value == "structure fire, smoke showing"


def test_the_original_report_survives_an_update():
    # The first thing said is evidence about the call and does not get
    # overwritten by the second thing said.
    p = picture("structure fire, smoke showing", "caller now says the smoke is black")
    assert fields(p)["report"].value == "structure fire, smoke showing"


def test_an_update_is_carried_as_its_own_reported_row():
    p = picture("structure fire, smoke showing", "caller now says the smoke is black")
    updates = [a for a in p.all if a.field.startswith("update")]
    assert len(updates) == 1
    assert updates[0].status is Status.REPORTED
    assert "black" in updates[0].value


def test_updates_are_numbered_in_the_order_they_arrived():
    p = picture("structure fire", "second floor now involved", "roof is sagging")
    updates = [a for a in p.all if a.field.startswith("update")]
    assert [a.value for a in updates] == ["second floor now involved", "roof is sagging"]


def test_an_update_never_becomes_verified():
    # It is still a person on a phone. Arriving later does not make it a record.
    p = picture("structure fire", "there are exactly four people on the third floor")
    for a in p.all:
        if a.field.startswith("update"):
            assert a.status is Status.REPORTED


def test_an_update_can_contradict_the_building_record():
    # The record says 13 storeys. The caller, later, says 40. Argus is not
    # positioned to pick a winner and says so.
    p = build_picture(
        Incident("IC-1", "1 Market Street", "structure fire",
                 updates=("caller says it is a 40 storey tower",)),
        evidence(building=building(("storeys", "13"))),
    )
    assert fields(p)["storeys"].status is Status.CONTRADICTED


def test_an_update_can_surface_people_the_first_call_did_not_mention():
    p = picture("smoke alarm sounding", "caller now says two people are still inside")
    people = fields(p)
    assert "persons_reported" in people
    assert "two people" in people["persons_reported"].value


def test_an_update_can_change_what_kind_of_incident_this_is():
    # A call that opens as an alarm and becomes a fire is the normal case, not
    # an edge case, and the schema that drives the investigation has to follow.
    assert classify("automatic alarm at the premises").value != "fire"
    assert classify("automatic alarm at the premises. flames now showing "
                    "from the second floor").value == "fire"


def test_full_text_carries_everything_said():
    inc = Incident("IC-1", "1 Market Street", "structure fire", updates=("roof sagging",))
    assert "structure fire" in inc.full_text
    assert "roof sagging" in inc.full_text


def test_the_join_between_statements_is_a_sentence_boundary():
    # Joined with a bare space, "…smoke showing" + "caller now says two people
    # are inside" became one clause, and the people row rendered as "smoke
    # showing caller now says two people are inside". Separate statements are
    # separate sentences.
    p = picture("structure fire, smoke showing",
                "caller now says two people are still inside")
    reported = fields(p)["persons_reported"].value
    assert not reported.startswith("smoke showing")
    assert "two people are still inside" in reported


def test_a_statement_that_already_ends_in_a_stop_is_not_double_punctuated():
    inc = Incident("IC-1", "1 Market Street", "Structure fire.", updates=("Roof sagging.",))
    assert ".." not in inc.full_text
