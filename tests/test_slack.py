"""The Slack path, which rehearsal cannot exercise.

Rehearsed actions never call Slack, so every mistake in the real request
survives until the first run with a live token — which, on a demo day, is the
worst possible moment to discover that `chat.postMessage` wants a channel ID
and was being handed a name.
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from ic.tools import comms


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_slack(monkeypatch, replies):
    """Answer each Slack endpoint from `replies`, recording what was sent."""
    sent: list[dict] = []

    def urlopen(req, timeout=None):
        endpoint = req.full_url.rsplit("/", 1)[-1]
        sent.append({"endpoint": endpoint, "body": json.loads(req.data.decode())})
        return FakeResponse(json.dumps(replies[endpoint]).encode())

    monkeypatch.setattr(comms.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    return sent


def test_a_new_channel_reports_the_id_slack_assigned(monkeypatch):
    fake_slack(monkeypatch, {
        "conversations.create": {"ok": True, "channel": {"id": "C123", "name": "inc"}},
    })
    result = comms.slack_open_channel("inc")
    assert result.ok and result.data["id"] == "C123"


def test_posting_uses_the_channel_id_not_the_name(monkeypatch):
    # chat.postMessage resolves IDs. Handed a bare name it returns
    # channel_not_found, and the brief silently never arrives.
    sent = fake_slack(monkeypatch, {"chat.postMessage": {"ok": True}})
    comms.slack_post("C123", "brief")
    assert sent[0]["body"]["channel"] == "C123"


def test_an_existing_channel_is_reused_rather_than_failing(monkeypatch):
    # Demoing the same incident twice must not fail on name_taken. It will
    # happen, because a rehearsal always precedes the real run.
    fake_slack(monkeypatch, {
        "conversations.create": {"ok": False, "error": "name_taken"},
        "conversations.list": {"ok": True, "channels": [
            {"id": "C999", "name": "incident-ic-1847"},
            {"id": "C111", "name": "something-else"},
        ]},
    })
    result = comms.slack_open_channel("incident-ic-1847")
    assert result.ok
    assert result.data["id"] == "C999"
    assert "existing" in result.summary.lower()


def test_a_genuine_slack_error_is_still_reported(monkeypatch):
    fake_slack(monkeypatch, {
        "conversations.create": {"ok": False, "error": "invalid_auth"},
    })
    result = comms.slack_open_channel("inc")
    assert not result.ok and "invalid_auth" in (result.error or "")
