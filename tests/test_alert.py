"""The responder alert: an external action that needs no credentials."""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from ic.tools import alert


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_ntfy(monkeypatch, reply=None, boom=None):
    sent = []

    def urlopen(req, timeout=None):
        sent.append({"url": req.full_url,
                     "headers": {k.lower(): v for k, v in req.header_items()},
                     "body": req.data.decode()})
        if boom:
            raise boom
        return FakeResponse(json.dumps(reply or {"id": "abc123", "topic": "t"}).encode())

    monkeypatch.setattr(alert.urllib.request, "urlopen", urlopen)
    return sent


def test_an_alert_is_actually_delivered_not_rehearsed(monkeypatch):
    # The whole point: this one needs no token, so it is never rehearsing.
    fake_ntfy(monkeypatch)
    result = alert.responder_alert("topic", "STRUCTURE FIRE", "1001 Van Ness")
    assert result.ok and result.delivered and not result.rehearsed


def test_the_alert_carries_a_title_and_a_body(monkeypatch):
    sent = fake_ntfy(monkeypatch)
    alert.responder_alert("topic", "STRUCTURE FIRE", "1001 Van Ness Avenue")
    assert "STRUCTURE FIRE" in sent[0]["headers"]["title"]
    assert "Van Ness" in sent[0]["body"]


def test_the_delivery_id_comes_back_as_proof(monkeypatch):
    fake_ntfy(monkeypatch, reply={"id": "2YMhwclcwllk", "topic": "t"})
    result = alert.responder_alert("topic", "FIRE", "body")
    assert "2YMhwclcwllk" in result.summary


def test_a_refused_delivery_is_reported_not_swallowed(monkeypatch):
    fake_ntfy(monkeypatch, boom=OSError("network down"))
    result = alert.responder_alert("topic", "FIRE", "body")
    assert not result.ok and result.error


# ── the thing that matters about a public channel ─────────────────────


def test_the_alert_body_is_a_summary_not_the_whole_brief():
    # ntfy topics are public and unauthenticated: anyone who knows the topic
    # can read it. A short operational alert is appropriate there; a full
    # incident brief with occupancy and caller detail is not.
    body = alert.alert_body("STRUCTURE FIRE", "1001 Van Ness Avenue",
                            ["13 storeys", "approach from WNW"])
    assert len(body) < 300


def test_the_alert_never_carries_what_the_caller_said():
    body = alert.alert_body("STRUCTURE FIRE", "1001 Van Ness Avenue",
                            ["13 storeys"], caller_account="my father is inside, he is 81")
    assert "father" not in body and "81" not in body


def test_a_generated_topic_is_unguessable_enough_to_not_collide():
    a, b = alert.default_topic(), alert.default_topic()
    assert a != b and len(a) > 16


# ── headers are latin-1, and our prose is not ─────────────────────────
#
# Found live. The title carried an em dash and urllib raised
# UnicodeEncodeError before the request left the machine — a 0 ms "not
# delivered" that looked like a network problem and was not.


def test_a_title_with_an_em_dash_is_still_delivered(monkeypatch):
    sent = fake_ntfy(monkeypatch)
    result = alert.responder_alert("topic", "STRUCTURE FIRE — IC-1847", "body")
    assert result.ok
    sent[0]["headers"]["title"].encode("latin-1")  # must not raise


def test_typographic_punctuation_is_transliterated_not_dropped():
    assert alert.ascii_header("FIRE — IC-1847 · “quoted”") == 'FIRE - IC-1847 - "quoted"'


def test_anything_still_unencodable_is_removed_rather_than_raising():
    alert.ascii_header("smoke 🔥 showing").encode("latin-1")


def test_the_body_may_still_carry_real_punctuation(monkeypatch):
    # Only headers are latin-1. The body is UTF-8 and should keep its typography.
    sent = fake_ntfy(monkeypatch)
    alert.responder_alert("topic", "FIRE", "1001 Van Ness · 13 storeys")
    assert "·" in sent[0]["body"]


# ── the topic must be stable ──────────────────────────────────────────
#
# Found live: a fresh topic per run meant ntfy saw a new topic every time,
# which is what its anonymous rate limit exists to stop (HTTP 429). It is also
# wrong for a demo — a judge subscribing on their phone would have to
# re-subscribe for every incident.


def test_the_topic_persists_across_calls(tmp_path, monkeypatch):
    monkeypatch.delenv("ARGUS_NTFY_TOPIC", raising=False)
    monkeypatch.setattr(alert, "TOPIC_FILE", tmp_path / "topic")
    first = alert.configured_topic()
    second = alert.configured_topic()
    assert first == second


def test_an_explicit_topic_from_the_environment_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(alert, "TOPIC_FILE", tmp_path / "topic")
    monkeypatch.setenv("ARGUS_NTFY_TOPIC", "my-own-topic")
    assert alert.configured_topic() == "my-own-topic"


def test_rate_limiting_is_reported_as_rate_limiting(monkeypatch):
    import urllib.error
    fake_ntfy(monkeypatch, boom=urllib.error.HTTPError(
        "https://ntfy.sh/t", 429, "Too Many Requests", {}, None))
    result = alert.responder_alert("topic", "FIRE", "body")
    assert not result.ok
    assert "rate" in (result.error or "").lower()
