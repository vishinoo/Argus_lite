"""What an armed incident needs that a fire does not."""

from ic.police import recommendations
from ic.schema import Status


def fields(items):
    return {a.field: a for a in items}


def test_a_fire_gets_no_police_recommendations():
    assert recommendations("fire", [("Sacred Heart School", "school", 207.0)]) == ()


def test_a_school_near_a_shooting_raises_a_lockdown_consideration():
    out = fields(recommendations("armed", [("Sacred Heart School", "school", 207.0)]))
    assert "containment" in out
    assert "Sacred Heart School" in out["containment"].value
    assert out["containment"].status is Status.INFERRED


def test_nothing_nearby_raises_nothing():
    # Silence is correct here. A "no lockdown needed" row would be a claim about
    # the surroundings that a map search cannot support.
    assert recommendations("armed", []) == ()


def test_a_distant_place_is_not_a_containment_concern():
    out = fields(recommendations("armed", [("Some School", "school", 4000.0)]))
    assert "containment" not in out


def test_the_recommendation_names_how_far_away_it_is():
    out = fields(recommendations("armed", [("Sacred Heart School", "school", 207.0)]))
    assert "207" in out["containment"].value


def test_it_never_claims_to_have_verified_anything():
    for a in recommendations("armed", [("Sacred Heart School", "school", 207.0)]):
        assert a.status is not Status.VERIFIED
