"""The actions: Slack, mail, calendar.

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

The calendar is the exception worth noting: rehearsal still produces a real
`.ics` file, because a calendar invitation is a document, and a document you
can open is better evidence than a log line saying one was created.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
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
    return ToolResult(True, f"brief posted to #{channel}",
                      sources=(Source("Slack", "https://slack.com"),))


# ------------------------------------------------------------------- mail


def send_mail(to: str, subject: str, body: str,
              rehearse: bool = False) -> ToolResult:
    user = None if rehearse else os.environ.get("SMTP_USER")
    password = None if rehearse else os.environ.get("SMTP_PASS")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))

    if not (user and password):
        path = _rehearsal_path("mail", subject)
        path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n")
        return ToolResult(
            True, f"brief prepared for {to} (rehearsed → {path})",
            data={"path": str(path)}, rehearsed=True, sources=(LOCAL,),
        )

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    return ToolResult(True, f"brief sent to {to}",
                      sources=(Source("SMTP", host),))


# --------------------------------------------------------------- calendar


def schedule_briefing(
    title: str, attendees: tuple[str, ...], minutes_from_now: int = 30,
    duration_min: int = 20,
) -> ToolResult:
    """A real .ics either way — a file you can open beats a log line."""
    start = datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
    end = start + timedelta(minutes=duration_min)
    stamp = "%Y%m%dT%H%M%SZ"
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Argus Incident Commander//EN",
        "BEGIN:VEVENT",
        f"UID:{abs(hash((title, start.isoformat())))}@argus",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(stamp)}",
        f"DTSTART:{start.strftime(stamp)}", f"DTEND:{end.strftime(stamp)}",
        f"SUMMARY:{title}",
        *[f"ATTENDEE;CN={a}:mailto:{a}" for a in attendees],
        "END:VEVENT", "END:VCALENDAR",
    ])
    path = _rehearsal_path("briefing", title).with_suffix(".ics")
    path.write_text(ics)
    when = start.strftime("%H:%M UTC")
    return ToolResult(
        True, f"briefing at {when} ({path})",
        data={"path": str(path), "start": start.isoformat()},
        rehearsed=True, sources=(LOCAL,),
    )
