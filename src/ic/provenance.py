"""Where a value came from, travelling with the value.

An emergency system mixes five kinds of claim and they are not interchangeable:
what a record states, what a frightened caller said, what software inferred from
that, what the historical record does on average, and what a model predicts.
Collapsing them into bare fields is how an inference quietly becomes a fact
somewhere downstream, and how a dispatcher ends up trusting a guess because it
was rendered in the same typeface as an address.

So every uncertain value is wrapped with its basis, its evidence, and a
confidence that only a recorded fact is allowed to max out. The interface reads
`label` to show the distinction; reviewers read `evidence` to audit it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Basis(Enum):
    RECORDED = "recorded"
    """Stated by a system of record. The only basis treated as certain."""
    CALLER_SAID = "caller_said"
    """Reported by a person on the phone. Often true, never verified."""
    DERIVED = "derived"
    """Inferred by software from something else."""
    HISTORICAL = "historical"
    """What comparable cases did. A rate, not a fact about this case."""
    PREDICTED = "predicted"
    """A model's estimate of something that has not happened yet."""
    UNKNOWN = "unknown"
    """Not established. Explicitly absent rather than silently missing."""


_LABELS = {
    Basis.RECORDED: "Recorded",
    Basis.CALLER_SAID: "Caller said",
    Basis.DERIVED: "Inferred",
    Basis.HISTORICAL: "From the record",
    Basis.PREDICTED: "Predicted",
    Basis.UNKNOWN: "Not established",
}

# Nothing short of a system of record may claim certainty.
_CEILING = 0.95


@dataclass(frozen=True)
class Known(Generic[T]):
    value: T | None
    basis: Basis
    evidence: str
    confidence: float

    @property
    def label(self) -> str:
        return _LABELS[self.basis]

    @property
    def is_verified(self) -> bool:
        """True only for a system of record. A caller's word is not verification."""
        return self.basis is Basis.RECORDED

    @classmethod
    def unknown(cls, field: str, why: str) -> "Known[Any]":
        return cls(value=None, basis=Basis.UNKNOWN,
                   evidence=f"{field} not established: {why}", confidence=0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "basis": self.basis.value,
            "label": self.label,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "verified": self.is_verified,
        }


def _clamp(c: float) -> float:
    return max(0.0, min(_CEILING, c))


def recorded(value: T, source: str) -> Known[T]:
    return Known(value, Basis.RECORDED, f"recorded by {source}", 1.0)


def caller_said(value: T, quote: str, confidence: float = 0.7) -> Known[T]:
    return Known(value, Basis.CALLER_SAID, f"caller: {quote}", _clamp(confidence))


def derived(value: T, why: str, confidence: float) -> Known[T]:
    return Known(value, Basis.DERIVED, why, _clamp(confidence))


def historical(value: T, rate: str, confidence: float = 0.6) -> Known[T]:
    return Known(value, Basis.HISTORICAL, rate, _clamp(confidence))


def predicted(value: T, model: str, confidence: float = 0.6) -> Known[T]:
    return Known(value, Basis.PREDICTED, f"predicted by {model}", _clamp(confidence))
