"""The loop: observe, investigate, reason, decide, act, document.

The agent's shape is deliberately boring, because the interesting decisions
are in what it refuses to do.

**It does not act until told.** Investigation and reasoning always run; the
actions — the responder alert and Slack — happen only when `execute` is set. The
dispatcher reads the brief and decides. An agent that opens an incident
channel the instant a sentence is typed is not decision support, it is a
liability with a webhook.

**It will not act on an unverified location, even when told.** If the address
did not resolve, `execute` is overridden and the run stops with a request for
human confirmation. This is the one place the agent overrules its operator,
and it is the right place: every action downstream — the channel name, the
brief, the people notified — would be about somewhere that may not exist.

**Everything is written down.** The transcript holds every tool call, its
latency, its outcome and its sources, whether the call worked or not. The run
is reconstructable afterwards from the record rather than from the summary the
agent wrote about itself.

Investigation is injected rather than hard-wired, so the same agent runs
against live APIs in a demo and against fixtures in the evaluation harness.
The reasoning under test is then identical to the reasoning being demonstrated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from ic.brief import Brief, Priority
from ic.reason import Evidence, Incident, synthesize
from ic.tools import alert, comms
from ic.tools.base import Source, ToolResult, Transcript


class Investigator(Protocol):
    """Gathers the evidence. Live against real APIs, or scripted for tests."""

    def gather(self, incident: Incident, transcript: Transcript) -> Evidence: ...


@dataclass
class RunResult:
    incident: Incident
    brief: Brief
    transcript: Transcript
    executed: bool
    refused: str | None = None
    elapsed_s: float = 0.0
    artifacts: list[str] = field(default_factory=list)

    @property
    def actions(self) -> list:
        return list(self.transcript.actions())

    @property
    def delivered(self) -> int:
        return sum(1 for a in self.actions if a.result.delivered)

    @property
    def rehearsed(self) -> int:
        return sum(1 for a in self.actions if a.result.rehearsed)

    def to_dict(self) -> dict:
        return {
            "incident": {
                "id": self.incident.incident_id,
                "address": self.incident.address,
                "description": self.incident.description,
                "updates": list(self.incident.updates),
            },
            "brief": self.brief.to_dict(),
            "transcript": self.transcript.to_dict(),
            "executed": self.executed,
            "refused": self.refused,
            "elapsed_s": round(self.elapsed_s, 2),
            "actions": {"delivered": self.delivered, "rehearsed": self.rehearsed},
            "artifacts": self.artifacts,
        }


class IncidentCommander:
    def __init__(
        self,
        investigator: Investigator,
        alert_topic: str | None = None,
        deliver: bool = True,
    ) -> None:
        self._investigator = investigator
        self._alert_topic = alert_topic or alert.configured_topic()
        self._deliver = deliver
        """False makes every outward action rehearse, whatever credentials
        exist. The evaluation harness runs this way."""

    def run(
        self, incident: Incident, execute: bool = False,
        transcript: Transcript | None = None,
    ) -> RunResult:
        started = time.perf_counter()
        transcript = transcript if transcript is not None else Transcript()

        # observe → investigate
        evidence = self._investigator.gather(incident, transcript)

        # reason
        brief = synthesize(incident, evidence)

        # decide — the one case where the agent overrules the request to act
        refused: str | None = None
        if execute and brief.priority is Priority.UNVERIFIED:
            refused = (
                "location could not be independently verified; the workflow was not "
                "executed and human confirmation is required"
            )
            execute = False

        artifacts: list[str] = []
        if execute:
            artifacts = self._act(incident, brief, transcript)

        return RunResult(
            incident=incident, brief=brief, transcript=transcript,
            executed=execute, refused=refused,
            elapsed_s=time.perf_counter() - started, artifacts=artifacts,
        )

    # -------------------------------------------------------------- acting

    def _act(self, incident: Incident, brief: Brief, t: Transcript) -> list[str]:
        artifacts: list[str] = []
        rendered = brief.render()
        name = comms.channel_name(incident.incident_id, incident.address)

        # The one action that needs no credentials, so it is always real. Short
        # form only: an ntfy topic is public, and the full brief is not for a
        # channel anyone can subscribe to.
        picture = brief.picture
        facts = []
        if picture is not None:
            facts = [
                a.value for a in (picture.situation + picture.approach)
                if a.value and a.field in {"building", "approach"}
            ][:2]
        t.run(
            "ntfy.alert",
            lambda: alert.responder_alert(
                self._alert_topic,
                f"{brief.headline} — {incident.incident_id}",
                alert.alert_body(brief.headline, incident.address, facts),
                rehearse=not self._deliver,
            ),
            topic=self._alert_topic,
        )

        # Readable prose for the Slack post, written by a model where one is
        # configured and checked against the evidence either way. A summary
        # that introduces anything is thrown away, not corrected.
        summary = None
        if picture is not None:
            written = t.run(
                "summary.write",
                lambda: _summary_result(picture, incident.full_text),
                because="brief prose",
            )
            if written.ok and written.data:
                summary = written.data

        # `Brief.render` is laid out for a terminal and wraps into porridge on
        # a phone, which is where this gets read.
        from ic.report import slack_report

        rendered = slack_report(
            incident, brief.priority.value, brief.headline, picture, summary,
        )

        opened = t.run(
            "slack.create_channel",
            lambda: comms.slack_open_channel(name, rehearse=not self._deliver),
            name=name,
        )
        if opened.ok:
            # chat.postMessage resolves ids, not names. Rehearsal has no id, so
            # it falls back to the name it wrote to disk.
            target = (opened.data or {}).get("id") or name
            posted = t.run(
                "slack.post_message",
                lambda: comms.slack_post(target, rendered,
                                         rehearse=not self._deliver),
                channel=target,
            )
            if posted.data and posted.data.get("path"):
                artifacts.append(posted.data["path"])

        return artifacts


def _summary_result(picture, description) -> ToolResult:
    """Summarise, and report which way it went — model or template."""
    from ic.summarise import summarise

    summary = summarise(picture, description)
    return ToolResult(
        True,
        f"{summary.source}: {summary.text[:70]}",
        data=summary.text,
        sources=(Source("summary", None),),
    )


def _survey_result(point) -> ToolResult:
    """Run the single OSM survey and report it as one call in the transcript."""
    from ic.tools.survey import survey

    found = survey(point)
    ok = found.building.ok or found.nearby.ok or found.hazards.ok
    bits = [r.summary for r in (found.building, found.nearby, found.hydrants) if r.ok]
    return ToolResult(
        ok,
        " | ".join(bits) or "survey returned nothing",
        data={"building": found.building, "hazards": found.hazards,
              "exposures": found.exposures, "nearby": found.nearby,
              "hydrants": found.hydrants},
        sources=found.nearby.sources or found.building.sources,
    )


class LiveInvestigator:
    """The real thing: OpenStreetMap geocoding, surroundings and public search."""

    def __init__(self, radius_m: float = 4000.0, hazard_radius_m: float = 300.0) -> None:
        self._radius = radius_m
        self._hazard_radius = hazard_radius_m

    def gather(self, incident: Incident, t: Transcript) -> Evidence:
        from ic.tools import maps, web

        geo = t.run(
            "maps.geocode", lambda: maps.geocode(incident.address),
            address=incident.address,
        )
        if not geo.ok:
            # Nothing further can be about this place, because there is no
            # place. Each skipped lookup is recorded as skipped, not silently
            # omitted, so the transcript shows the decision.
            empty = ToolResult(False, "skipped — location unverified",
                               error="no verified location")
            for tool in ("osm.survey", "weather.current", "web.public_search"):
                t.run(tool, lambda: empty, reason="location unverified")
            return Evidence(geo, empty, empty, empty, empty)

        located = geo.data["located"]
        point = located.point
        context = located.display_name

        # One Overpass request answers building, surroundings and resources.
        # Asking three times — concurrently, no less — is what got the first
        # version rate-limited into 504s. Wikipedia is a different provider, so
        # it runs alongside without competing.
        from concurrent.futures import ThreadPoolExecutor
        from ic.tools.survey import survey

        # Three providers, three threads. They are different services, so
        # running them together costs nothing — unlike the earlier version that
        # fired three requests at Overpass alone and was rate-limited for it.
        from ic.tools import weather

        with ThreadPoolExecutor(max_workers=3) as pool:
            osm = pool.submit(t.run, "osm.survey", lambda: _survey_result(point),
                              point=str(point), because="building, hazards, "
                              "resources, water supply")
            air = pool.submit(t.run, "weather.current",
                              lambda: weather.current(point), point=str(point),
                              because="conditions, approach")
            public = pool.submit(
                t.run, "web.public_search",
                lambda: web.public_search(incident.address, context),
                query=incident.address,
            ).result()
            found = osm.result()
            conditions = air.result()

        parts = found.data or {}
        failed = ToolResult(False, "survey failed", error=found.error)
        return Evidence(
            geo,
            parts.get("building", failed),
            parts.get("hazards", failed),
            parts.get("nearby", failed),
            public,
            weather=conditions,
            hydrants=parts.get("hydrants", failed),
            exposures=parts.get("exposures", failed),
        )
