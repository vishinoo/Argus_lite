"""Every fact, numbered, with what produced it.

The chain this makes possible is the point of the project:

    SOURCE → RAW EVIDENCE → NORMALISED FACT → CLAIM → SYNTHESIS

A claim that merely *names* a source proves nothing; any string can say
"OpenStreetMap". A claim carrying `EV-003`, where EV-003 is a row recording
which tool ran, which source it hit and what it returned verbatim, can be
checked by someone who does not trust the claim — which is the only kind of
attribution worth measuring.

Numbering is per incident. `EV-001` means the first thing established about
*this* call, not the first since the process started, so two runs are directly
comparable and an evidence id means the same thing to everyone reading one
brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ic.tools.base import Source


@dataclass(frozen=True)
class EvidenceRecord:
    """One retrieved fact, as it arrived."""

    id: str
    tool: str
    source: Source
    fact: str
    """What it means, normalised — "storeys"."""
    raw: str
    """What the source actually said — "13"."""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "tool": self.tool, "source": str(self.source),
            "fact": self.fact, "raw": self.raw,
        }


@dataclass
class Ledger:
    """The evidence gathered for one incident, in arrival order."""

    records: list[EvidenceRecord] = field(default_factory=list)

    def record(self, tool: str, source: Source, fact: str, raw: str) -> EvidenceRecord:
        """Add a row, or return the identical one already held.

        The same reading is often needed twice — occupancy describes the
        building and also the people — and minting two rows for it would make
        the ledger look like two independent corroborations of something
        observed once. Two *different* tools reporting the same value is real
        corroboration and stays as two rows.
        """
        raw = str(raw)
        for existing in self.records:
            if (existing.tool, existing.fact, existing.raw) == (tool, fact, raw) \
                    and str(existing.source) == str(source):
                return existing
        ev = EvidenceRecord(
            id=f"EV-{len(self.records) + 1:03d}",
            tool=tool, source=source, fact=fact, raw=raw,
        )
        self.records.append(ev)
        return ev

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        for ev in self.records:
            if ev.id == evidence_id:
                return ev
        return None

    def to_list(self) -> list[dict]:
        return [ev.to_dict() for ev in self.records]
