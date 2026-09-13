"""The brief, and the rules that keep it honest."""

from __future__ import annotations

import pytest

from ic.brief import Claim, Brief, Priority
from ic.provenance import Basis
from ic.tools.base import Source

OSM = Source("OpenStreetMap", "https://openstreetmap.org")


# ------------------------------------------------------------- the hard rule


def test_an_external_claim_must_name_its_source():
    # The whole reliability story rests on this. If a claim can be made
    # without saying where it came from, every metric downstream is decorative.
    with pytest.raises(ValueError):
        Claim.recorded("13 storeys", "building record", source=None)


def test_an_external_claim_with_a_source_is_allowed():
    c = Claim.recorded("13 storeys", "building record", source=OSM)
    assert c.basis is Basis.RECORDED
    assert c.source is OSM


def test_what_the_caller_said_needs_no_source_but_stays_caller_said():
    # The caller is the source. It never becomes a recorded fact.
    c = Claim.caller_said("someone may still be inside")
    assert c.basis is Basis.CALLER_SAID
    assert c.source is None


def test_an_inference_records_what_it_was_inferred_from():
    c = Claim.inferred("aerial access likely required", "13 storeys exceeds ground ladders", 0.7)
    assert c.basis is Basis.DERIVED
    assert "storeys" in c.evidence


def test_an_inference_never_claims_certainty():
    assert Claim.inferred("x", "y", 0.99).confidence < 1.0


# ------------------------------------------------------------- the brief


def simple_brief(**kw):
    base = dict(
        incident_id="IC-1",
        headline="STRUCTURE FIRE",
        priority=Priority.HIGH,
        address="1001 Van Ness Avenue",
        location_verified=True,
        known=(Claim.recorded("13 storeys", "building record", source=OSM),),
        hazards=(),
        resources=(),
        unknowns=("occupancy not independently confirmed",),
        considerations=(),
        conflicts=(),
    )
    base.update(kw)
    return Brief(**base)


def test_the_brief_states_what_it_does_not_know():
    # A brief that lists only what it found reads as complete. The unknowns
    # are the part that stops a crew trusting it too far.
    assert simple_brief().unknowns


def test_confidence_is_computed_not_asserted():
    verified = simple_brief(location_verified=True)
    unverified = simple_brief(location_verified=False)
    assert verified.confidence > unverified.confidence


def test_an_unverified_location_caps_confidence_hard():
    # If we are not sure where this is, nothing else we found matters much.
    assert simple_brief(location_verified=False).confidence <= 0.4


def test_more_corroboration_raises_confidence():
    thin = simple_brief()
    thick = simple_brief(known=tuple(
        Claim.recorded(f"fact {i}", "building record", source=OSM) for i in range(6)
    ))
    assert thick.confidence > thin.confidence


def test_unknowns_pull_confidence_down():
    few = simple_brief(unknowns=("one thing",))
    many = simple_brief(unknowns=tuple(f"unknown {i}" for i in range(6)))
    assert many.confidence < few.confidence


def test_confidence_never_reaches_certainty():
    loaded = simple_brief(
        known=tuple(Claim.recorded(f"f{i}", "rec", source=OSM) for i in range(20)),
        unknowns=(),
    )
    assert loaded.confidence < 1.0


def test_every_external_claim_in_a_brief_is_attributable():
    # This is the number that goes on the slide, so it is enforced here and
    # then measured by the harness rather than asserted in prose.
    b = simple_brief()
    assert b.attribution_rate == 1.0


def test_a_conflict_is_surfaced_rather_than_resolved():
    b = simple_brief(conflicts=("OSM says 13 storeys; permit record says 3",))
    assert "13 storeys" in b.render()


def test_the_brief_renders_the_unknowns_section():
    assert "not independently confirmed" in simple_brief().render()


def test_the_brief_never_reads_as_an_order():
    # Argus prepares; a human decides. The rendered brief has to say so.
    assert "advisory" in simple_brief().render().lower()
