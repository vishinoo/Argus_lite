"""Which side to come in from, and what is in the plume.

This is the second agent, and it answers a different question from the first.
The intelligence agent asks *what is here*. This one asks *what do you do about
where it is* — and the difference between a fact and a tactic is mostly wind.

Three things follow from wind direction, and none of them are visible in a list
of nearby places:

**Approach from upwind.** A crew that stages downwind works the incident from
inside its own smoke plume. Wind from the west means come in from the west.

**Exposures are not symmetric.** A school 200 m east of a fire with a westerly
wind is in the plume; the same school 200 m west is not. A brief that lists the
school without saying which has given a fact and withheld its meaning.

**Water has a side too.** The nearest hydrant matters, and so does whether
reaching it means crossing the plume.

Everything here is INFERRED and says so. Wind shifts, OpenStreetMap is
incomplete, and the officer on arrival can see things no map holds. The plume
arc is 30 degrees either side of the wind axis — a conventional approximation
that errs towards including a building rather than excluding it, because the
cost of warning someone unnecessarily is far lower than the cost of missing
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ic.geo import Point, bearing_deg, compass_point, is_downwind
from ic.schema import Assessment
from ic.tools.maps import Place
from ic.tools.weather import OPEN_METEO, Conditions

# Below this the wind will not decide anything, and saying it does would give a
# crew false confidence in a side.
DECISIVE_KMH = 8.0


@dataclass(frozen=True)
class ApproachPlan:
    """How to come at this incident, and what is downwind of it."""

    approach_from: str | None
    approach_bearing_deg: float | None
    wind: Conditions | None
    wind_decisive: bool
    downwind: tuple[str, ...] = ()
    water_supply: str | None = None
    responding: str | None = None
    station_bearing_from: str | None = None
    notes: tuple[str, ...] = ()
    caveat: str = ""

    def assessments(self) -> tuple[Assessment, ...]:
        """The plan as picture rows, each carrying why it says what it says."""
        out: list[Assessment] = []

        if self.approach_from and self.wind_decisive and self.wind is not None:
            out.append(Assessment.inferred(
                "approach",
                f"RECOMMENDATION: approach from {self.approach_from} — upwind",
                f"wind {self.wind.wind_kmh:.0f} km/h from {self.approach_from}; "
                "approaching downwind puts the crew inside the plume",
                0.7,
            ))
        elif self.wind is not None:
            out.append(Assessment.inferred(
                "approach",
                "wind too light to decide an approach side",
                f"wind {self.wind.wind_kmh:.0f} km/h; below the threshold at which "
                "an upwind approach is worth committing to",
                0.35,
            ))
        else:
            out.append(Assessment.unknown(
                "approach", "no weather available; no approach side is claimed"))

        if self.wind is not None:
            out.append(Assessment.verified(
                "conditions", self.wind.summary, "current observation", OPEN_METEO,
            ))

        if self.downwind:
            out.append(Assessment.inferred(
                "in the plume", "; ".join(self.downwind),
                f"within 30 degrees of the downwind axis from a wind out of "
                f"{self.approach_from}; wind shifts and this should be re-checked",
                0.6,
            ))

        if self.water_supply:
            out.append(Assessment.inferred(
                "water supply", self.water_supply,
                "nearest mapped hydrant; presence on a map is not a test of it",
                0.6,
            ))
        else:
            out.append(Assessment.unknown(
                "water supply", "no hydrant mapped within the searched radius"))

        if self.responding:
            out.append(Assessment.inferred(
                "responding",
                f"{self.responding} — arriving from the {self.station_bearing_from}",
                "nearest mapped station and the side it comes in on", 0.65,
            ))
        return tuple(out)


def plan_approach(
    incident: Point,
    wind: Conditions | None,
    stations: Sequence[Place],
    exposures: Sequence[Place],
    hydrants: Sequence[str],
) -> ApproachPlan:
    """Work out the approach, the plume and the water, from what is known."""
    notes: list[str] = []
    decisive = bool(wind and wind.wind_kmh >= DECISIVE_KMH)

    approach_from = wind.wind_from if wind else None
    approach_bearing = wind.wind_from_deg if wind else None

    downwind: list[str] = []
    if wind and decisive:
        for place in exposures:
            if is_downwind(incident, place.point, wind.wind_from_deg):
                side = compass_point(bearing_deg(incident, place.point))
                downwind.append(f"{place.name} — {place.distance_m:.0f} m {side}")

    water = hydrants[0] if hydrants else None
    if not water:
        notes.append("no hydrant mapped nearby — confirm water supply on arrival")

    responding = station_side = None
    if stations:
        nearest = min(stations, key=lambda s: s.distance_m)
        responding = f"{nearest.name} ({nearest.distance_m / 1000:.1f} km)"
        station_side = compass_point(bearing_deg(incident, nearest.point))

    if wind is None:
        caveat = ("No wind observation was available, so no approach side is "
                  "claimed — staging downwind on a guess is worse than staging "
                  "with no advice. Advisory only.")
    else:
        caveat = ("Wind shifts; re-check on arrival. Everything here is inferred "
                  "from mapped data and is advisory only.")

    return ApproachPlan(
        approach_from=approach_from,
        approach_bearing_deg=approach_bearing,
        wind=wind,
        wind_decisive=decisive,
        downwind=tuple(downwind),
        water_supply=water,
        responding=responding,
        station_bearing_from=station_side,
        notes=tuple(notes),
        caveat=caveat,
    )
