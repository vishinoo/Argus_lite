"""The brief as it lands in Slack.

`Brief.render` was written for a terminal: fixed columns, a monospace grid,
citations on their own indented line. On a phone that wraps into porridge, and
the phone is where a responder reads it.

This renders the same picture as Slack mrkdwn — bold where the eye should go,
italic sources, one bullet per fact — and keeps the three categories a reader
has to be able to tell apart at a glance:

    ESTABLISHED     an external record says so, and the record is named
    ADVISORY        Argus worked it out, or the caller said it
    NOT ESTABLISHED nobody knows, including the questions that decide it

Unlike the public ntfy alert, Slack is authenticated, so the caller's account
of who is inside belongs here. That is the opposite of the alert's rule, and
deliberately so: the alert says an incident exists, this says what is known.
"""

from __future__ import annotations

from ic.schema import Picture, Status

# A responder is reading this on a lock screen at arm's length. Past a certain
# length nobody reaches the open questions, which are the point.
_MAX_PER_SECTION = 6

# Nominatim returns the whole postal hierarchy — country, postcode and all —
# and a line that long wraps three times on a phone and buries the next fact.
_MAX_VALUE = 110

# The call itself. It belongs at the top in the caller's own words, not filed
# among the things Argus worked out.
_VERBATIM = ("report",)


def _clip(text: str, limit: int = _MAX_VALUE) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;") + "…"


def _is_verbatim(field: str) -> bool:
    return field in _VERBATIM or field.startswith("update ")


def _line(assessment) -> str:
    value = _clip(assessment.value or "—")
    source = assessment.source.label if assessment.source else assessment.evidence
    return f"• *{assessment.field}* — {value}\n   _{_clip(source, 120)}_"


def slack_report(incident, priority: str, headline: str,
                 picture: Picture | None, summary: str | None = None) -> str:
    """The incident as a Slack post."""
    out: list[str] = [f":rotating_light: *{priority} — {headline}*",
                      f"{incident.address}  ·  `{incident.incident_id}`"]

    if summary:
        out.append("")
        out.append(summary)

    if picture is None:
        return "\n".join(out)

    # The call, in the caller's words, including anything said since.
    spoken = [a for a in picture.all if _is_verbatim(a.field) and a.value]
    if spoken:
        out.append("")
        out += [f"> {_clip(a.value, 220)}" for a in spoken]

    established = [a for a in picture.all if a.status is Status.VERIFIED and a.value]
    advisory = [a for a in picture.all
                if a.status in (Status.INFERRED, Status.REPORTED)
                and a.value and not _is_verbatim(a.field)]
    contradicted = [a for a in picture.all if a.status is Status.CONTRADICTED]
    unknown = [a for a in picture.all if a.status is Status.UNKNOWN]

    if established:
        out += ["", "*ESTABLISHED*"]
        out += [_line(a) for a in established[:_MAX_PER_SECTION]]

    if contradicted:
        out += ["", "*SOURCES DISAGREE*"]
        out += [_line(a) for a in contradicted]

    if advisory:
        out += ["", "*ADVISORY* — worked out, or reported by the caller"]
        out += [_line(a) for a in advisory[:_MAX_PER_SECTION]]

    if unknown:
        out += ["", "*NOT ESTABLISHED* — no source can settle these before arrival"]
        out.append("• " + ", ".join(a.field for a in unknown))

    out += ["", "_Advisory only. Argus does not dispatch._"]
    return "\n".join(out)
