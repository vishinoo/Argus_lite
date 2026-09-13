"""The tool layer, and the record of every call made through it.

Two ideas carry the whole project.

The first is that a tool call is an event worth keeping. Not just its result —
the call itself: which tool, with what arguments, how long it took, whether it
worked, and what it cited. That record is what the dashboard renders live, what
the evaluation harness measures, and what a reviewer reads afterwards to see
what the agent actually did rather than what it said it did. An agent that
cannot show its working is a demo; one that can is a system.

The second is that a tool is allowed to fail, and failing is not an error in
the program — it is information about the world. An address that does not
geocode, a search that returns nothing, a Slack workspace with no credentials:
each is a normal outcome that the agent has to reason about rather than crash
on or paper over. So every tool returns a result that can be empty, and the
reason it is empty travels with it.

Rehearsal mode
--------------
Tools that would send something to a real person — Slack, mail, a calendar
invitation — run in rehearsal unless credentials are present. Rehearsal
records exactly what *would* have been sent and marks itself as rehearsed. It
is not a stub that pretends to succeed: the transcript says `rehearsed`, the
dashboard says `rehearsed`, and the evaluation counts it separately from a
delivered action. Nobody should be able to watch this run and come away
believing an email went out when it did not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class Source:
    """Where a piece of information came from. Shown wherever it is used."""

    label: str
    url: str | None = None

    def __str__(self) -> str:
        return f"{self.label}" + (f" <{self.url}>" if self.url else "")


@dataclass(frozen=True)
class ToolResult:
    """What a tool produced, and what stands behind it."""

    ok: bool
    summary: str
    """One line a human can read on a dashboard."""
    data: Any = None
    sources: tuple[Source, ...] = ()
    rehearsed: bool = False
    """True when the action was prepared but deliberately not delivered."""
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.ok and not self.rehearsed


@dataclass(frozen=True)
class ToolCall:
    """One invocation, kept whether it succeeded or not."""

    tool: str
    args: dict[str, Any]
    result: ToolResult
    latency_ms: float

    @property
    def ok(self) -> bool:
        return self.result.ok

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": {k: v for k, v in self.args.items() if k != "secret"},
            "ok": self.result.ok,
            "rehearsed": self.result.rehearsed,
            "summary": self.result.summary,
            "sources": [str(s) for s in self.result.sources],
            "error": self.result.error,
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class Transcript:
    """Everything the agent did, in order."""

    calls: list[ToolCall] = field(default_factory=list)
    on_call: Callable[[ToolCall], None] | None = None
    """Hook so a live display can render each call as it lands."""

    def record(self, call: ToolCall) -> ToolCall:
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)
        return call

    def run(self, tool: str, fn: Callable[[], ToolResult], **args: Any) -> ToolResult:
        """Invoke `fn`, timing it and keeping the record either way.

        A tool that raises is recorded as a failed call rather than allowed to
        take down the run. The agent decides what a failure means; it should
        never be denied the chance to decide by an exception.
        """
        start = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - a failing tool is data
            result = ToolResult(
                ok=False, summary=f"{tool} failed", error=f"{type(exc).__name__}: {exc}"
            )
        elapsed = (time.perf_counter() - start) * 1000
        self.record(ToolCall(tool=tool, args=args, result=result, latency_ms=elapsed))
        return result

    # ------------------------------------------------------------ measures

    @property
    def total(self) -> int:
        return len(self.calls)

    @property
    def succeeded(self) -> int:
        return sum(1 for c in self.calls if c.ok)

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.total if self.total else 0.0

    @property
    def latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    @property
    def sources(self) -> tuple[Source, ...]:
        seen: dict[str, Source] = {}
        for c in self.calls:
            for s in c.result.sources:
                seen.setdefault(str(s), s)
        return tuple(seen.values())

    def actions(self) -> Iterator[ToolCall]:
        """Calls that changed something outside this process, or would have."""
        for c in self.calls:
            if c.tool.split(".")[0] in {"slack", "gmail", "calendar", "ntfy"}:
                yield c

    def to_dict(self) -> dict:
        return {
            "calls": [c.to_dict() for c in self.calls],
            "total": self.total,
            "succeeded": self.succeeded,
            "success_rate": round(self.success_rate, 3),
            "latency_ms": round(self.latency_ms, 1),
        }
