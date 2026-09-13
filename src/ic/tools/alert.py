"""Pushing an alert to responders, with no credentials at all.

Slack and mail need a token from somebody's workspace, which means that until
somebody supplies one they rehearse — and an agent that only ever *prepares*
actions is a demo rather than a system. This closes that gap: ntfy.sh accepts
an unauthenticated publish to a topic and delivers a real push notification to
any device subscribed to it. No account, no token, no setup. It is genuinely
delivered, so it is never counted as rehearsed.

The thing to be careful about
-----------------------------
An ntfy topic is public and unauthenticated. Anyone who knows the topic name
can read everything published to it, and there is no way to take a message
back. That is fine for a short operational alert — an incident number, a type,
a street — and entirely wrong for a full brief.

So this deliberately sends less than it knows. The caller's account never goes
out over it: "my father is inside, he's 81" identifies a specific person at a
specific address on a channel anyone can subscribe to, and no operational
benefit justifies that. The full brief travels by Slack and mail, which are
authenticated, and the alert carries only enough for a responder to know an
incident exists and open the real one.

Topics are generated per install rather than shared, because a fixed default
would put every user of this software on the same public channel.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
import urllib.error
import urllib.request
from typing import Sequence

from ic.tools.base import Source, ToolResult

NTFY = "https://ntfy.sh"
TIMEOUT_S = 15.0
SOURCE = Source("ntfy.sh", "https://ntfy.sh")

# Short enough to read on a lock screen, long enough to act on.
MAX_BODY = 280


def default_topic() -> str:
    """A fresh, unguessable topic. Never a shared constant."""
    return f"argus-{secrets.token_urlsafe(12)}"


# Where this install's topic is remembered. A topic has to be stable: ntfy
# rate-limits anonymous publishing and treats a new topic per run as exactly
# the abuse that limit exists for, and a judge who subscribed on their phone
# should not have to re-subscribe for the next incident.
TOPIC_FILE = Path(".cache/ntfy-topic")


def configured_topic() -> str:
    """This install's topic: the environment, then the remembered one, then new."""
    from_env = os.environ.get("ARGUS_NTFY_TOPIC")
    if from_env:
        return from_env
    try:
        if TOPIC_FILE.exists():
            remembered = TOPIC_FILE.read_text().strip()
            if remembered:
                return remembered
    except OSError:
        pass
    topic = default_topic()
    try:
        TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOPIC_FILE.write_text(topic)
    except OSError:
        pass  # an unwritable cache is not a reason to fail the alert
    return topic


# HTTP headers are latin-1 by specification, and this project writes em dashes
# and middle dots everywhere. Left alone, urllib raises before the request
# leaves the machine and the failure reads as "not delivered" in 0 ms, which
# looks exactly like a network problem and is not one.
_TRANSLITERATE = {
    "\u2014": "-", "\u2013": "-", "\u2012": "-",   # dashes
    "\u00b7": "-", "\u2022": "-",                   # middle dot, bullet
    "\u2018": "'", "\u2019": "'",                   # single quotes
    "\u201c": '"', "\u201d": '"',                   # double quotes
    "\u2026": "...",
}


def ascii_header(value: str) -> str:
    """A header value that will survive latin-1, with the meaning kept."""
    for fancy, plain in _TRANSLITERATE.items():
        value = value.replace(fancy, plain)
    # Anything still outside latin-1 is dropped rather than allowed to raise.
    return value.encode("latin-1", "ignore").decode("latin-1")


def alert_body(headline: str, address: str, facts: Sequence[str],
               caller_account: str | None = None) -> str:
    """The short form that is safe to publish on a public channel.

    `caller_account` is accepted and deliberately discarded. It is here as a
    signature so that a future caller passing it in cannot quietly succeed —
    what a frightened person said about who is inside a building does not go
    out over a channel anyone can subscribe to.
    """
    parts = [address, *facts]
    body = " · ".join(p for p in parts if p)
    return body[:MAX_BODY]


def responder_alert(topic: str, headline: str, body: str,
                    priority: str = "urgent",
                    rehearse: bool = False) -> ToolResult:
    """Publish an alert. Delivered for real, or reported as failed.

    `rehearse` composes the alert without sending it. The evaluation harness
    uses it: a hundred test incidents firing a hundred real pushes at a free
    third-party service is not a test suite, it is a denial-of-service with
    good intentions.
    """
    if rehearse:
        return ToolResult(
            True, f"alert prepared for ntfy.sh/{topic} (rehearsed)",
            data={"topic": topic}, rehearsed=True, sources=(SOURCE,),
        )

    request = urllib.request.Request(
        f"{NTFY}/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": ascii_header(headline),
            "Priority": priority,
            "Tags": "rotating_light",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = (
            "rate limited by ntfy.sh — anonymous publishing is throttled per "
            "address; the alert was not delivered"
            if exc.code == 429 else f"HTTP {exc.code}: {exc.reason}"
        )
        return ToolResult(False, "alert not delivered", sources=(SOURCE,),
                          error=detail)
    except Exception as exc:  # noqa: BLE001 - a failed alert is data, not a crash
        return ToolResult(
            False, "alert not delivered", sources=(SOURCE,),
            error=f"{type(exc).__name__}: {exc}",
        )

    delivery_id = payload.get("id", "?")
    return ToolResult(
        True,
        f"delivered to ntfy.sh/{topic} (id {delivery_id})",
        data={"topic": topic, "id": delivery_id,
              "read_at": f"{NTFY}/{topic}"},
        sources=(Source("ntfy.sh", f"{NTFY}/{topic}"),),
    )
