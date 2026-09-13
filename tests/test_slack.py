"""The Slack path, which rehearsal cannot exercise.

Rehearsed actions never call Slack, so every mistake in the real request
survives until the first run with a live token — which, on a demo day, is the
worst possible moment to discover that `chat.postMessage` wants a channel ID
and was being handed a name.
"""

from __future__ import annotations

import json
import urllib.parse
from io import BytesIO

import pytest

from ic.tools import comms


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_slack(monkeypatch, replies):
    """Answer each Slack endpoint from `replies`, recording what was sent.

    Records the HTTP method and reads arguments from wherever they actually
    are. An earlier version assumed every call was a JSON POST and decoded
    `req.data` blindly, so it happily passed a `chat.getPermalink` that Slack
    rejects with `invalid_arguments` — that one is a GET, and the bug survived
    to a live run because the fake did not care.
    """
    sent: list[dict] = []

    def urlopen(req, timeout=None):
        url, _, query = req.full_url.partition("?")
        endpoint = url.rsplit("/", 1)[-1]
        if req.data:
            body = json.loads(req.data.decode())
        else:
            body = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        sent.append({"endpoint": endpoint, "body": body,
                     "method": req.get_method()})
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


# ── where the message actually went ───────────────────────────────────
#
# The run said "brief posted to #C0C1C6YDTDH" and that was the whole story.
# Nobody watching a demo can do anything with a channel id, and the person who
# built it could not say where to look either. A post that cannot be found is
# indistinguishable from one that never happened.


def test_a_post_returns_a_link_a_human_can_open(monkeypatch):
    sent = fake_slack(monkeypatch, {
        "chat.postMessage": {"ok": True, "ts": "1727villain.0001",
                             "channel": "C123"},
        "chat.getPermalink": {
            "ok": True,
            "permalink": "https://argus.slack.com/archives/C123/p1727000000001",
        },
    })
    result = comms.slack_post("C123", "the brief")
    assert result.ok
    assert result.data["permalink"].startswith("https://")
    assert any(s["endpoint"] == "chat.getPermalink" for s in sent)


def test_the_permalink_request_uses_the_timestamp_slack_returned(monkeypatch):
    sent = fake_slack(monkeypatch, {
        "chat.postMessage": {"ok": True, "ts": "1727000000.0001", "channel": "C123"},
        "chat.getPermalink": {"ok": True, "permalink": "https://x.slack.com/p1"},
    })
    comms.slack_post("C123", "the brief")
    ask = next(s for s in sent if s["endpoint"] == "chat.getPermalink")
    assert ask["body"]["message_ts"] == "1727000000.0001"
    assert ask["body"]["channel"] == "C123"
    # Slack serves this one over GET. Posting a JSON body to it returns
    # `invalid_arguments`, which is what happened live.
    assert ask["method"] == "GET"


def test_a_post_still_succeeds_when_the_permalink_lookup_fails(monkeypatch):
    # The message was delivered. Failing the whole action because the
    # convenience link could not be fetched would report a false negative about
    # something that actually happened.
    fake_slack(monkeypatch, {
        "chat.postMessage": {"ok": True, "ts": "1727000000.0001", "channel": "C123"},
        "chat.getPermalink": {"ok": False, "error": "message_not_found"},
    })
    result = comms.slack_post("C123", "the brief")
    assert result.ok
    assert result.data.get("permalink") is None


def test_a_rehearsed_post_offers_no_link(monkeypatch):
    # Nothing was sent anywhere, so there is nowhere to point.
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    result = comms.slack_post("C123", "the brief", rehearse=True)
    assert result.rehearsed
    assert result.data.get("permalink") is None


# ── a message nobody is in the room for ───────────────────────────────
#
# Reported live: "it says the message was sent, it wasn't." It was — to a
# channel created seconds earlier that the person watching had never joined.
# The post was real, the permalink resolved, and there was still nobody there
# to read it, which for the person in front of the screen is the same as
# nothing having happened.


def test_an_existing_channel_can_be_named_instead_of_creating_one(monkeypatch):
    # The reliable fix for a demo: post where people already are.
    monkeypatch.setenv("ARGUS_SLACK_CHANNEL", "#ops")
    assert comms.target_channel() == "ops"


def test_no_configured_channel_means_one_per_incident(monkeypatch):
    monkeypatch.delenv("ARGUS_SLACK_CHANNEL", raising=False)
    assert comms.target_channel() is None


def test_a_created_channel_invites_the_people_who_should_see_it(monkeypatch):
    sent = fake_slack(monkeypatch, {
        "conversations.create": {"ok": True, "channel": {"id": "C1"}},
        "conversations.invite": {"ok": True},
    })
    monkeypatch.setenv("ARGUS_SLACK_INVITE", "U123,U456")
    result = comms.slack_open_channel("incident-1")
    assert result.ok
    invite = next(s for s in sent if s["endpoint"] == "conversations.invite")
    assert invite["body"]["users"] == "U123,U456"
    assert invite["body"]["channel"] == "C1"


def test_a_failed_invite_does_not_fail_the_channel(monkeypatch):
    # The channel exists and the brief can still be posted to it.
    fake_slack(monkeypatch, {
        "conversations.create": {"ok": True, "channel": {"id": "C1"}},
        "conversations.invite": {"ok": False, "error": "already_in_channel"},
    })
    monkeypatch.setenv("ARGUS_SLACK_INVITE", "U123")
    assert comms.slack_open_channel("incident-1").ok


def test_nobody_to_invite_means_no_invite_call(monkeypatch):
    sent = fake_slack(monkeypatch, {
        "conversations.create": {"ok": True, "channel": {"id": "C1"}},
    })
    monkeypatch.delenv("ARGUS_SLACK_INVITE", raising=False)
    comms.slack_open_channel("incident-1")
    assert not any(s["endpoint"] == "conversations.invite" for s in sent)


def test_the_permalink_uses_the_id_slack_resolved_not_the_name(monkeypatch):
    # chat.postMessage accepts "#ops"; chat.getPermalink does not, and answers
    # channel_not_found. The post response carries the resolved id, so a brief
    # sent to a named channel still comes back with a link.
    sent = fake_slack(monkeypatch, {
        "chat.postMessage": {"ok": True, "ts": "1727000000.0001", "channel": "C999"},
        "chat.getPermalink": {"ok": True, "permalink": "https://x.slack.com/p1"},
    })
    result = comms.slack_post("all-noctus", "the brief")
    ask = next(s for s in sent if s["endpoint"] == "chat.getPermalink")
    assert ask["body"]["channel"] == "C999"
    assert result.data["permalink"] == "https://x.slack.com/p1"
