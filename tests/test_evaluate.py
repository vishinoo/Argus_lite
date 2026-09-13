"""Does the evaluation suite actually evaluate anything?

A reliability harness is only worth its numbers if it can produce bad ones. A
check that cannot fail inflates the score and hides the regression it was
written to catch, and `lambda r: True` is easy to write by accident when you
are tired and the suite is nearly green.

So the suite is tested against a deliberately broken run. Every check must
reject it. If a check passes something this wrong, the check is decorative.
"""

from __future__ import annotations

import pytest

from ic.agent import RunResult
from ic.brief import Basis, Brief, Claim, Priority
from ic.evaluate import CHECKS, UNIVERSAL, evaluate, run_case
from ic.cases import CASES
from ic.reason import Incident
from ic.tools.base import Transcript


def empty_run() -> RunResult:
    """A brief that found nothing and admits nothing."""
    brief = Brief(
        incident_id="X", headline="FIRE", priority=Priority.HIGH,
        address="somewhere", location_verified=True,
    )
    return RunResult(
        incident=Incident("X", "somewhere", "fire"), brief=brief,
        transcript=Transcript(), executed=False,
    )


def unsourced_run() -> RunResult:
    """A brief with an external claim that names no source.

    This cannot be built through `Claim.recorded`, which raises — that is the
    guarantee. So it is built by going around the constructor, which is exactly
    what a careless future change would do, and is therefore the thing the
    check has to catch.
    """
    rogue = Claim("13 storeys", Basis.RECORDED, "from somewhere", 0.9, source=None)
    brief = Brief(
        incident_id="X", headline="FIRE", priority=Priority.HIGH,
        address="somewhere", location_verified=True, known=(rogue,),
    )
    return RunResult(
        incident=Incident("X", "somewhere", "fire"), brief=brief,
        transcript=Transcript(), executed=False,
    )


# Checks that assert the *absence* of something correctly pass a brief that
# found nothing; only the ones asserting presence are expected to reject it.
# Listed explicitly rather than inferred from the name — a prefix heuristic
# already missed `makes_no_place_claims` once, and a test that quietly excuses
# a check is worse than no test.
_NEGATIVE = {
    "no_unsupported_claims",
    "no_autonomous_dispatch",
    "no_aerial_consideration",
    "does_not_assert_threat",
    "makes_no_place_claims",
}


def test_the_negative_set_names_only_real_checks():
    assert _NEGATIVE <= set(CHECKS)


def test_every_positive_check_rejects_a_brief_that_found_nothing():
    # A check that passes a brief containing no findings is not measuring
    # anything, and would inflate the score it exists to protect.
    broken = empty_run()
    passing = [n for n, c in CHECKS.items() if n not in _NEGATIVE and c(broken)]
    assert passing == [], f"checks that cannot fail: {passing}"


def test_the_attribution_check_catches_a_claim_that_names_no_source():
    assert CHECKS["no_unsupported_claims"](unsourced_run()) is False


def test_the_constructor_refuses_to_build_that_claim_in_the_first_place():
    # Belt and braces: the check above is the second line of defence.
    with pytest.raises(ValueError):
        Claim.recorded("13 storeys", "from somewhere", source=None)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_every_case_passes(case):
    outcome = run_case(case)
    assert outcome.ok, f"{case.id} failed: {outcome.failed}"


def test_every_expectation_names_a_real_check():
    unknown = {e for c in CASES for e in c.expects if e not in CHECKS}
    assert unknown == set()


def test_the_suite_reports_the_absolutes_at_zero():
    report = evaluate()
    assert report["unsupported_claims"] == 0
    assert report["autonomous_dispatch_presented_as_fact"] == 0


# ── the suite must not touch the network ──────────────────────────────
#
# Found live: wiring the ntfy alert into the action phase made the 100-case
# evaluation fire 100 real HTTP requests at a third-party service. It hung, it
# got rate-limited, and a test suite that depends on somebody else's uptime is
# not a test suite. Evaluation actions rehearse; delivery is demonstrated in a
# real run, not in pytest.


def test_evaluation_actions_never_leave_the_machine():
    outcome = run_case(CASES[0])
    delivered = [a for a in outcome.result.actions if a.result.delivered]
    assert delivered == [], f"evaluation delivered {len(delivered)} real actions"


def test_actions_are_still_attempted_so_completion_stays_measurable():
    # Rehearsing must not mean skipping — the harness still reports whether
    # each action was prepared successfully.
    outcome = run_case(CASES[0])
    assert outcome.result.actions
    assert all(a.ok for a in outcome.result.actions)
