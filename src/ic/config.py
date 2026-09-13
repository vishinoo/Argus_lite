"""Credentials, and an honest account of which integrations are actually live.

The demo runs without any of this. But "runs without credentials" and "is a
simulation" are different claims, and the difference has to be visible: an
action that was rehearsed says so in the transcript, in the dashboard, and in
`ic check`.

Reading a local `.env` is a convenience with a sharp edge — a file full of
secrets is easy to commit by accident — so `.env` is gitignored and this never
prints a value, only whether one is present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path(".env")


def load_env(path: Path = ENV_FILE) -> int:
    """Load KEY=value lines into the environment. Existing values win."""
    if not path.exists():
        return 0
    loaded = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


@dataclass(frozen=True)
class Integration:
    name: str
    live: bool
    detail: str
    how: str


def _summary_provider() -> str | None:
    from ic.summarise import chosen_provider

    return chosen_provider()


def status() -> tuple[Integration, ...]:
    """What is live, what is rehearsing, and what to do about it."""
    slack = os.environ.get("SLACK_BOT_TOKEN")

    return (
        Integration(
            "Maps / geocoding", True, "live — OpenStreetMap Nominatim, no key needed", ""
        ),
        Integration(
            "Weather", True, "live — Open-Meteo, no key needed", ""
        ),
        Integration(
            "Responder alert", True,
            "live — ntfy.sh push, delivered for real with no credentials", "",
        ),
        Integration(
            "OpenStreetMap survey", True, "live — Overpass, no key needed", ""
        ),
        Integration(
            "Public search", True, "live — Wikipedia, no key needed", ""
        ),
        Integration(
            "Slack", bool(slack),
            "live — will create a real channel and post" if slack
            else "REHEARSING — composes the message, does not send",
            "api.slack.com/apps → Create New App → From a manifest, paste "
            "slack-app-manifest.yaml, Install to Workspace, then put the "
            "xoxb- token in .env as SLACK_BOT_TOKEN",
        ),
        Integration(
            "Summary prose", bool(_summary_provider()),
            f"live — written by {_summary_provider()}, checked against the evidence"
            if _summary_provider() else
            "deterministic template — no model key set",
            "set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env; either way the "
            "summary is checked against the evidence and rejected if it "
            "introduces anything",
        ),
    )


def live_count() -> tuple[int, int]:
    items = status()
    return sum(1 for i in items if i.live), len(items)
