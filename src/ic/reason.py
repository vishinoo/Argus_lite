"""Reasoning over what the tools found.

This is the layer that makes the project something other than plumbing. Any
script can call a geocoder and post to Slack. The interesting question is what
you do when the building record says thirteen storeys and the caller said
three, when the hazard scan comes back empty, or when the address does not
exist at all.

Three commitments shape it.

**Unknowns are generated, not written.** Every tool that fails or returns
nothing produces an explicit open question in the brief. Nobody maintains a
list of caveats; the caveats fall out of what actually happened. That is why
"no relevant public information" reads as *insufficient evidence* rather than
as a section that quietly is not there — and the difference between those two
is the difference between a system you can trust and one you cannot.

**Conflicts are surfaced, never resolved.** When the caller's account and the
map record disagree, the brief carries both and says they disagree. The agent
is not positioned to know which is right, and picking one silently is how a
crew ends up prepared for the wrong building.

**An unverified location stops everything.** If the address did not resolve,
no claim is made about the place — not the building, not the hazards, not the
nearby stations — because every one of them would be about somewhere else. The
brief becomes a request for confirmation. This is the failure the demo should
show on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ic.brief import Brief, Claim, Priority
from ic.tools.base import ToolResult
from ic.approach import plan_approach
from ic.evidence import Ledger
from ic.schema import Assessment, Picture, required_for, unverifiable_for
from ic.tools.maps import Place


class Kind(Enum):
    FIRE = "fire"
    MEDICAL = "medical"
    GAS = "gas"
    MISSING_PERSON = "missing person"
    ARMED = "armed"
    UNKNOWN = "unknown"


_PATTERNS: tuple[tuple[Kind, re.Pattern], ...] = (
    # Plurals matter: `fume\b` never matched "Fumes", and `shoot\w*` never
    # matched "Shots". Both were found by the evaluation suite rather than by
    # reading the regex, which is the argument for having one.
    (Kind.GAS, re.compile(r"\b(gas|propane|lpg|fumes?|leak(ing|ed)?|odou?r of gas)\b", re.I)),
    (Kind.ARMED, re.compile(
        r"\b(armed|weapon|gun|knife|shots?|shot|shoot\w*|stab\w*|hostage|threaten\w*)\b",
        re.I)),
    (Kind.FIRE, re.compile(r"\b(fire|smoke|burning|flames?|alarm sounding)\b", re.I)),
    (Kind.MEDICAL, re.compile(r"\b(cardiac|heart attack|unresponsive|not breathing|"
                              r"bleeding|stroke|seizure|overdose|collaps\w*|injur\w*|patient)\b", re.I)),
    (Kind.MISSING_PERSON, re.compile(
        r"\b(missing|last seen|wandered|lost (child|person)|"
        r"has not returned|hasn'?t returned|separated from|did not come home)\b", re.I)),
)

# Structures a ground ladder will not reach.
_AERIAL_STOREYS = 4

# Mapped things that are *at risk from* an incident rather than a cause of it.
_EXPOSURE_KINDS = {"school", "hospital", "care home"}

_CARE_OCCUPANCY = {
    "social_facility", "nursing_home", "care_home", "hospital", "retirement_home",
}


@dataclass(frozen=True)
class Incident:
    """What the dispatcher typed, and everything said since.

    A call is not one sentence. The line stays open and information keeps
    arriving — the smoke changes colour, somebody gets out, the building turns
    out to be taller than the record says. Each update is another thing a
    person on a phone said, so each stays REPORTED; what changes is that the
    investigation and the contradiction checks now run over everything said,
    not just the opening line.
    """

    incident_id: str
    address: str
    description: str
    updates: tuple[str, ...] = ()

    @property
    def full_text(self) -> str:
        """Everything the caller has said, for classification and extraction.

        Joined as sentences rather than with a bare space. Extraction splits on
        punctuation, so a space let the end of one statement and the start of
        the next fuse into a single clause — the people row came out reading
        "smoke showing caller now says two people are inside".
        """
        parts = [p.strip() for p in (self.description, *self.updates) if p and p.strip()]
        return " ".join(
            p if p.endswith((".", "!", "?", ";")) else f"{p}."
            for p in parts
        ).strip()


@dataclass(frozen=True)
class Evidence:
    """Everything the tools returned, successful or not."""

    geocode: ToolResult
    building: ToolResult
    hazards: ToolResult
    nearby: ToolResult
    public: ToolResult
    weather: ToolResult | None = None
    hydrants: ToolResult | None = None
    exposures: ToolResult | None = None


def classify(description: str) -> Kind:
    """What kind of call this is. First match wins, most specific first."""
    for kind, pattern in _PATTERNS:
        if pattern.search(description or ""):
            return kind
    return Kind.UNKNOWN


# OpenStreetMap answers `office=yes` for a great many buildings, and the field
# mapper turned that into "occupancy: yes" — which reads as an established fact
# and carries no information. A tag whose value is "yes" says only that the key
# is present.
_EMPTY_TAG_VALUES = {"yes", "true"}


def _storeys(building: ToolResult) -> int | None:
    if not building.ok or not building.data:
        return None
    for f in building.data:
        if f.field == "storeys":
            try:
                return int(re.sub(r"[^0-9]", "", f.value) or 0) or None
            except ValueError:
                return None
    return None


def _claimed_storeys(description: str) -> int | None:
    m = re.search(r"\b(\d{1,2})[- ]?(?:storey|story|floor|flr)s?\b", description or "", re.I)
    return int(m.group(1)) if m else None


def _occupancy(building: ToolResult) -> str | None:
    if not building.ok or not building.data:
        return None
    for f in building.data:
        if f.field == "occupancy":
            return f.value
    return None


def synthesize(incident: Incident, evidence: Evidence) -> Brief:
    """Assemble the brief. Refuses to describe a place it could not locate."""
    kind = classify(incident.full_text)
    headline = kind.value.upper() if kind is not Kind.UNKNOWN else "UNCLASSIFIED INCIDENT"

    # ---------------------------------------------------------- the refusal
    if not evidence.geocode.ok:
        return Brief(
            incident_id=incident.incident_id,
            headline=headline,
            priority=Priority.UNVERIFIED,
            address=incident.address,
            location_verified=False,
            picture=build_picture(incident, evidence),
            known=(),
            unknowns=(
                f"the address {incident.address!r} could not be verified against any "
                "public geocoder",
                "no information about the location can be gathered until it is confirmed",
                "human confirmation of the address is required before acting",
            ),
        )

    known: list[Claim] = []
    hazards: list[Claim] = []
    resources: list[Claim] = []
    considerations: list[Claim] = []
    unknowns: list[str] = []
    conflicts: list[str] = []

    # The caller's account is carried, and stays theirs.
    known.append(Claim.caller_said(incident.description))
    for update in incident.updates:
        known.append(Claim.caller_said(update))

    geo = evidence.geocode.data["located"]
    known.append(
        Claim.recorded(
            f"Location resolved to {geo.display_name}",
            "geocoder match",
            source=evidence.geocode.sources[0] if evidence.geocode.sources else None,
        )
    )
    if evidence.geocode.data.get("ambiguous"):
        unknowns.append(
            "the address matched more than one distinct place — which one is meant "
            "is ambiguous and was not guessed"
        )

    # ------------------------------------------------------------ building
    if evidence.building.ok and evidence.building.data:
        src = evidence.building.sources[0] if evidence.building.sources else None
        for f in evidence.building.data:
            known.append(Claim.recorded(f"{f.field}: {f.value}", "building record", src))
    else:
        unknowns.append(
            "no public building record for this address — structure type, storeys "
            "and occupancy are unestablished"
        )

    storeys = _storeys(evidence.building)
    claimed = _claimed_storeys(incident.full_text)
    if storeys and claimed and storeys != claimed:
        conflicts.append(
            f"caller described {claimed} storeys; the building record says {storeys} — "
            "both are reported, neither is preferred"
        )

    # ------------------------------------------------------------- hazards
    if evidence.hazards.ok and evidence.hazards.data:
        src = evidence.hazards.sources[0] if evidence.hazards.sources else None
        for f in evidence.hazards.data:
            hazards.append(Claim.recorded(f.value, "mapped surroundings", src))
    elif evidence.hazards.ok:
        hazards.append(
            Claim.inferred(
                "No mapped hazards within the scanned radius",
                "the surroundings scan ran and returned nothing; absence in the map "
                "is not absence on the ground",
                0.5,
            )
        )
    else:
        unknowns.append("the hazard scan did not complete — surroundings are unknown")

    # ----------------------------------------------------------- resources
    if evidence.nearby.ok and evidence.nearby.data:
        src = evidence.nearby.sources[0] if evidence.nearby.sources else None
        best: dict[str, Place] = {}
        for p in evidence.nearby.data:
            best.setdefault(p.kind, p)
        for kind_name, p in best.items():
            resources.append(
                Claim.recorded(
                    f"Nearest {kind_name.replace('_', ' ')}: {p.name} — "
                    f"{p.distance_m/1000:.1f} km, est. {p.eta_text}",
                    "mapped resource; travel time from a model fitted on SFFD dispatches",
                    src,
                )
            )
    else:
        unknowns.append("no nearby stations or hospitals were found within the radius")

    # -------------------------------------------------------------- public
    if evidence.public.ok and evidence.public.data:
        for f in evidence.public.data:
            known.append(
                Claim.recorded(f"Public reference: {f.value}", "public search", f.source)
            )
    else:
        unknowns.append(
            "no public reference found for this address — there is insufficient "
            "evidence to say anything further about it"
        )

    # -------------------------------------------------- what follows from it
    if kind is Kind.FIRE and storeys and storeys >= _AERIAL_STOREYS:
        considerations.append(
            Claim.inferred(
                "Aerial access likely required — consider a ladder company",
                f"{storeys} storeys exceeds ground-ladder reach",
                0.75,
            )
        )
    occupancy = _occupancy(evidence.building)
    if occupancy in _CARE_OCCUPANCY:
        considerations.append(
            Claim.inferred(
                "Assisted evacuation likely — occupancy implies people who may not "
                "self-evacuate",
                f"building record gives occupancy as {occupancy!r}",
                0.7,
            )
        )
    if kind is Kind.GAS:
        considerations.append(
            Claim.inferred(
                "Consider utility isolation and an exclusion zone before entry",
                "reported gas incident",
                0.65,
            )
        )
        unknowns.append("the utility operator has not been confirmed from any source")
    if kind is Kind.MEDICAL:
        considerations.append(
            Claim.inferred(
                "Route to the nearest emergency department on scene assessment",
                "medical incident with a mapped hospital nearby",
                0.7,
            )
        )
    if kind is Kind.ARMED:
        unknowns.append(
            "the threat is the caller's unconfirmed account — no source independently "
            "verifies a weapon, and this brief does not treat it as established"
        )
        considerations.append(
            Claim.inferred(
                "Treat as unconfirmed threat information — law enforcement decision",
                "reported by the caller and not independently verified",
                0.5,
            )
        )
    if kind is Kind.MISSING_PERSON:
        unknowns.append(
            "no source can confirm the person's location or description; the account "
            "is the caller's alone"
        )

    priority = {
        Kind.FIRE: Priority.HIGH, Kind.GAS: Priority.HIGH, Kind.ARMED: Priority.HIGH,
        Kind.MEDICAL: Priority.HIGH, Kind.MISSING_PERSON: Priority.MEDIUM,
        Kind.UNKNOWN: Priority.MEDIUM,
    }[kind]

    return Brief(
        incident_id=incident.incident_id,
        headline=headline,
        priority=priority,
        address=incident.address,
        location_verified=True,
        known=tuple(known),
        hazards=tuple(hazards),
        resources=tuple(resources),
        unknowns=tuple(unknowns),
        considerations=tuple(considerations),
        conflicts=tuple(conflicts),
        picture=build_picture(incident, evidence),
    )


# --------------------------------------------------------------------------
# The structured picture
#
# The brief above is prose a human reads. This is the same incident as the
# five questions a dispatcher actually asks, with each field carrying its own
# state and warrant. It is what drives the investigation — the fields still
# UNKNOWN are precisely what the agent goes and looks for — and what the
# evaluation measures, because "did it determine occupancy" is checkable and
# "was the summary good" is not.
# --------------------------------------------------------------------------

_PEOPLE_WORDS = re.compile(
    r"\b(someone|somebody|people|occupants?|person|child|man|woman|resident|"
    r"patient|trapped|inside|staff)\b", re.I,
)


def _people_clause(description: str) -> str | None:
    """The part of what the caller said that is about a person.

    The whole description already appears as the `report` field. Repeating it
    here says nothing and, truncated to a column, says less than nothing — so
    only the clause mentioning someone is carried.
    """
    if not description:
        return None
    clauses = re.split(r"(?<=[.;])\s+|\s+\band\b\s+|,\s+", description)
    hits = [c.strip(" .,;") for c in clauses if _PEOPLE_WORDS.search(c)]
    if not hits:
        return None
    # The most specific clause, which is almost always the longest one that
    # mentions a person rather than the sentence that merely contains it.
    return max(hits, key=len)


def build_picture(incident: Incident, evidence: Evidence,
                  ledger: Ledger | None = None) -> Picture:
    """Assemble the operational picture, field by field, state by state.

    Every verified field is minted into the ledger first and then cites the row
    it came from, so the chain runs source → raw evidence → fact → claim and
    can be walked backwards by anyone who doubts it.
    """
    kind = classify(incident.full_text)
    ledger = ledger if ledger is not None else Ledger()
    situation: list[Assessment] = []
    people: list[Assessment] = []
    threats: list[Assessment] = []
    resources: list[Assessment] = []
    exposures: list[Assessment] = []
    conflicts: list[str] = []

    situation.append(
        Assessment.reported("report", incident.description, confidence=0.4)
    )
    for n, update in enumerate(incident.updates, start=1):
        situation.append(
            Assessment.reported(f"update {n}", update, confidence=0.4)
        )

    # ------------------------------------------------------------- location
    if evidence.geocode.ok:
        geo = evidence.geocode.data["located"]
        src = evidence.geocode.sources[0] if evidence.geocode.sources else None
        ev = ledger.record("maps.geocode", src, "location", geo.display_name)
        situation.append(
            Assessment.verified("location", geo.display_name, "geocoder match",
                                src, evidence_ids=(ev.id,))
        )
    else:
        situation.append(
            Assessment.unknown(
                "location",
                f"{incident.address!r} could not be verified against any public geocoder",
            )
        )
        # Nothing else can be asserted about a place that has not been found.
        return Picture(situation=tuple(situation), people=(), threats=(), resources=())

    # ------------------------------------------------------------- building
    src = evidence.building.sources[0] if evidence.building.sources else None
    storeys = _storeys(evidence.building)
    if evidence.building.ok and evidence.building.data:
        described = "; ".join(
            f"{f.field}: {f.value}" for f in evidence.building.data
            if f.value.lower() not in _EMPTY_TAG_VALUES
        )
        if described:
            rows = tuple(
                ledger.record("osm.survey", src, f.field, f.value)
                for f in evidence.building.data
                if f.value.lower() not in _EMPTY_TAG_VALUES
            )
            situation.append(
                Assessment.verified("building", described, "public building record",
                                    src, evidence_ids=tuple(r.id for r in rows))
            )
        else:
            situation.append(
                Assessment.unknown(
                    "building",
                    "a building is mapped here but the record carries no usable detail",
                )
            )
    else:
        situation.append(
            Assessment.unknown("building", "no public building record for this address")
        )

    claimed = _claimed_storeys(incident.full_text)
    if storeys and claimed and storeys != claimed:
        situation.append(
            Assessment.contradicted(
                "storeys",
                f"caller: {claimed} storeys",
                f"building record: {storeys} storeys",
                "the caller's account and the map record disagree; neither is "
                "preferred and both should be expected on arrival",
            )
        )

    # --------------------------------------------------------------- people
    #
    # Two questions, not one. What the building is *used for* is a property
    # record; who is inside it *right now* is the caller. An earlier version
    # had these competing for a single field, so a map tag silently suppressed
    # "someone may still be inside" — the most urgent sentence in a fire call.
    occupancy = _occupancy(evidence.building)
    occupancy_ev: tuple[str, ...] = ()
    if occupancy:
        row = ledger.record("osm.survey", src, "occupancy", occupancy)
        occupancy_ev = (row.id,)
        people.append(
            Assessment.verified("occupancy", occupancy, "building record",
                                src, evidence_ids=occupancy_ev)
        )

    reported_people = _people_clause(incident.full_text)
    if reported_people:
        people.append(Assessment.reported("persons_reported", reported_people))

    if occupancy in _CARE_OCCUPANCY:
        # Deliberately weaker than it was. An OpenStreetMap `amenity` tag says
        # what a building is *for*; it does not establish that the people in it
        # have mobility limitations, and asserting that they do — from a map
        # tag — is the kind of over-reach a careful reviewer picks up
        # immediately. It raises a question for the crew; it concludes nothing.
        people.append(
            Assessment.inferred(
                "vulnerability",
                "CONSIDER: occupancy type may warrant evacuation assistance — "
                "not established",
                f"building record gives occupancy as {occupancy!r}; this does not "
                "establish the mobility or needs of anyone present",
                0.45, evidence_ids=occupancy_ev,
            )
        )

    # ------------------------------------------------- threats vs exposures
    #
    # A filling station next door is a hazard: it can make the incident worse.
    # A school next door is an exposure: the incident can make *it* worse.
    # Reporting a primary school under HAZARDS was a category error, and the
    # kind a reviewer notices immediately.
    hsrc = evidence.hazards.sources[0] if evidence.hazards.sources else None
    if evidence.hazards.ok and evidence.hazards.data:
        real_hazards = list(evidence.hazards.data)
        if real_hazards:
            rows = tuple(
                ledger.record("osm.survey", hsrc, "external hazard", f.value)
                for f in real_hazards
            )
            threats.append(
                Assessment.verified(
                    "external hazards",
                    "; ".join(f.value for f in real_hazards),
                    "mapped surroundings", hsrc,
                    evidence_ids=tuple(r.id for r in rows),
                )
            )
        else:
            # "No hazards" is a claim this system cannot make. It searched a
            # map of the surroundings; it knows nothing about what is inside a
            # burning building, and the wording has to carry that.
            threats.append(
                Assessment.inferred(
                    "external hazards",
                    "no mapped fuel, tanks or substations within the scanned "
                    "radius — this does not establish the site is free of hazards",
                    "a map search of the surroundings; nothing was searched or "
                    "established about conditions inside the structure",
                    0.4,
                )
            )

    elif evidence.hazards.ok:
        # Same wording as the branch above. There are two paths to this row and
        # only one of them got corrected the first time, so the empty-scan case
        # went on claiming "none mapped" — which reads as "no hazards" — while
        # the other path had already been fixed to say what it actually means.
        threats.append(
            Assessment.inferred(
                "external hazards",
                "no mapped fuel, tanks or substations within the scanned "
                "radius — this does not establish the site is free of hazards",
                "a map search of the surroundings; nothing was searched or "
                "established about conditions inside the structure", 0.4,
            )
        )
    else:
        threats.append(
            Assessment.unknown(
                "external hazards", "the surroundings scan did not complete")
        )

    if kind is Kind.ARMED:
        threats.append(
            Assessment.reported("threat", incident.full_text, confidence=0.35)
        )
    if kind is Kind.GAS:
        threats.append(
            Assessment.unknown(
                "utility", "no consulted source names the utility operator for this address"
            )
        )

    # ------------------------------------------------------------ resources
    if evidence.nearby.ok and evidence.nearby.data:
        nsrc = evidence.nearby.sources[0] if evidence.nearby.sources else None
        best: dict[str, Place] = {}
        for place in evidence.nearby.data:
            best.setdefault(place.kind, place)
        for field, place in best.items():
            described = (f"{place.name} — {place.distance_m/1000:.1f} km, "
                         f"est. {place.eta_text}")
            row = ledger.record("osm.survey", nsrc, field, described)
            resources.append(
                Assessment.verified(
                    field, described,
                    "mapped resource; travel time from a model fitted on SFFD dispatches",
                    nsrc, evidence_ids=(row.id,),
                )
            )
    for field in ("fire_station", "hospital"):
        if field in required_for(kind) and field not in {a.field for a in resources}:
            resources.append(
                Assessment.unknown(field, "none found within the searched radius")
            )

    # --------------------------------------------------------------- access
    #
    # Gated on the discipline, not on the building. A ladder company is a fire
    # resource, and recommending one because a shooting happened in a tall
    # building is an error anyone operational spots instantly. Medical access
    # is a stretcher route, and `ic.ems` writes that one.
    if kind in (Kind.FIRE, Kind.GAS) and storeys is not None:
        if storeys >= _AERIAL_STOREYS:
            situation.append(
                Assessment.inferred(
                    "access",
                    "RECOMMENDATION: consider a ladder company for aerial access",
                    f"{storeys} storeys exceeds ground-ladder reach", 0.75,
                    evidence_ids=tuple(
                        r.id for r in ledger.records if r.fact == "storeys"),
                )
            )
        else:
            situation.append(
                Assessment.inferred(
                    "access", "within ground-ladder reach",
                    f"{storeys} storeys", 0.7,
                )
            )
    elif "access" in required_for(kind):
        situation.append(
            Assessment.unknown("access", "building height unestablished")
        )

    # What nobody can settle from a desk. Always emitted, so the brief can
    # never read as complete while the questions that decide the incident are
    # still open.
    open_questions = tuple(
        Assessment.unknown(field, "no public source can establish this before "
                                  "a crew is on scene")
        for field in unverifiable_for(kind)
    )

    # Exposures: located, so the plume test below can ask which side they are on.
    if evidence.exposures is not None and evidence.exposures.ok:
        esrc = evidence.exposures.sources[0] if evidence.exposures.sources else None
        for place in (evidence.exposures.data or []):
            described = f"{place.name} — {place.distance_m:.0f} m"
            row = ledger.record("osm.survey", esrc, place.kind, described)
            exposures.append(
                Assessment.verified(
                    place.kind, described,
                    "mapped nearby — at risk if the incident spreads", esrc,
                    evidence_ids=(row.id,),
                )
            )

    # ------------------------------------------------------------- approach
    #
    # The second agent. Everything above establishes what is here; this works
    # out what to do about where it is, which is mostly a question of wind.
    approach_rows: tuple[Assessment, ...] = ()
    wind = (evidence.weather.data
            if evidence.weather is not None and evidence.weather.ok else None)
    if wind is not None:
        ledger.record("weather.current", evidence.weather.sources[0],
                      "wind", wind.summary)

    exposure_places = list(evidence.exposures.data or []) \
        if evidence.exposures is not None and evidence.exposures.ok else []
    station_places = [p for p in (evidence.nearby.data or [])
                      if evidence.nearby.ok and p.kind == "fire_station"]
    hydrant_values = [f.value for f in (evidence.hydrants.data or [])] \
        if evidence.hydrants is not None and evidence.hydrants.ok else []

    plan = plan_approach(geo.point, wind, station_places, exposure_places,
                         hydrant_values)
    # Upwind approach, water supply and which engine arrives from which side
    # are fire answers. An armed incident inherited all of them, so a report of
    # shots fired came back recommending a hydrant.
    approach_rows = plan.assessments()
    if kind not in (Kind.FIRE, Kind.GAS):
        approach_rows = tuple(
            a for a in approach_rows
            if a.field not in {"approach", "water supply", "responding", "plume"}
        )

    # A medical call inherited a building record and a nearest hospital and
    # stopped there, which is a fire brief with the fire removed. These are the
    # two things an EMS crew plans around that the evidence already supports.
    from ic.ems import recommendations as ems_recommendations
    from ic.police import recommendations as police_recommendations

    hospital_row = next((a for a in resources if a.field == "hospital"
                         and a.value), None)
    approach_rows = approach_rows + ems_recommendations(
        kind, incident.full_text, storeys,
        hospital_row.value if hospital_row else None,
    ) + police_recommendations(
        kind, [(p.name, p.kind, p.distance_m) for p in exposure_places],
    )

    # An aerial of the address. No request is made here — this is the URL the
    # browser will load, so the picture stays small and the image never enters
    # the payload.
    from ic.imagery import aerial_view

    return Picture(
        situation=tuple(situation), people=tuple(people),
        threats=tuple(threats), resources=tuple(resources),
        exposures=tuple(exposures), approach=approach_rows,
        open_questions=open_questions,
        conflicts=tuple(conflicts), ledger=ledger,
        imagery=aerial_view(geo.point).to_dict(),
    )
