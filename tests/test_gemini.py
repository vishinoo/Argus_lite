"""A second model behind the same grounding check.

The point of adding Gemini is not redundancy. It is that the check which makes
a model safe to use here does not know or care which model wrote the text — it
compares the output against the evidence. A second provider passing through the
identical gate is the demonstration.
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from ic import summarise as S


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_http(monkeypatch, replies):
    """Answer each URL from `replies`, keyed by a substring of the URL."""
    seen = []

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        seen.append(url)
        for key, payload in replies.items():
            if key in url:
                return FakeResponse(json.dumps(payload).encode())
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(S.urllib.request, "urlopen", urlopen)
    return seen


LIST = {"models": [
    {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-flash-newest", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-pro-newest", "supportedGenerationMethods": ["generateContent"]},
]}


def reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


# ── model discovery ───────────────────────────────────────────────────


def test_a_usable_model_is_discovered_rather_than_hardcoded(monkeypatch, tmp_path):
    # Model names churn. Asking which ones exist is more durable than
    # remembering one that was current when this was written.
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    fake_http(monkeypatch, {"/models?": LIST})
    assert S.discover_gemini_model("key") == "models/gemini-flash-newest"


def test_a_model_that_cannot_generate_is_not_chosen(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    fake_http(monkeypatch, {"/models?": LIST})
    assert "embedding" not in S.discover_gemini_model("key")


def test_the_discovered_model_is_remembered(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    seen = fake_http(monkeypatch, {"/models?": LIST})
    S.discover_gemini_model("key")
    S.discover_gemini_model("key")
    assert len(seen) == 1


def test_an_explicit_model_overrides_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    monkeypatch.setenv("GEMINI_MODEL", "models/my-choice")
    assert S.discover_gemini_model("key") == "models/my-choice"


# ── the same gate ─────────────────────────────────────────────────────


def picture():
    from ic.schema import Assessment, Picture
    from ic.tools.base import Source
    osm = Source("OpenStreetMap")
    return Picture(situation=(
        Assessment.verified("building", "storeys: 13", "record", osm),
        Assessment.verified("location", "1001 Van Ness Avenue", "geocoder", osm),
    ))


def test_a_grounded_gemini_summary_is_used(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    fake_http(monkeypatch, {
        "/models?": LIST,
        "generateContent": reply("The building at 1001 Van Ness Avenue has 13 storeys."),
    })
    result = S.summarise(picture(), "structure fire")
    assert result.source == "gemini"
    assert "13 storeys" in result.text


def test_an_ungrounded_gemini_summary_is_rejected_exactly_like_claude(monkeypatch, tmp_path):
    # The whole reason a second provider is safe to add.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    fake_http(monkeypatch, {
        "/models?": LIST,
        "generateContent": reply("The 40-storey tower is fully involved."),
    })
    result = S.summarise(picture(), "structure fire")
    assert result.source == "template"
    assert "40" in (result.rejected or "")


def test_claude_is_preferred_when_both_keys_are_present(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini")
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")
    # No HTTP is stubbed, so a Gemini call would raise and fall to template
    # with a rejection note. Claude's own failure path is the same shape, so
    # assert on which provider was attempted instead.
    assert S.chosen_provider() == "claude"


def test_gemini_is_used_when_only_it_is_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini")
    assert S.chosen_provider() == "gemini"


def test_no_key_means_no_provider(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert S.chosen_provider() is None


def test_a_gemini_failure_falls_back_rather_than_crashing(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "model")

    def boom(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(S.urllib.request, "urlopen", boom)
    result = S.summarise(picture(), "structure fire")
    assert result.source == "template" and result.rejected


# ── truncation is a rejection, not a summary ──────────────────────────
#
# Found live. gemini-2.5-flash is a thinking model and its thinking tokens
# count against maxOutputTokens, so the budget was spent before the visible
# text finished and the brief got "...social facility at". Half a sentence
# presented as a summary is worse than the deterministic one.


def test_thinking_is_turned_off_for_a_restatement(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "m")
    monkeypatch.setenv("GEMINI_MODEL", "models/x")
    sent = []

    def urlopen(req, timeout=None):
        sent.append(json.loads(req.data.decode()))
        return FakeResponse(json.dumps(reply("ok")).encode())

    monkeypatch.setattr(S.urllib.request, "urlopen", urlopen)
    S._gemini_summary("prompt", "key")
    config = sent[0]["generationConfig"]
    assert config.get("thinkingConfig", {}).get("thinkingBudget") == 0


def test_a_truncated_response_is_rejected(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setenv("GEMINI_MODEL", "models/x")
    monkeypatch.setattr(S, "GEMINI_MODEL_CACHE", tmp_path / "m")

    cut = {"candidates": [{"content": {"parts": [{"text": "A fire is reported at"}]},
                           "finishReason": "MAX_TOKENS"}]}
    monkeypatch.setattr(S.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(json.dumps(cut).encode()))
    result = S.summarise(picture(), "structure fire")
    assert result.source == "template"
    assert "truncat" in (result.rejected or "").lower()
