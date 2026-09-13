"""What actually lands in the channel.

A responder opens Slack on a phone. The post has to say what happened, where,
what is established, what is advisory and what nobody knows — and it has to be
legible without a monospace terminal, which the plain brief was written for.
"""

from ic.reason import Incident, build_picture
from ic.report import slack_report
from tests.test_reason import evidence


def report(description="structure fire at 1001 Van Ness Avenue, smoke showing",
           summary="A structure fire is reported."):
    incident = Incident("IC-1847", "1001 Van Ness Avenue", description)
    picture = build_picture(incident, evidence())
    return slack_report(incident, "HIGH PRIORITY", "FIRE", picture, summary)


def test_it_leads_with_priority_and_address():
    text = report()
    head = text.splitlines()[0]
    assert "HIGH PRIORITY" in head and "FIRE" in head
    assert "1001 Van Ness Avenue" in text


def test_the_incident_number_is_present():
    assert "IC-1847" in report()


def test_the_model_summary_leads_the_body():
    text = report(summary="A structure fire is reported at a 13-storey building.")
    assert "13-storey" in text


def test_established_facts_are_separated_from_advisory_ones():
    text = report()
    assert "ESTABLISHED" in text
    assert "ADVISORY" in text


def test_open_questions_are_carried():
    text = report()
    assert "NOT ESTABLISHED" in text or "OPEN" in text
    assert "persons_trapped" in text


def test_every_established_line_names_where_it_came_from():
    # A claim without its source is the thing this whole system refuses to
    # produce. It must not become one on the way into Slack.
    text = report()
    body = text.split("*ESTABLISHED*", 1)[1].split("*ADVISORY*", 1)[0]
    lines = [l for l in body.strip().splitlines() if l.strip()]
    for bullet, citation in zip(lines[::2], lines[1::2]):
        assert bullet.strip().startswith("•"), bullet
        assert citation.strip().startswith("_"), f"no source under: {bullet}"


def test_it_does_not_leak_the_callers_account_of_who_is_inside():
    # Unlike the public ntfy alert, Slack is authenticated, so the caller's
    # account belongs here. This pins the opposite of the alert's rule so the
    # two cannot be confused for each other later.
    text = report("structure fire, my father is inside, he is 81")
    assert "father" in text


def test_it_is_short_enough_to_read_on_a_phone():
    assert len(report()) < 3000


def test_the_callers_own_words_are_quoted_not_filed_as_advice():
    # The verbatim report was taking a slot in ADVISORY, where it crowded out
    # the things Argus actually worked out — and reading the call back as though
    # it were a recommendation is the wrong shape anyway.
    text = report("structure fire, smoke showing, someone may still be inside")
    advisory = text.split("*ADVISORY*", 1)[1]
    assert "smoke showing, someone may still be inside" not in advisory
    assert ">" in text.split("*ESTABLISHED*", 1)[0]


def test_updates_are_quoted_with_the_original_call():
    incident = Incident("IC-1847", "1001 Van Ness Avenue",
                        "structure fire, smoke showing")
    object.__setattr__(incident, "updates", ("caller now says the roof is sagging",))
    picture = build_picture(incident, evidence())
    text = slack_report(incident, "HIGH PRIORITY", "FIRE", picture, None)
    assert "roof is sagging" in text.split("*ESTABLISHED*", 1)[0]


def test_a_long_location_does_not_swallow_the_post():
    text = report()
    for line in text.splitlines():
        assert len(line) < 160, f"line too long to read on a phone: {line}"


# ── the link has to survive into the payload ──────────────────────────


def test_a_tool_call_carries_its_link_into_the_payload():
    # The console reads this to show where the message went. `data` itself is
    # not serialised — it holds Places and Findings that are not JSON and have
    # no business in the payload — so the link is lifted out explicitly.
    from ic.tools.base import ToolCall, ToolResult
    call = ToolCall(
        "slack.post_message", {},
        ToolResult(True, "posted", data={"permalink": "https://x.slack.com/p1"}),
        12.0,
    )
    assert call.to_dict()["link"] == "https://x.slack.com/p1"


def test_an_alert_carries_the_page_you_can_read_it_on():
    from ic.tools.base import ToolCall, ToolResult
    call = ToolCall(
        "ntfy.alert", {},
        ToolResult(True, "delivered", data={"read_at": "https://ntfy.sh/argus-x"}),
        12.0,
    )
    assert call.to_dict()["link"] == "https://ntfy.sh/argus-x"


def test_a_call_with_nowhere_to_point_has_no_link():
    from ic.tools.base import ToolCall, ToolResult
    call = ToolCall("maps.geocode", {}, ToolResult(True, "found", data={"located": object()}), 1.0)
    assert call.to_dict()["link"] is None
