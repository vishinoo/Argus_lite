"""The incident brief, and the rules that keep it honest.

The brief is the product. Everything the agent does before it is gathering;
this is where gathering becomes something a human can act on. Which means the
brief's job is not to look complete — it is to be accurate about its own
limits, because a crew that over-trusts it once will never trust it again.

Three rules do the work.

**A claim that cannot name its source cannot be made.** `Claim.recorded`
raises without a `Source`. Not a lint, not a convention — a `ValueError`. This
is the single mechanism behind "100% of external claims were attributable",
and it is enforced at construction so the metric measures a property of the
system rather than the diligence of whoever wrote the prompt.

**What the caller said stays what the caller said.** It never becomes a
recorded fact on its way through the pipeline, however many inferences rest on
it. A frightened person's account is often true and never verified.

**Confidence is computed, not asserted.** It falls out of how much
corroboration there is, whether the location actually verified, and how long
the list of unknowns is. A model that writes "Confidence: 87%" at the bottom of
its own output is marking its own homework; this number can be recomputed from
the brief's contents by anyone who doubts it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ic.provenance import Basis, _CEILING

__all__ = [
    "Basis", "Claim", "Brief", "Priority",
]
from ic.tools.base import Source


class Priority(Enum):
    HIGH = "HIGH PRIORITY"
    MEDIUM = "PRIORITY"
    LOW = "ROUTINE"
    UNVERIFIED = "UNVERIFIED — HUMAN CONFIRMATION REQUIRED"


@dataclass(frozen=True)
class Claim:
    """One statement in the brief, with what stands behind it."""

    text: str
    basis: Basis
    evidence: str
    confidence: float
    source: Source | None = None

    # ------------------------------------------------------------ builders

    @classmethod
    def recorded(cls, text: str, evidence: str, source: Source | None) -> "Claim":
        """A fact from an external record. Refuses to exist without a citation."""
        if source is None:
            raise ValueError(
                f"recorded claim {text!r} has no source; an external claim that "
                "cannot be attributed must not be made"
            )
        return cls(text, Basis.RECORDED, evidence, _CEILING, source)

    @classmethod
    def caller_said(cls, text: str, confidence: float = 0.7) -> "Claim":
        """The caller's account. The caller is the source; it stays theirs."""
        return cls(text, Basis.CALLER_SAID, "reported by the caller", confidence, None)

    @classmethod
    def inferred(cls, text: str, evidence: str, confidence: float) -> "Claim":
        return cls(text, Basis.DERIVED, evidence, min(confidence, _CEILING), None)

    @property
    def label(self) -> str:
        return {
            Basis.RECORDED: "recorded",
            Basis.CALLER_SAID: "caller said",
            Basis.DERIVED: "inferred",
        }.get(self.basis, self.basis.value)

    @property
    def is_external(self) -> bool:
        """Came from outside the call, so it owes a citation."""
        return self.basis is Basis.RECORDED

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "basis": self.basis.value,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "source": str(self.source) if self.source else None,
        }


@dataclass(frozen=True)
class Brief:
    """What the agent knows, what it does not, and what follows from both."""

    incident_id: str
    headline: str
    priority: Priority
    address: str
    location_verified: bool
    known: tuple[Claim, ...] = ()
    hazards: tuple[Claim, ...] = ()
    resources: tuple[Claim, ...] = ()
    unknowns: tuple[str, ...] = ()
    considerations: tuple[Claim, ...] = ()
    conflicts: tuple[str, ...] = ()
    picture: "object | None" = None
    """The same incident as the five-section schema. See `ic.schema`."""

    # ---------------------------------------------------------- measures

    @property
    def claims(self) -> tuple[Claim, ...]:
        return self.known + self.hazards + self.resources + self.considerations

    @property
    def attribution_rate(self) -> float:
        """Share of external claims that name a source. Should always be 1.0."""
        external = [c for c in self.claims if c.is_external]
        if not external:
            return 1.0
        return sum(1 for c in external if c.source is not None) / len(external)

    @property
    def unsupported(self) -> tuple[Claim, ...]:
        """External claims with no citation. Should always be empty."""
        return tuple(c for c in self.claims if c.is_external and c.source is None)

    @property
    def confidence(self) -> float:
        """Derived from the evidence, so anyone can recompute and check it.

        An unverified location dominates everything: if we do not know where
        this is, the rest of the brief is about somewhere else.
        """
        if not self.location_verified:
            return 0.25

        corroborated = sum(1 for c in self.claims if c.is_external)
        # Diminishing returns — the fifth map tag adds less than the first.
        breadth = min(0.45, 0.09 * corroborated)
        doubt = min(0.30, 0.05 * len(self.unknowns))
        conflict = 0.10 if self.conflicts else 0.0
        return round(max(0.2, min(_CEILING, 0.45 + breadth - doubt - conflict)), 2)

    # ------------------------------------------------------------ render

    def render(self) -> str:
        lines: list[str] = []
        add = lines.append
        add(f"INCIDENT INTELLIGENCE — {self.incident_id}")
        add(f"{self.priority.value} — {self.headline}")
        add(f"{self.address}")
        add("")

        def section(title: str, claims: tuple[Claim, ...]) -> None:
            if not claims:
                return
            add(title)
            for c in claims:
                cite = f"  [{c.label}]"
                if c.source:
                    cite += f" {c.source.label}"
                add(f"  · {c.text}")
                add(f"   {cite}")
            add("")

        section("KNOWN", self.known)
        section("HAZARDS", self.hazards)
        section("RESOURCES", self.resources)

        if self.unknowns:
            add("NOT ESTABLISHED")
            for u in self.unknowns:
                add(f"  · {u}")
            add("")

        if self.conflicts:
            add("CONFLICTING SOURCES")
            for c in self.conflicts:
                add(f"  ! {c}")
            add("")

        section("CONSIDERATIONS (advisory)", self.considerations)

        sourced = sum(1 for c in self.claims if c.is_external)
        open_q = len(self.unknowns)
        add(f"Confidence {self.confidence:.0%} — computed from "
            f"{sourced} sourced finding{'' if sourced == 1 else 's'} and "
            f"{open_q} open question{'' if open_q == 1 else 's'}")
        add("Advisory only. Argus does not dispatch; a human decides.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "headline": self.headline,
            "priority": self.priority.value,
            "address": self.address,
            "location_verified": self.location_verified,
            "known": [c.to_dict() for c in self.known],
            "hazards": [c.to_dict() for c in self.hazards],
            "resources": [c.to_dict() for c in self.resources],
            "considerations": [c.to_dict() for c in self.considerations],
            "unknowns": list(self.unknowns),
            "conflicts": list(self.conflicts),
            "confidence": self.confidence,
            "attribution_rate": self.attribution_rate,
            "unsupported_claims": len(self.unsupported),
            "picture": self.picture.to_dict() if self.picture is not None else None,
        }
