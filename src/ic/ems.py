"""What a medical call needs that a fire call does not.

The fire picture had a second agent working the approach — upwind side, plume,
water supply — and a medical call got none of that attention. It inherited a
building record and a nearest hospital and stopped, which is a fire brief with
the fire removed.

Two things here are derivable from evidence already gathered and are the ones
an EMS crew actually plans around.

**Getting to the patient.** A carry down thirteen storeys is a different job
from a carry down one, and it is decided before the ambulance leaves. The
building record gives the height. It emphatically does not give the floor the
patient is on, and this module says so rather than letting a reader assume the
worst case was computed for them.

**Getting the patient away.** For a time-critical presentation the destination
and the time to it are the plan. Both come from the resources already found, so
this adds no new lookup — but it will not name a destination that was never
found, because recommending transport to a hospital nobody located is the kind
of confident nonsense the rest of this system exists to prevent.

It also will not call that destination an emergency department. OpenStreetMap's
`amenity=hospital` covers counselling clinics and outpatient surgery centres,
and live this recommended transporting a cardiac arrest to "Cityscape
Counseling" under that heading. The nearest *mapped hospital* is what the
evidence supports; whether it can receive this patient is a question for the
crew, and the row says so.

Everything here is INFERRED. None of it is a record.
"""

from __future__ import annotations

import re

from ic.schema import Assessment

# Above the ground floor a stretcher stops being a straightforward carry and
# starts depending on a lift, a stair turn and how many hands are on scene.
_CARRY_STOREYS = 3

# Above the ground floor the carry depends on a lift. Reported floor 1 is the
# ground floor in the caller's own counting often enough that 2 is the point
# where it is worth raising.
_CARRY_FLOOR = 2

# Presentations where the clock is the treatment. Deliberately narrow: this
# flags what the caller actually described, and an EMS crew reading
# TIME-CRITICAL on an ankle injury would stop reading it anywhere.
_TIME_CRITICAL = re.compile(
    r"\b(cardiac arrest|not breathing|unresponsive|no pulse|cpr|choking|"
    r"turning blue|anaphyla\w*|stroke|haemorrhag\w*|hemorrhag\w*|"
    r"severe bleeding)\b",
    re.I,
)


_ORDINAL_WORDS = {
    "ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20,
}

# "9th floor", "ninth floor", "floor 9". Callers use all three and the carry is
# the same either way.
_FLOOR_DIGIT = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?[\s-]*(?:floor|storey|story|level)\b", re.I)
_FLOOR_AFTER = re.compile(r"\b(?:floor|storey|story|level)\s*(\d{1,2})\b", re.I)
_FLOOR_WORD = re.compile(
    r"\b(" + "|".join(_ORDINAL_WORDS) + r")[\s-]*(?:floor|storey|story|level)\b", re.I)


def patient_floor(description: str) -> int | None:
    """The floor the caller put the patient on, however they phrased it.

    This is the number that actually decides the carry. The building record
    gives the building's height, which was never the question — and for the
    towers where it matters most, OpenStreetMap frequently has no height at all.
    """
    text = description or ""
    for pattern in (_FLOOR_DIGIT, _FLOOR_AFTER):
        m = pattern.search(text)
        if m:
            return int(m.group(1))
    m = _FLOOR_WORD.search(text)
    if m:
        return _ORDINAL_WORDS[m.group(1).lower()]
    return None


def _kind_name(kind) -> str:
    return getattr(kind, "value", str(kind))


def recommendations(kind, description: str, storeys: int | None,
                    hospital: str | None) -> tuple[Assessment, ...]:
    """Advisory rows for a medical call. Empty for anything else."""
    if _kind_name(kind) != "medical":
        return ()

    out: list[Assessment] = []

    # The caller's floor beats the building's height, and is often the only one
    # of the two that exists.
    floor = patient_floor(description)
    if floor is not None and floor >= _CARRY_FLOOR:
        out.append(
            Assessment.inferred(
                "ems_access",
                f"CONSIDER: patient reported on floor {floor} — confirm lift "
                "availability and a stretcher route",
                "the caller placed the patient on that floor; not independently "
                "verified, and the lift's condition is not established",
                0.5,
            )
        )
    elif floor is None and storeys is not None and storeys >= _CARRY_STOREYS:
        out.append(
            Assessment.inferred(
                "ems_access",
                f"CONSIDER: {storeys}-storey building — confirm lift "
                "availability and a stretcher route",
                f"building record gives {storeys} storeys; the floor the "
                "patient is on is not established by any source consulted",
                0.6,
            )
        )

    if hospital:
        urgent = bool(_TIME_CRITICAL.search(description or ""))
        prefix = "TIME-CRITICAL — " if urgent else ""
        out.append(
            Assessment.inferred(
                "transport",
                f"{prefix}RECOMMENDATION: nearest mapped hospital {hospital}",
                "nearest place tagged as a hospital; whether it has an "
                "emergency department, and whether it is accepting, is not "
                "established by the map record. The caller's description "
                + ("names a time-critical presentation"
                   if urgent else "does not name a time-critical presentation"),
                0.7 if urgent else 0.55,
            )
        )

    return tuple(out)
