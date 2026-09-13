"""Information arrives in pieces, and the picture has to hold all of it.

Reported live: a caller says "one person down", then "another person is down",
and the people row changed from the first to the second instead of carrying
both. Two people were down and the brief named one of them.

The cause was picking a single clause by length. Whichever statement happened
to be longest won and the rest were discarded — so an update could silently
erase the opening call, or be silently erased by it.
"""

from ic.reason import Incident, build_picture
from tests.test_reason import evidence


def picture(description, *updates):
    return build_picture(
        Incident("IC-1", "350 5th Avenue", description, updates=updates), evidence())


def fields(p):
    return {a.field: a for a in p.all}


def test_a_second_casualty_does_not_replace_the_first():
    p = picture("Shots reported. One person down, suspect seen leaving on foot.",
                "another person is down")
    said = fields(p)["persons_reported"].value
    assert "One person down" in said
    assert "another person is down" in said


def test_a_shorter_update_is_not_swallowed_by_a_longer_opening_line():
    # The failing case was length-based: a brief update lost to a wordy first
    # sentence and never appeared at all.
    p = picture("Structure fire, caller reports someone may still be inside the building",
                "two more inside")
    said = fields(p)["persons_reported"].value
    assert "two more inside" in said


def test_the_same_thing_said_twice_is_carried_once():
    p = picture("structure fire, someone may still be inside",
                "someone may still be inside")
    said = fields(p)["persons_reported"].value
    assert said.count("someone may still be inside") == 1


def test_statements_keep_the_order_they_were_made_in():
    p = picture("Shots reported. One person down.", "another person is down")
    said = fields(p)["persons_reported"].value
    assert said.index("One person down") < said.index("another person is down")


def test_the_threat_row_is_about_the_threat_not_the_casualties():
    # It carried `full_text`, so the console truncated it to the opening words
    # and every update looked like it had been ignored. Casualties are a fact
    # about people and belong in that row, not this one.
    p = picture("Shots reported at 350 5th Avenue, New York. One person down, "
                "suspect seen leaving on foot.", "another person is down")
    threat = fields(p)["threat"].value
    assert "another person is down" not in threat
    assert "suspect seen leaving on foot" in threat
    assert "another person is down" in fields(p)["persons_reported"].value


def test_the_threat_row_reflects_what_was_added():
    p = picture("Shots reported, one person down.", "suspect now says he has a knife")
    assert "knife" in fields(p)["threat"].value


def test_an_occupancy_tag_of_yes_is_not_shown_as_a_fact():
    # `office=yes` became "occupancy: yes" in its own row. It says only that
    # the key exists.
    from tests.test_reason import building
    p = build_picture(
        Incident("IC-1", "350 5th Avenue", "structure fire"),
        evidence(building=building(("storeys", "102"), ("occupancy", "yes"))),
    )
    assert "occupancy" not in fields(p)
