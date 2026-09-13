"""What an armed incident needs that a fire does not.

The fire picture had an agent working the approach and a medical call now has
one working access and transport. An armed incident had neither, and worse: it
inherited the fire one, so a report of shots fired came back recommending a
hydrant and a responding engine.

What an armed incident does need, and what the evidence already supports, is
the question of who else is close enough to matter. A school two hundred metres
from a scene with a suspect still outstanding is a lockdown decision, and it is
a decision somebody has to make early. The surroundings scan has already found
those places for the fire case's exposure list; this reads the same rows with a
different question in mind.

It says nothing when nothing is near. A "no lockdown required" row would be a
claim about the surroundings that a map search cannot support.
"""

from __future__ import annotations

from ic.schema import Assessment

# Close enough that a scene with an outstanding suspect is a decision for the
# people inside. Beyond this it is a notification, not a containment question.
_CONTAINMENT_M = 500.0

_RELEVANT = {"school", "hospital", "kindergarten", "college", "university",
             "care_home", "nursing_home"}


def _kind_name(kind) -> str:
    return getattr(kind, "value", str(kind))


def recommendations(kind, nearby) -> tuple[Assessment, ...]:
    """Advisory rows for an armed incident. Empty for anything else.

    `nearby` is a sequence of (name, kind, distance_m).
    """
    if _kind_name(kind) != "armed":
        return ()

    close = [
        (name, place_kind, metres) for name, place_kind, metres in nearby
        if metres <= _CONTAINMENT_M and place_kind in _RELEVANT
    ]
    if not close:
        return ()

    close.sort(key=lambda row: row[2])
    described = "; ".join(f"{name} — {metres:.0f} m" for name, _, metres in close[:3])
    return (
        Assessment.inferred(
            "containment",
            f"CONSIDER: lockdown notification — {described}",
            "mapped places within "
            f"{_CONTAINMENT_M:.0f} m; whether they are occupied, and whether the "
            "suspect is still outstanding, is not established here",
            0.55,
        ),
    )
