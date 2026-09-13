"""The action that touches someone else: Slack.

These are the only tools that touch someone else. Everything before them reads
the world; these change it, which means they need a different standard.

When credentials are present they do the real thing. When they are not, they
run in *rehearsal*: the message is composed in full, recorded in the
transcript, written to disk where you can read it — and not delivered. The
result says `rehearsed`, the dashboard prints `rehearsed`, and the evaluation
counts rehearsed actions separately from delivered ones.

That distinction is deliberate and load-bearing. The easy way to demo an agent
is a stub that returns success, and the failure mode is a room full of people
believing an email went to a fire chief when nothing left the laptop. If this
agent says it sent something, it sent it.

A post also comes back with a permalink. "Posted to #C0C1C6YDTDH" is true and
useless — nobody watching can act on a channel id, and a message nobody can
find is indistinguishable from one that was never sent.

Mail and a calendar invitation used to live here too. Both rehearsed on every
run anybody actually did, which meant two of the integrations on the dashboard
were permanently reporting that they had not done anything. They are in git if
they are wanted back.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from ic.tools.base import Source, ToolResult

SLACK_API = "https://slack.com/api"
TIMEOUT_S = 20.0

OUT_DIR = Path("out")
LOCAL = Source("rehearsed locally", None)


def _rehearsal_path(kind: str, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-")[:60]
    return OUT_DIR / f"{kind}-{safe}"


def channel_name(incident_id: str, address: str) -> str:
    """Slack's rules, applied once: lowercase, no spaces, 80 chars."""
    stem = re.sub(r"[^a-z0-9]+", "-", f"{incident_id} {address}".lower()).strip("-")
    return f"incident-{stem}"[:80]


# ------------------------------------------------------------------ slack


def target_channel() -> str | None:
    """An existing channel to post into, instead of opening one per incident.

    A fresh channel is correct for real operations and wrong for a demo: the
    bot creates it, posts, and the person watching was never a member, so a
    delivered message looks like nothing happened. Naming a channel people are
    already in makes the post land where they are looking.
    """
    name = (os.environ.get("ARGUS_SLACK_CHANNEL") or "").strip()
    return name.lstrip("#") or None


def _invite_list() -> str:
    return ",".join(
        u.strip() for u in (os.environ.get("ARGUS_SLACK_INVITE") or "").split(",")
        if u.strip()
    )


def slack_open_channel(name: str, rehearse: bool = False) -> ToolResult:
    token = None if rehearse else os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        path = _rehearsal_path("slack-channel", name)
        path.write_text(f"would create #{name}\n")
        return ToolResult(
            True, f"#{name} (rehearsed — no SLACK_BOT_TOKEN)",
            data={"channel": name, "id": None}, rehearsed=True, sources=(LOCAL,),
        )

    payload = _slack("conversations.create", token, {"name": name})

    if not payload.get("ok"):
        # A channel for this incident already exists — which happens on the
        # second run of any demo, since a rehearsal usually precedes the real
        # one. Reuse it rather than failing; the incident is the same incident.
        if payload.get("error") == "name_taken":
            existing = _find_channel(token, name)
            if existing:
                return ToolResult(
                    True, f"#{name} — existing channel reused",
                    data={"channel": name, "id": existing},
                    sources=(Source("Slack", f"slack://channel/{existing}"),),
                )
        return ToolResult(False, f"Slack refused: {payload.get('error')}",
                          error=str(payload.get("error")))

    cid = payload["channel"]["id"]

    # Put somebody in the room. A channel created seconds ago has exactly one
    # member — the bot — and a brief posted to an empty room is indistinguishable
    # from one never sent.
    invited = _invite_list()
    if invited:
        try:
            _slack("conversations.invite", token, {"channel": cid, "users": invited})
        except Exception:  # noqa: BLE001 - the channel exists either way
            pass

    return ToolResult(True, f"#{name} created", data={"channel": name, "id": cid},
                      sources=(Source("Slack", f"slack://channel/{cid}"),))


def _slack(method: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{SLACK_API}/{method}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode())


def _find_channel(token: str, name: str) -> str | None:
    """The id of an existing channel with this name, if there is one."""
    payload = _slack("conversations.list", token,
                     {"limit": 1000, "exclude_archived": True})
    if not payload.get("ok"):
        return None
    for channel in payload.get("channels", []):
        if channel.get("name") == name:
            return channel.get("id")
    return None


def slack_post(channel: str, text: str, rehearse: bool = False) -> ToolResult:
    """Post to a channel. `channel` must be the id Slack assigned, not the name."""
    token = None if rehearse else os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        path = _rehearsal_path("slack-post", channel)
        path.write_text(text)
        return ToolResult(
            True, f"brief prepared for #{channel} (rehearsed → {path})",
            data={"path": str(path)}, rehearsed=True, sources=(LOCAL,),
        )

    body = json.dumps({"channel": channel, "text": text}).encode()
    req = urllib.request.Request(
        f"{SLACK_API}/chat.postMessage", data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        payload = json.loads(r.read().decode())
    if not payload.get("ok"):
        return ToolResult(False, f"Slack refused: {payload.get('error')}",
                          error=str(payload.get("error")))

    # Where it landed, in a form a human can open. "posted to #C0C1C6YDTDH" is
    # true and useless: nobody watching can act on a channel id, and a post
    # nobody can find is indistinguishable from one that never happened.
    # postMessage accepts "#ops"; getPermalink does not. The response carries
    # the id Slack resolved, which is the one that works.
    resolved = payload.get("channel") or channel
    permalink = _permalink(token, resolved, payload.get("ts"))
    where = permalink or f"#{channel}"
    return ToolResult(
        True, f"brief posted to {where}",
        data={"channel": resolved, "ts": payload.get("ts"), "permalink": permalink},
        sources=(Source("Slack", permalink or "https://slack.com"),),
    )


def _permalink(token: str, channel: str, ts: str | None) -> str | None:
    """A link straight to the message, or None.

    Never raises and never fails the post. The message was delivered; losing
    the convenience link is not a reason to report that it was not.
    """
    if not ts:
        return None
    try:
        payload = _slack_get("chat.getPermalink", token,
                             {"channel": channel, "message_ts": ts})
    except Exception:  # noqa: BLE001 - a missing link is not a failed delivery
        return None
    return payload.get("permalink") if payload.get("ok") else None


def _slack_get(method: str, token: str, params: dict) -> dict:
    """Slack serves some methods over GET only.

    `chat.getPermalink` is one of them: handed a JSON body it answers
    `invalid_arguments` and names both fields as missing, which reads exactly
    like a bug in the caller rather than in the verb.
    """
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{SLACK_API}/{method}?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode())
