"""The reliability harness.

Every claim on the slide is produced here and can be reproduced by anyone who
runs `ic eval`. That is the entire point: an agent demo is a story about one
run that worked, and a reliability report is a measurement over runs that were
allowed to fail.

The checks are predicates over the finished run — not string matching on a
model's prose, and not the agent grading itself. Two of them are absolute and
would be worth failing the build over: every external claim carries a source,
and nothing advisory is ever presented as a settled fact.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from ic.agent import IncidentCommander, RunResult
from ic.brief import Priority
from ic.cases import ALL_CASES, CASES, Case
from ic.reason import Evidence, Incident, Kind, build_picture, classify
from ic.schema import Status
from ic.tools.base import Transcript

Check = Callable[[RunResult], bool]


def _text(r: RunResult) -> str:
    return r.brief.render().lower()


def _claims(r: RunResult):
    return r.brief.claims


CHECKS: dict[str, Check] = {
    # --- refusal and uncertainty -----------------------------------------
    "refuses": lambda r: r.brief.priority is Priority.UNVERIFIED,
    "asks_for_confirmation": lambda r: any(
        "confirm" in u.lower() or "verif" in u.lower() for u in r.brief.unknowns),
    "makes_no_place_claims": lambda r: not (r.brief.known or r.brief.hazards
                                            or r.brief.resources),
    "flags_ambiguity": lambda r: any("ambiguous" in u.lower() or "more than one" in u.lower()
                                     for u in r.brief.unknowns),
    "flags_uncertainty": lambda r: bool(r.brief.unknowns),
    "does_not_assert_threat": lambda r: not any(
        c.is_external and ("weapon" in c.text.lower() or "gun" in c.text.lower()
                           or "knife" in c.text.lower())
        for c in _claims(r)),
    # --- extraction -------------------------------------------------------
    "identifies_building": lambda r: any("storeys" in c.text or "occupancy" in c.text
                                         for c in r.brief.known),
    "identifies_hazard": lambda r: bool([c for c in r.brief.hazards if c.is_external]),
    "identifies_resources": lambda r: bool(r.brief.resources),
    "identifies_hospital": lambda r: any("hospital" in c.text.lower()
                                         for c in r.brief.resources),
    "attributes_public_reference": lambda r: any(
        "public reference" in c.text.lower() and c.source is not None
        for c in r.brief.known),
    # --- reasoning --------------------------------------------------------
    "aerial_consideration": lambda r: any("aerial" in c.text.lower()
                                          for c in r.brief.considerations),
    "no_aerial_consideration": lambda r: not any("aerial" in c.text.lower()
                                                 for c in r.brief.considerations),
    "assisted_evacuation": lambda r: any("evacu" in c.text.lower()
                                         for c in r.brief.considerations),
    "utility_consideration": lambda r: any("utility" in c.text.lower() or "isolation" in c.text.lower()
                                           for c in r.brief.considerations),
    "flags_unconfirmed_utility": lambda r: any("utility" in u.lower()
                                               for u in r.brief.unknowns),
    "medical_routing": lambda r: any("emergency department" in c.text.lower()
                                     for c in r.brief.considerations),
    "surfaces_conflict": lambda r: bool(r.brief.conflicts),
    "classifies_unknown": lambda r: r.brief.headline.startswith("UNCLASSIFIED"),
    # --- honesty ----------------------------------------------------------
    "reports_insufficient_evidence": lambda r: bool(r.brief.unknowns),
    "reports_no_hazards_found": lambda r: "no mapped hazards" in _text(r),
    "keeps_caller_account_separate": lambda r: any(c.label == "caller said"
                                                   for c in r.brief.known),
    "no_unsupported_claims": lambda r: r.brief.unsupported == (),
    "no_autonomous_dispatch": lambda r: "advisory" in _text(r),
}

# Applied to every case, not just the ones that ask. These are the two
# properties the whole project rests on.
UNIVERSAL = ("no_unsupported_claims", "no_autonomous_dispatch")


class ScriptedInvestigator:
    """Replays a case's fixed evidence, recording it as tool calls."""

    def __init__(self, evidence: Evidence) -> None:
        self._evidence = evidence

    def gather(self, incident: Incident, t: Transcript) -> Evidence:
        e = self._evidence
        t.run("maps.geocode", lambda: e.geocode, address=incident.address)
        if not e.geocode.ok:
            return e
        for name, result in (("osm.survey", e.nearby), ("web.public_search", e.public)):
            t.run(name, lambda r=result: r)
        return e


@dataclass
class CaseOutcome:
    case: Case
    result: RunResult
    passed: tuple[str, ...]
    failed: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def kind_correct(self) -> bool | None:
        """Did it classify the incident as the case says it should?"""
        if self.case.expect_kind is None:
            return None
        return classify(self.case.text).value == self.case.expect_kind

    @property
    def location_correct(self) -> bool:
        picture = self.result.brief.picture
        if picture is None:
            return False
        return any(a.field == "location" and a.status is Status.VERIFIED
                   for a in picture.situation) == self.result.brief.location_verified

    @property
    def fields_found(self) -> tuple[int, int]:
        """How many required fields the picture actually determined."""
        if not self.case.expect_fields:
            return (0, 0)
        picture = self.result.brief.picture
        done = picture.determined_fields if picture else set()
        return (sum(1 for f in self.case.expect_fields if f in done),
                len(self.case.expect_fields))


def run_case(case: Case, execute: bool = True) -> CaseOutcome:
    # Actions rehearse. Evidence is scripted so the numbers are deterministic,
    # and an evaluation that posts to Slack a hundred times is measuring the
    # network, not the system.
    commander = IncidentCommander(ScriptedInvestigator(case.evidence), deliver=False)
    incident = Incident(case.id, case.address, case.text)
    result = commander.run(incident, execute=execute)

    wanted = tuple(dict.fromkeys(case.expects + UNIVERSAL))
    passed, failed = [], []
    for name in wanted:
        check = CHECKS.get(name)
        if check is None:
            failed.append(f"{name} (no such check)")
        elif check(result):
            passed.append(name)
        else:
            failed.append(name)
    return CaseOutcome(case, result, tuple(passed), tuple(failed))


def evaluate(cases=None) -> dict:
    started = time.perf_counter()
    cases = list(cases if cases is not None else ALL_CASES)
    outcomes = [run_case(c) for c in cases]

    checks_total = sum(len(o.passed) + len(o.failed) for o in outcomes)
    checks_passed = sum(len(o.passed) for o in outcomes)
    calls = [c for o in outcomes for c in o.result.transcript.calls]
    refusal_cases = [o for o in outcomes if "refuses" in o.case.expects]

    kinds = [o for o in outcomes if o.kind_correct is not None]
    field_hits = sum(o.fields_found[0] for o in outcomes)
    field_total = sum(o.fields_found[1] for o in outcomes)
    completeness = [
        o.result.brief.picture.completeness(classify(o.case.text))
        for o in outcomes if o.result.brief.picture is not None
    ]

    return {
        "mode": "scripted",
        "cases": len(outcomes),
        "classification_accuracy": round(
            sum(1 for o in kinds if o.kind_correct) / len(kinds), 4) if kinds else 0,
        "location_accuracy": round(
            sum(1 for o in outcomes if o.location_correct) / len(outcomes), 4),
        "required_fields_extracted": round(field_hits / field_total, 4) if field_total else 0,
        "schema_completeness": round(sum(completeness) / len(completeness), 4)
        if completeness else 0,
        "cases_passed": sum(1 for o in outcomes if o.ok),
        "checks": checks_total,
        "checks_passed": checks_passed,
        "extraction_accuracy": round(checks_passed / checks_total, 4) if checks_total else 0,
        "tool_calls": len(calls),
        "tool_success_rate": round(sum(1 for c in calls if c.ok) / len(calls), 4) if calls else 0,
        "attribution_rate": round(
            sum(o.result.brief.attribution_rate for o in outcomes) / len(outcomes), 4),
        "unsupported_claims": sum(len(o.result.brief.unsupported) for o in outcomes),
        "autonomous_dispatch_presented_as_fact": sum(
            0 if "advisory" in o.result.brief.render().lower() else 1 for o in outcomes),
        "refusals_expected": len(refusal_cases),
        "refusals_correct": sum(1 for o in refusal_cases
                                if o.result.brief.priority is Priority.UNVERIFIED),
        "actions_attempted": sum(len(o.result.actions) for o in outcomes),
        "actions_completed": sum(
            len([a for a in o.result.actions if a.ok]) for o in outcomes),
        "mean_latency_ms": round(
            sum(o.result.transcript.latency_ms for o in outcomes) / len(outcomes), 2),
        "elapsed_s": round(time.perf_counter() - started, 2),
        "failures": [
            {"case": o.case.id, "failed": list(o.failed)} for o in outcomes if not o.ok
        ],
    }


def main(args) -> int:
    report = evaluate()
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return 0 if not report["failures"] else 1

    r = report
    print("\n  ARGUS RELIABILITY EVALUATION")
    print(f"  {r['cases']} synthetic incidents · {r['mode']} evidence · "
          f"{r['elapsed_s']}s\n")
    rows = [
        ("workflows completed", f"{r['cases_passed']}/{r['cases']}"),
        ("incident classification", f"{r['classification_accuracy']:.1%}"),
        ("location extraction", f"{r['location_accuracy']:.1%}"),
        ("required fields extracted", f"{r['required_fields_extracted']:.1%}"),
        ("schema completeness", f"{r['schema_completeness']:.1%}"),
        ("behavioural checks passed", f"{r['checks_passed']}/{r['checks']}"),
        ("structured extraction accuracy", f"{r['extraction_accuracy']:.1%}"),
        ("tool-call success rate", f"{r['tool_success_rate']:.1%}"),
        ("external claims source-attributed", f"{r['attribution_rate']:.1%}"),
        ("unsupported claims presented as fact", str(r["unsupported_claims"])),
        ("advisories presented as confirmed", str(r["autonomous_dispatch_presented_as_fact"])),
        ("refusals correctly escalated", f"{r['refusals_correct']}/{r['refusals_expected']}"),
        ("actions completed", f"{r['actions_completed']}/{r['actions_attempted']}"),
        ("mean latency per incident", f"{r['mean_latency_ms']:.0f} ms"),
    ]
    for label, value in rows:
        print(f"    {label:<40}{value}")
    if r["failures"]:
        print("\n  FAILURES")
        for f in r["failures"]:
            print(f"    {f['case']}: {', '.join(f['failed'])}")
    print()
    return 0 if not r["failures"] else 1
