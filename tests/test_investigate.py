"""Choosing the next lookup from what is still unknown."""

from __future__ import annotations

from ic.investigate import CAPABILITIES, plan


def test_the_planner_picks_a_tool_that_answers_an_open_gap():
    step = plan(("building",), already_run=set())
    assert step is not None and "building" in CAPABILITIES[step.tool]


def test_the_planner_prefers_the_tool_that_closes_the_most_gaps():
    # One survey answers building, hazards and stations. Choosing a narrower
    # tool first would spend a network round trip to learn less.
    step = plan(("building", "hazards", "fire_station"), already_run=set())
    assert step.tool == "osm.survey"
    assert len(step.because) == 3


def test_a_tool_already_run_is_not_run_again():
    assert plan(("location",), already_run={"maps.geocode"}) is None


def test_nothing_is_planned_when_no_tool_can_help():
    assert plan(("motive", "next_of_kin"), already_run=set()) is None


def test_no_gaps_means_no_work():
    assert plan((), already_run=set()) is None


def test_the_step_explains_itself():
    step = plan(("utility",), already_run=set())
    assert "utility" in step.reason
