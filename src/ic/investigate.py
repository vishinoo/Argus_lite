"""Deciding what to find out next.

The first version of this was a fixed pipeline: geocode, survey, search, done.
That is a script with an LLM bolted to it, and it cannot adapt — a gas leak and
a missing person got identical investigations because the sequence was written
in advance.

This version is given a goal instead. The schema says which fields this kind of
incident obliges Argus to determine; the picture says which of them are still
unknown; and each tool declares which fields it can answer. Investigation is
then just: while something required is missing, run a tool that could supply
it. Nothing is sequenced by hand.

The useful consequence is that behaviour changes when the *schema* changes, not
when the pipeline does. Adding `utility` to the gas schema makes the agent start
looking up utility operators on gas calls, with no new control flow anywhere.

Location comes first and alone, because everything else is a question about a
place. If the place is not established there is nothing to ask questions about,
and the remaining tools are recorded as deliberately skipped rather than
quietly not run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ic.schema import Picture
from ic.tools.base import ToolResult, Transcript

# What each tool can answer. The planner matches these against the gaps.
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "maps.geocode": ("location",),
    "osm.survey": ("building", "occupancy", "hazards", "fire_station", "hospital",
                   "access"),
    "web.public_search": ("public_context",),
    "osm.utility": ("utility",),
}

# A hard stop, so a schema gap nothing can answer cannot spin forever.
MAX_STEPS = 6


@dataclass(frozen=True)
class Step:
    """One decision the planner made, and why it made it."""

    tool: str
    because: tuple[str, ...]
    """The gaps this call was chosen to close."""

    @property
    def reason(self) -> str:
        return f"{self.tool} — to determine {', '.join(self.because)}"


def plan(gaps: tuple[str, ...], already_run: set[str]) -> Step | None:
    """The next tool worth running, or None when nothing would help.

    Chooses the tool that closes the most outstanding gaps, so one Overpass
    survey is preferred over several narrower lookups.
    """
    best: Step | None = None
    for tool, answers in CAPABILITIES.items():
        if tool in already_run:
            continue
        closes = tuple(g for g in gaps if g in answers)
        if closes and (best is None or len(closes) > len(best.because)):
            best = Step(tool, closes)
    return best


class GapDrivenInvestigator:
    """Investigates until the schema is satisfied or nothing more can help."""

    def __init__(self, runners: dict[str, Callable[[], ToolResult]],
                 rebuild: Callable[[dict[str, ToolResult]], Picture],
                 kind) -> None:
        self._runners = runners
        self._rebuild = rebuild
        self._kind = kind

    def run(self, transcript: Transcript) -> tuple[Picture, dict[str, ToolResult],
                                                   tuple[Step, ...]]:
        results: dict[str, ToolResult] = {}
        taken: list[Step] = []
        ran: set[str] = set()

        for _ in range(MAX_STEPS):
            picture = self._rebuild(results)
            gaps = picture.gaps(self._kind)
            if not gaps:
                break
            step = plan(gaps, ran)
            if step is None:
                break
            runner = self._runners.get(step.tool)
            if runner is None:
                ran.add(step.tool)
                continue
            taken.append(step)
            ran.add(step.tool)
            results[step.tool] = transcript.run(
                step.tool, runner, because=", ".join(step.because)
            )

            # Everything after location is a question about a place. Without
            # one there is nothing to ask, and the rest is skipped on purpose.
            if step.tool == "maps.geocode" and not results[step.tool].ok:
                for tool in CAPABILITIES:
                    if tool not in ran:
                        transcript.run(
                            tool,
                            lambda: ToolResult(False, "skipped — location unverified",
                                               error="no verified location"),
                            because="skipped: nothing to ask without a location",
                        )
                        ran.add(tool)
                break

        return self._rebuild(results), results, tuple(taken)
