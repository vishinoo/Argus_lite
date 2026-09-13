"""Prose for the alert, written by a model and then checked against evidence.

There is no language model anywhere else in this system, and that is deliberate:
nothing generates claims, so every claim traces to a retrieved source by
construction rather than by measurement. This module is the one place a model is
allowed near the output, and it is allowed only under three conditions.

**It never sees raw tool output.** The prompt is built from fields Argus has
already established, with each field's state attached. The model is restating,
not researching.

**It is never the source of a fact.** Its job is to turn a table into two
sentences a human can read on a phone. If it adds anything, that is a defect,
not a feature.

**Its output is checked and can be rejected.** Every number and every
distinctive name in the summary must appear in the fields it was given. A
summary that introduces "40 storeys" or "Engine 9" fails the check, is thrown
away, and the deterministic template is used instead. The check is the reason
the model is permitted at all — without it, one hallucinated distance would
undo every guarantee the rest of the system makes.

The template is not a degraded fallback. It is correct by construction and
always available; the model is an improvement in readability that has to earn
its place on every single call.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ic.schema import Picture, Status

MODEL = "claude-opus-5"
MAX_TOKENS = 700

# Gemini, as a second provider behind the identical grounding check. The point
# is not redundancy: it is that the check does not know which model wrote the
# text. Anything that introduces a fact is rejected regardless of who produced
# it, which is what makes adding a provider safe rather than a new risk.
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODEL_CACHE = Path(".cache/gemini-model")
HTTP_TIMEOUT_S = 30.0

SYSTEM = """You write two-sentence situation summaries for emergency responders.

You will be given fields an incident intelligence system has already \
established, each marked VERIFIED (an external record), REPORTED (what the \
caller said, unverified) or INFERRED (worked out from other fields).

Rules, in order of importance:
1. Use only the facts given. Introduce no numbers, names, distances or \
details that do not appear above. If something is not there, it is not known.
2. Keep REPORTED things marked as reported — write "the caller reports" or \
"reportedly". Never state a REPORTED item as fact.
3. Two sentences. Plain words. No preamble, no heading, no bullet points.

Write only the summary."""

# Words that may appear in ordinary prose without being facts about the
# incident. Without this, the grounding check fires on every sentence and the
# model may as well not be there.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "at", "in", "on", "of", "to", "from", "with", "for", "by", "as",
    "this", "that", "these", "those", "it", "its", "has", "have", "had",
    "there", "where", "which", "who", "may", "might", "still", "not", "no",
    "reported", "reportedly", "caller", "callers", "reports", "incident",
    "building", "structure", "fire", "smoke", "someone", "somebody", "people",
    "person", "inside", "nearby", "away", "near", "responding", "response",
    "units", "unit", "crew", "storeys", "storey", "floors", "floor", "km",
    "metres", "meters", "m", "occupancy", "verified", "unverified", "about",
    "approximately", "located", "location", "address", "site", "scene",
}


@dataclass(frozen=True)
class Summary:
    text: str
    source: str
    """The provider that wrote it — "claude" or "gemini" — or "template"."""
    rejected: str | None = None
    """Why a model summary was thrown away, when one was."""

    @property
    def label(self) -> str:
        if self.source in {"claude", "gemini"}:
            return (f"written by {self.source} from established fields, "
                    "checked against them")
        if self.rejected:
            return f"deterministic — model output rejected: {self.rejected}"
        return "deterministic"


def chosen_provider() -> str | None:
    """Which model writes the prose, if any. Claude first where both exist."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return None


def discover_gemini_model(api_key: str) -> str:
    """Ask which models exist rather than remembering one.

    Model names change often enough that a hardcoded default is a latent
    404. `GEMINI_MODEL` overrides; otherwise the first model that can actually
    generate is chosen, preferring a flash variant because this task is
    restating a short table and does not want an expensive model.
    """
    explicit = os.environ.get("GEMINI_MODEL")
    if explicit:
        return explicit
    try:
        if GEMINI_MODEL_CACHE.exists():
            remembered = GEMINI_MODEL_CACHE.read_text().strip()
            if remembered:
                return remembered
    except OSError:
        pass

    url = f"{GEMINI_API}/models?key={urllib.parse.quote(api_key)}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as response:
        payload = json.loads(response.read().decode())

    usable = [
        m["name"] for m in payload.get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    if not usable:
        raise RuntimeError("no Gemini model advertises generateContent")
    chosen = next((m for m in usable if "flash" in m), usable[0])
    try:
        GEMINI_MODEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GEMINI_MODEL_CACHE.write_text(chosen)
    except OSError:
        pass
    return chosen


def _gemini_summary(prompt: str, api_key: str) -> str:
    model = discover_gemini_model(api_key)
    url = f"{GEMINI_API}/{model}:generateContent?key={urllib.parse.quote(api_key)}"
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": MAX_TOKENS,
            "temperature": 0.2,
            # Gemini 2.5 models think by default and those tokens come out of
            # maxOutputTokens, so the budget was being spent before the visible
            # sentence finished. Restating a short table needs no reasoning.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        payload = json.loads(response.read().decode())

    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    candidate = candidates[0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        # Half a sentence presented as a summary is worse than the
        # deterministic one, which at least finishes.
        raise RuntimeError("response truncated at the token limit")
    parts = (candidate.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()


def _claude_summary(prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        # Restating a table is not hard work; spending thinking tokens on it
        # would cost more than the readability is worth.
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _established(picture: Picture) -> list:
    """The fields a summary may draw on: anything actually determined."""
    return [a for a in picture.all if a.determined and a.value]


def build_prompt(picture: Picture, description: str) -> str:
    """The only thing the model sees: established fields, with their states."""
    lines = [f"Incident as reported: {description}", "", "Established fields:"]
    for a in _established(picture):
        lines.append(f"- [{a.status.value}] {a.field}: {a.value}")
    return "\n".join(lines)


# Words and figures, without the punctuation attached to them. An earlier
# version kept the trailing full stop, so "away." read as an unknown proper
# noun and every well-formed sentence failed the check.
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def grounded(text: str, picture: Picture) -> tuple[bool, list[str]]:
    """Does every number and name in `text` appear in the established fields?

    Deliberately strict about numbers, which is where a fabricated detail does
    the most damage — a wrong distance or storey count reads as authoritative
    and gets acted on. Looser about words, because connective English is not a
    claim and a check that rejects ordinary prose is a check nobody keeps.
    """
    source = " ".join(str(a.value) for a in _established(picture))
    source_tokens = _tokens(source)
    source_numbers = _numbers(source)

    offending = [n for n in _numbers(text) if n not in source_numbers]

    def acceptable(token: str) -> bool:
        if token in _STOPWORDS or token in source_tokens:
            return True
        # Ordinary lowercase prose is connective tissue, not a claim.
        if re.fullmatch(r"[a-z]+", token) and len(token) > 2:
            return True
        # A hyphenated compound is acceptable when all its parts are.
        # "13-storey" is a faithful rendering of `storeys: 13`; rejecting it
        # rejects correct prose, and a check that rejects correct prose is one
        # people learn to ignore. This cannot smuggle a fabrication through,
        # because numbers are checked against the source separately above —
        # "40-storey" still fails on the 40.
        if "-" in token:
            parts = [p for p in token.split("-") if p]
            return bool(parts) and all(acceptable(p) for p in parts)
        return False

    offending.extend(t for t in _tokens(text) if not acceptable(t))
    return (not offending), offending


def deterministic_summary(picture: Picture, description: str) -> str:
    """Correct by construction, and always available."""
    verified = [a for a in picture.by_status(Status.VERIFIED) if a.value]
    reported = [a for a in picture.by_status(Status.REPORTED) if a.value]
    unknown = picture.unknown_fields

    first = "; ".join(f"{a.field} {a.value}" for a in verified[:3]) or \
        "nothing established from public records"
    second = (
        "Reported by the caller, unverified: "
        + "; ".join(str(a.value) for a in reported[:2]) + "."
        if reported else "Nothing further was reported by the caller."
    )
    third = (f" {len(unknown)} questions remain open until a crew is on scene."
             if unknown else "")
    return f"Established: {first}. {second}{third}"


def summarise(picture: Picture, description: str) -> Summary:
    """A readable summary: model-written where possible, checked either way."""
    template = deterministic_summary(picture, description)
    provider = chosen_provider()
    if provider is None:
        return Summary(template, "template")

    prompt = build_prompt(picture, description)
    try:
        if provider == "claude":
            text = _claude_summary(prompt)
        else:
            text = _gemini_summary(prompt, os.environ["GEMINI_API_KEY"])
    except Exception as exc:  # noqa: BLE001 - a summary is never worth a crash
        return Summary(template, "template",
                       rejected=f"{type(exc).__name__}: {exc}")

    if not text:
        return Summary(template, "template", rejected="model returned nothing")

    # The same gate for every provider. This is the reason a second model can
    # be added without adding risk.
    ok, offending = grounded(text, picture)
    if not ok:
        return Summary(
            template, "template",
            rejected=f"introduced {', '.join(sorted(set(offending))[:4])} — "
                     "not present in the established fields",
        )
    return Summary(text, provider)
