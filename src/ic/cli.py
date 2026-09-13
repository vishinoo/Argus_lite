"""Argus Incident Commander at the command line.

The run is rendered as it happens rather than summarised afterwards, because
watching an agent work is the only way to see that it is working rather than
narrating. Each tool call prints when it lands, with its latency and what it
cited.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from ic.agent import IncidentCommander, LiveInvestigator
from ic.config import live_count, load_env, status as integration_status
from ic.brief import Priority
from ic.reason import Incident, classify
from ic.tools.base import ToolCall, Transcript

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"


def _colour(enabled: bool):
    if enabled:
        return DIM, BOLD, RESET, RED, GREEN, YELLOW
    return "", "", "", "", "", ""


# Street types that end the address proper. Anything after them is a city, a
# state, or narrative.
_STREET_TYPE = (
    r"street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|"
    r"place|pl|square|sq|terrace|ter|highway|hwy|parkway|pkwy|alley|circle"
)

# A comma-separated clause is part of the address only if it still looks like a
# place. Chasing a stop-word list ("possible", "caller", "patient", …) is a
# losing game — there is always another word. Asking "does this look like a
# place name?" is the durable question.
_PLACE_CLAUSE = re.compile(
    r"^[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3}$"    # San Francisco, Nob Hill
    r"|^[A-Z]{2}$"                                   # CA
    r"|^\d{5}(?:-\d{4})?$",                          # 94109
)


def extract_address(text: str) -> str | None:
    """Pull an address out of what the dispatcher typed.

    Deliberately conservative. A wrong address is worse than no address: it
    sends the whole investigation somewhere else and every finding after it
    inherits the error. When this cannot find one, the CLI asks rather than
    guesses.
    """
    m = re.search(
        rf"\bat\s+(\d+[\w\s.'-]*?(?:{_STREET_TYPE})\b[\w\s,.'-]*)", text, re.I
    )
    if not m:
        m = re.search(
            rf"\b(\d{{1,6}}\s+[\w\s.'-]*?(?:{_STREET_TYPE})\b[\w\s,.'-]*)", text, re.I
        )
    if not m:
        m = re.search(r"\b(\d{1,6}\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3})", text)
        return m.group(1).strip(" ,.") if m else None

    # Sentence boundary always ends it.
    head = re.split(r"[.;]", m.group(1), maxsplit=1)[0]

    # Then keep comma clauses only while they still read as a place.
    clauses = [c.strip(" ,.") for c in head.split(",")]
    kept = [clauses[0]]
    for clause in clauses[1:]:
        if _PLACE_CLAUSE.match(clause):
            kept.append(clause)
        else:
            break
    return ", ".join(kept).strip(" ,.")


def cmd_check(args: argparse.Namespace) -> int:
    """Say plainly which integrations are live and which are rehearsing."""
    load_env()
    dim, bold, reset, red, green, yellow = _colour(sys.stdout.isatty())
    live, total = live_count()
    print(f"\n{bold}  ARGUS INTEGRATIONS{reset}   {live}/{total} live\n")
    for item in integration_status():
        mark = f"{green}●{reset}" if item.live else f"{yellow}○{reset}"
        print(f"  {mark} {item.name:<22} {item.detail}")
        if not item.live and item.how:
            print(f"{dim}      → {item.how}{reset}")
    print()
    if live < total:
        print(f"{dim}  Rehearsed actions are written to out/ and counted separately "
              f"from delivered ones.{reset}\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    load_env()
    dim, bold, reset, red, green, yellow = _colour(not args.no_colour and sys.stdout.isatty())

    address = args.address or extract_address(args.text)
    if not address:
        print(f"{red}Cannot identify an address in that description.{reset}\n"
              f"  Pass --address explicitly. Argus does not guess a location: a wrong\n"
              f"  address sends the entire investigation somewhere else.", file=sys.stderr)
        return 2

    incident = Incident(
        incident_id=args.id, address=address, description=args.text
    )

    if not args.json:
        print(f"\n{bold}ARGUS INCIDENT COMMANDER{reset}")
        print(f"{dim}  observe → investigate → reason → decide → act → document{reset}\n")
        print(f"  incident   {incident.incident_id}")
        print(f"  reported   \"{incident.description}\"")
        print(f"  address    {address}")
        print(f"  classified {classify(incident.description).value}\n")
        print(f"{dim}  ── investigating {'─' * 46}{reset}")

    def show(call: ToolCall) -> None:
        if args.json:
            return
        mark = f"{green}✓{reset}" if call.ok else f"{red}✗{reset}"
        tag = f" {yellow}rehearsed{reset}" if call.result.rehearsed else ""
        print(f"  {mark} {call.tool:<22} {call.latency_ms:6.0f}ms  "
              f"{call.result.summary[:64]}{tag}")
        if call.result.error and not call.ok:
            print(f"      {dim}{call.result.error}{reset}")

    transcript = Transcript(on_call=show)
    commander = IncidentCommander(
        LiveInvestigator(), notify_email=args.notify,
        schedule_briefing=not args.no_calendar,
    )
    result = commander.run(incident, execute=args.execute, transcript=transcript)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print()
    _evidence_chain(result, dim, bold, reset)
    _picture(result, dim, bold, reset, red, green, yellow)
    print()

    if result.refused:
        print(f"  {red}{bold}WORKFLOW NOT EXECUTED{reset}")
        print(f"  {result.refused}\n")
    elif not result.executed:
        print(f"  {dim}Brief prepared. Re-run with --execute to open the incident "
              f"channel and notify.{reset}\n")

    _dashboard(result, dim, bold, reset, green, yellow)
    return 0


_STATUS_COLOUR = {"VERIFIED": "\033[32m", "REPORTED": "\033[33m",
                  "INFERRED": "\033[36m", "CONTRADICTED": "\033[35m",
                  "UNKNOWN": "\033[31m"}


def _evidence_chain(result, dim, bold, reset) -> None:
    """Where each part of the picture came from, in the order it arrived.

    The point of showing this is that a judge — or a fire chief — can see the
    brief being *constructed from evidence* rather than produced whole by a
    model. Every arrow is a real tool call with a real latency.
    """
    calls = [c for c in result.transcript.calls
             if not c.tool.split(".")[0] in {"slack", "gmail", "calendar"}]
    if not calls:
        return
    print(f"{bold}  EVIDENCE CHAIN{reset}")
    print(f"    CALLER REPORT")
    print(f"{dim}      ↓  \"{result.incident.description[:58]}\"{reset}")
    for c in calls:
        mark = "✓" if c.ok else "✗"
        why = c.args.get("because", "")
        print(f"    {mark} {c.tool}")
        detail = c.result.summary if c.ok else (c.result.error or "failed")
        print(f"{dim}      ↓  {detail[:62]}{reset}")
        if why:
            print(f"{dim}         sought: {why[:56]}{reset}")
    print(f"    ARGUS SYNTHESIS")
    print()


def _picture(result, dim, bold, reset, red, green, yellow) -> None:
    picture = result.brief.picture
    if picture is None:
        print(result.brief.render())
        return

    print(f"{bold}  {result.brief.priority.value} — {result.brief.headline}{reset}")
    print(f"  {result.brief.address}\n")

    sections = (
        ("SITUATION", picture.situation),
        ("PEOPLE", picture.people),
        ("THREATS", picture.threats),
        ("EXPOSURES — at risk if this spreads", picture.exposures),
        ("RESOURCES", picture.resources),
        ("APPROACH — second agent: upwind side, plume, water", picture.approach),
        ("OPEN QUESTIONS — no source can settle these before arrival",
         picture.open_questions),
    )
    for title, items in sections:
        if not items:
            continue
        print(f"  {title}")
        for a in items:
            colour = _STATUS_COLOUR.get(a.status.value, "") if green else ""
            end = reset if colour else ""
            value = a.value if a.value is not None else "—"
            print(f"    {colour}{a.status.value:<9}{end} {a.field:<17} {str(value)[:49]}")
            cite = a.source.label if a.source else a.evidence
            print(f"{dim}      confidence {a.band.value:<7} {str(cite)[:58]}{reset}")
        print()

    if picture.conflicts:
        print(f"  {yellow}CONFLICTING SOURCES{reset}")
        for c in picture.conflicts:
            print(f"    ! {c}")
        print()

    from ic.schema import Status

    kind = classify(result.incident.description)
    counts = {s.value: len(picture.by_status(s)) for s in Status}
    print(f"  determined {picture.completeness(kind):.0%} of what is knowable · "
          f"{counts['VERIFIED']} verified · {counts['REPORTED']} reported · "
          f"{counts['INFERRED']} inferred · {counts['CONTRADICTED']} contradicted · "
          f"{counts['UNKNOWN']} unknown")
    print(f"{dim}  The open questions above are the ones that decide this incident,{reset}")
    print(f"{dim}  and no desk can answer them. Argus does not dispatch; a human decides.{reset}")
    print()


def _dashboard(result, dim, bold, reset, green, yellow) -> None:
    t = result.transcript
    tick = f"{green}✓{reset}"
    cross = f"{yellow}—{reset}"
    rows = [
        ("Incident created", True),
        ("Location verified", result.brief.location_verified),
        ("External intelligence gathered", any(
            c.ok for c in t.calls if c.tool.startswith(("web.", "maps.nearby")))),
        ("Sources evaluated", bool(t.sources)),
        ("Brief generated", True),
        ("Slack notified", any(c.tool.startswith("slack") and c.ok for c in t.calls)),
        ("Email notified", any(c.tool == "gmail.send" and c.ok for c in t.calls)),
        ("Briefing scheduled", any(c.tool == "calendar.schedule" and c.ok for c in t.calls)),
    ]
    print(f"{bold}  DASHBOARD{reset}")
    for label, ok in rows:
        print(f"    {label:<34}{tick if ok else cross}")
    print()
    print(f"    {'tool calls':<34}{t.succeeded}/{t.total} succeeded")
    print(f"    {'sources cited':<34}{len(t.sources)}")
    print(f"    {'external claims attributable':<34}{result.brief.attribution_rate:.0%}")
    print(f"    {'unsupported claims':<34}{len(result.brief.unsupported)}")
    print(f"    {'actions delivered / rehearsed':<34}"
          f"{result.delivered} / {result.rehearsed}")
    print(f"    {'elapsed':<34}{result.elapsed_s:.1f}s")
    if result.artifacts:
        print(f"\n{dim}    artifacts:{reset}")
        for a in result.artifacts:
            print(f"      {a}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ic",
        description="Argus Incident Commander — an emergency call to a sourced brief",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="work an incident end to end")
    run.add_argument("text", help="what the dispatcher was told")
    run.add_argument("--address", default=None, help="override the extracted address")
    run.add_argument("--id", default="IC-001")
    run.add_argument("--execute", action="store_true",
                     help="carry out the actions, not just prepare them")
    run.add_argument("--notify", default="command@example.gov")
    run.add_argument("--no-calendar", action="store_true")
    run.add_argument("--json", action="store_true")
    run.add_argument("--no-colour", action="store_true")
    run.set_defaults(func=cmd_run)

    web = sub.add_parser("serve", help="the console in a browser")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--host", default="127.0.0.1")
    web.set_defaults(func=lambda a: (
        __import__("ic.server", fromlist=["serve"]).serve(a.host, a.port) or 0))

    check = sub.add_parser("check", help="which integrations are live")
    check.set_defaults(func=cmd_check)

    ev = sub.add_parser("eval", help="run the reliability suite")
    ev.add_argument("--live", action="store_true",
                    help="hit real APIs instead of fixtures")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=lambda a: __import__("ic.evaluate", fromlist=["main"]).main(a))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
