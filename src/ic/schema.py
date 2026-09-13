"""What Argus is required to determine about an incident, and how sure it is.

This is the opinionated part. Most of an agent's behaviour follows from what it
is *obliged* to find out, and a system with no such obligation degenerates into
summarising whatever the first search returned.

So an incident is not free text. It is five questions a dispatcher already asks
— what happened, who is at risk, what threatens them, what can respond, and
what do we actually know — and Argus is judged on how much of that it filled in
and how honestly.

Four states, and the difference between them is the product
-----------------------------------------------------------
    VERIFIED   an external record says so, and names itself
    REPORTED   a person on the phone says so
    INFERRED   Argus worked it out from something else
    UNKNOWN    nobody has established this

"There are 12 people inside" and "the caller thinks people might be inside" are
different sentences, and a system that renders them in the same typeface will
eventually get someone hurt. VERIFIED cannot be constructed without a source —
it raises — which is what makes attribution a property of the type rather than
a habit.

The schema is also the work plan
--------------------------------
Each incident kind declares the fields that must be determined. Whatever is
still missing is, precisely, what the agent should go and look for next. That
is the whole mechanism behind autonomous investigation here: no script of tool
calls, just a list of things not yet known and tools that know how to answer
them. Add a field to the schema and the agent starts investigating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ic.tools.base import Source


class Status(Enum):
    VERIFIED = "VERIFIED"
    """An external record says so, and names itself."""
    REPORTED = "REPORTED"
    """A person on the phone says so. Often true, never verified."""
    INFERRED = "INFERRED"
    """Argus worked it out from something else. A recommendation, not a fact."""
    CONTRADICTED = "CONTRADICTED"
    """Two sources disagree. Both are carried; neither is preferred."""
    UNKNOWN = "UNKNOWN"
    """Nobody has established this — including, deliberately, the things no
    source can establish before a crew arrives."""


class Band(Enum):
    """Confidence as a word, because a dispatcher reads words under pressure."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NONE = "None"


@dataclass(frozen=True)
class Assessment:
    """One field of the picture, with its state and its warrant."""

    field: str
    value: str | None
    status: Status
    evidence: str
    confidence: float = 0.0
    source: Source | None = None
    evidence_ids: tuple[str, ...] = ()
    """Rows in the evidence ledger this rests on — EV-003, and so on.

    A source *string* is a label; anything can write "OpenStreetMap". An id
    points at a row recording which tool ran and what it returned verbatim,
    which is what lets a sceptic check the claim instead of trusting it."""

    # ------------------------------------------------------------ builders

    @classmethod
    def verified(cls, field: str, value: str, evidence: str,
                 source: Source | None,
                 evidence_ids: tuple[str, ...] = ()) -> "Assessment":
        if source is None:
            raise ValueError(
                f"{field!r} cannot be VERIFIED without a source; a claim that "
                "asserts the world must be able to say who says so"
            )
        return cls(field, value, Status.VERIFIED, evidence, 0.95, source, evidence_ids)

    @classmethod
    def reported(cls, field: str, value: str, confidence: float = 0.4) -> "Assessment":
        return cls(field, value, Status.REPORTED,
                   "reported by the caller; not independently verified", confidence)

    @classmethod
    def inferred(cls, field: str, value: str, evidence: str,
                 confidence: float = 0.6,
                 evidence_ids: tuple[str, ...] = ()) -> "Assessment":
        return cls(field, value, Status.INFERRED, evidence, min(confidence, 0.9),
                   None, evidence_ids)

    @classmethod
    def contradicted(cls, field: str, first: str, second: str,
                     evidence: str) -> "Assessment":
        """Two sources disagree. Argus is not positioned to pick a winner.

        Resolving this silently is how a crew arrives prepared for the wrong
        building, so both accounts are carried and the disagreement is the
        finding.
        """
        return cls(field, f"{first} / {second}", Status.CONTRADICTED, evidence, 0.3)

    @classmethod
    def unknown(cls, field: str, evidence: str) -> "Assessment":
        return cls(field, None, Status.UNKNOWN, evidence, 0.0)

    # -------------------------------------------------------------- reading

    @property
    def band(self) -> Band:
        if self.status is Status.UNKNOWN:
            return Band.NONE
        if self.status is Status.VERIFIED:
            return Band.HIGH
        if self.status in (Status.REPORTED, Status.CONTRADICTED):
            return Band.LOW
        return Band.MEDIUM if self.confidence >= 0.65 else Band.LOW

    @property
    def determined(self) -> bool:
        return self.status is not Status.UNKNOWN

    def to_dict(self) -> dict:
        return {
            "field": self.field, "value": self.value, "status": self.status.value,
            "confidence": round(self.confidence, 2), "band": self.band.value,
            "evidence": self.evidence,
            "evidence_ids": list(self.evidence_ids),
            "source": str(self.source) if self.source else None,
        }


# What each kind of incident obliges Argus to determine. Missing entries are
# the agent's to-do list, so this table is the investigation plan.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "fire": ("location", "building", "access", "external hazards",
             "fire_station", "hospital"),
    "medical": ("location", "hospital"),
    "gas": ("location", "building", "external hazards", "fire_station"),
    "armed": ("location", "threat", "hospital"),
    "missing person": ("location", "building"),
    "unknown": ("location", "building", "external hazards"),
}
#
# `occupancy` used to be required on four of those. What a building is *used
# for* is worth showing when a record carries it, and it still drives the
# evacuation-assistance consideration — but most addresses carry no such tag,
# so obliging it scored ordinary incidents incomplete over a fact that changed
# nothing about the response, and printed an UNKNOWN row saying so.


# Questions no public source can answer before a crew is on scene. They are
# emitted as UNKNOWN on every incident of that kind, always.
#
# This exists because the first version of this system reported "0 unknown" on
# a structure fire. Nobody knew whether a fire was actually burning, whether
# anyone was inside, or how bad it was — and the brief read as complete. A
# completeness score that reaches 100% with those open is measuring how much
# OpenStreetMap knows about a building, not how much Argus knows about an
# emergency. Naming them is the honest correction, and it is also the more
# useful output: these are exactly the questions the first-arriving officer
# has to answer.
#
# An entry has to earn its line, though. `fire_confirmed` and `leak_confirmed`
# were dropped because they restate the call: somebody has rung to report a
# fire, crews roll on the report, and asking whether there is one pushed the
# questions that decide the incident further down a list read under pressure.
# `weapon_confirmed` stays, deliberately breaking the symmetry — "shots heard"
# and "an armed person is present" are different scenes with different
# approaches, so that one changes what police do on arrival.
_UNVERIFIABLE: dict[str, tuple[str, ...]] = {
    "fire": ("persons_trapped", "severity", "hazmat", "current_access"),
    "medical": ("patient_condition", "persons_involved", "scene_safety"),
    "gas": ("utility", "concentration", "ignition_sources", "persons_present"),
    "armed": ("weapon_confirmed", "suspect_location", "persons_at_risk",
              "scene_safety"),
    "missing person": ("person_description", "last_known_position", "time_missing"),
    "unknown": ("nature_of_incident", "persons_at_risk", "scene_safety"),
}


def required_for(kind) -> tuple[str, ...]:
    """The fields this kind of incident obliges Argus to determine."""
    key = getattr(kind, "value", str(kind))
    return _REQUIRED.get(key, _REQUIRED["unknown"])


def unverifiable_for(kind) -> tuple[str, ...]:
    """Questions Argus must admit it cannot answer before arrival."""
    key = getattr(kind, "value", str(kind))
    return _UNVERIFIABLE.get(key, _UNVERIFIABLE["unknown"])


@dataclass(frozen=True)
class Picture:
    """The operational picture, in the five sections a dispatcher thinks in."""

    situation: tuple[Assessment, ...] = ()
    people: tuple[Assessment, ...] = ()
    threats: tuple[Assessment, ...] = ()
    resources: tuple[Assessment, ...] = ()
    exposures: tuple[Assessment, ...] = ()
    """Nearby places that matter if this spreads — a school, a care home. Not
    hazards: a school does not make a fire worse, it makes the consequences
    worse, and calling it a hazard was a category error."""
    approach: tuple[Assessment, ...] = ()
    """How to come at it: upwind side, what is in the plume, water, who responds."""
    open_questions: tuple[Assessment, ...] = ()
    """What no source can settle before a crew arrives."""
    conflicts: tuple[str, ...] = ()
    ledger: "object | None" = None
    """The evidence rows every verified field points at. See `ic.evidence`."""
    imagery: dict | None = None
    """An aerial photograph of the location. See `ic.imagery`."""

    @property
    def all(self) -> tuple[Assessment, ...]:
        return (self.situation + self.people + self.threats + self.resources
                + self.exposures + self.approach + self.open_questions)

    def by_status(self, status: Status) -> tuple[Assessment, ...]:
        return tuple(a for a in self.all if a.status is status)

    @property
    def determined_fields(self) -> set[str]:
        return {a.field for a in self.all if a.determined}

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(a.field for a in self.all if a.status is Status.UNKNOWN)

    @property
    def attribution_rate(self) -> float:
        """Share of VERIFIED items naming a source. Structurally always 1.0."""
        verified = self.by_status(Status.VERIFIED)
        if not verified:
            return 1.0
        return sum(1 for a in verified if a.source is not None) / len(verified)

    @property
    def unsupported(self) -> tuple[Assessment, ...]:
        return tuple(a for a in self.by_status(Status.VERIFIED) if a.source is None)

    @property
    def traceability(self) -> float:
        """Share of verified items that point at a numbered evidence row.

        Distinct from `attribution_rate`, deliberately. Attribution asks
        whether a claim names a source; traceability asks whether that naming
        is backed by a record somebody else could go and read.
        """
        verified = self.by_status(Status.VERIFIED)
        if not verified:
            return 1.0
        return sum(1 for a in verified if a.evidence_ids) / len(verified)

    def gaps(self, kind) -> tuple[str, ...]:
        """Required fields not yet determined — what to investigate next."""
        done = self.determined_fields
        return tuple(f for f in required_for(kind) if f not in done)

    def completeness(self, kind) -> float:
        required = required_for(kind)
        if not required:
            return 1.0
        return len([f for f in required if f in self.determined_fields]) / len(required)

    @property
    def contradicted(self) -> tuple[Assessment, ...]:
        return self.by_status(Status.CONTRADICTED)

    def to_dict(self) -> dict:
        return {
            "situation": [a.to_dict() for a in self.situation],
            "people": [a.to_dict() for a in self.people],
            "threats": [a.to_dict() for a in self.threats],
            "exposures": [a.to_dict() for a in self.exposures],
            "resources": [a.to_dict() for a in self.resources],
            "approach": [a.to_dict() for a in self.approach],
            "open_questions": [a.to_dict() for a in self.open_questions],
            "conflicts": list(self.conflicts),
            "unknown_fields": list(self.unknown_fields),
            "imagery": self.imagery,
            "traceability": round(self.traceability, 3),
            "ledger": self.ledger.to_list() if self.ledger is not None else [],
        }
