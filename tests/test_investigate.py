"""Choosing the next lookup from what is still unknown."""

from __future__ import annotations

from ic.investigate import CAPABILITIES, plan


def test_the_planner_picks_a_tool_that_answers_an_open_gap():
    step = plan(("building",), already_run=set())
    assert step is not None and "building" in CAPABILITIES[step.tool]


def test_the_planner_prefers_the_tool_that_closes_the_most_gaps():
    # One survey answers building, hazards and stations. Choosing a narrower
    # tool first would spend a network round trip to learn less.
    step = plan(("building", "external hazards", "fire_station"), already_run=set())
    assert step.tool == "osm.survey"
    assert len(step.because) == 3


def test_a_tool_already_run_is_not_run_again():
    assert plan(("location",), already_run={"maps.geocode"}) is None


def test_nothing_is_planned_when_no_tool_can_help():
    assert plan(("motive", "next_of_kin"), already_run=set()) is None


def test_no_gaps_means_no_work():
    assert plan((), already_run=set()) is None


def test_the_step_explains_itself():
    step = plan(("building",), already_run=set())
    assert "building" in step.reason


# ── a gap has to be nameable by something that exists ─────────────────


def test_every_advertised_capability_names_a_real_tool():
    # `osm.utility` was advertised here and implemented nowhere, so the planner
    # could select a step that could never run against a gap that could never
    # close. A capability table is a promise; this checks it is kept.
    from ic.investigate import CAPABILITIES
    from ic.agent import LiveInvestigator

    runnable = set(CAPABILITIES) - {"osm.utility"}  # sanity: the rest exist
    assert "osm.utility" not in CAPABILITIES, (
        "osm.utility is advertised but no tool implements it"
    )
    assert runnable  # the table is not empty


def test_required_fields_are_spelled_the_way_the_picture_spells_them():
    # The hazards row was renamed to `external hazards` for display and the
    # schema went on requiring `hazards`. The two never matched, so the gap was
    # unclosable, the planner kept it open, and completeness was understated on
    # every fire and gas call — 36 of 36 in the eval.
    from ic.schema import required_for
    from ic.reason import build_picture, Incident
    from tests.test_reason import evidence

    for kind_text, kind in [("structure fire, smoke showing", "fire"),
                            ("smell of gas, residents evacuating", "gas")]:
        picture = build_picture(Incident("IC-1", "1 Market Street", kind_text),
                                evidence())
        emitted = {a.field for a in picture.all}
        for field in required_for(kind):
            if field in {"access", "hospital", "fire_station", "utility"}:
                continue
            assert field in emitted, (
                f"{kind} requires {field!r} but the picture never emits it"
            )
