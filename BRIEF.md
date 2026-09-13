# Argus Incident Commander — system and reliability brief

[**▶ Two-minute demo**](https://youtu.be/O0qCljFcMg4)

An emergency call is one sentence. Acting on it needs a dozen facts that live
in different systems. Argus investigates across those systems, states what it
established and what it could not, and coordinates the result to the response
team.

## What it connects to

| External app | Role | Status |
|---|---|---|
| Slack | opens an incident channel, posts the full brief, returns a permalink | live |
| ntfy.sh | push alert to responders' phones | live, no credentials needed |
| OpenStreetMap Nominatim | geocoding | live |
| OpenStreetMap Overpass | building, hazards, hydrants, stations | live |
| Open-Meteo | wind, for plume and approach side | live |
| Wikipedia | public record of the address | live |
| Esri World Imagery | aerial of the location | live |
| Gemini | writes the summary prose | live |

`ic check` prints this at runtime. Nothing above needs an API key except Slack,
and Gemini.

## How it works

Six stages: observe → investigate → reason → decide → act → document. The
console does not draw them — a diagram of our control flow is not something a
dispatcher acts on. It shows the finalised approach and the open questions
instead.

It is **not** a pipeline. Each incident kind has a schema of fields that must
be determined; the unfilled required fields are the agent's to-do list, and it
picks the tool that closes the most gaps. Adding a field to a schema changes
behaviour with no new control flow. The evidence chain shows this as
`sought: building, hazards, resources, water supply` against the call that
went and got them.

**Every field carries one of five states** — VERIFIED, REPORTED, INFERRED,
CONTRADICTED, UNKNOWN. "Twelve people are inside" and "the caller thinks people
might be inside" are different sentences, and the system will not render them
in the same typeface.

**A claim that cannot name its source cannot be constructed.** `Claim.recorded`
and `Assessment.verified` raise `ValueError` without a `Source`. Attribution is
a property of the type, not the diligence of a prompt.

**The model writes prose and never gathers a fact.** It is handed fields
already established, with each state attached, and asked to restate them. Its
output is then checked against those fields: every number and distinctive name
must appear in the evidence or the summary is discarded for a deterministic
template. The check does not know which provider wrote the text.

**It refuses.** An address no geocoder can verify halts the workflow — even
with `--execute`. Acting would mean opening a channel and notifying people
about a place that may not exist.

## How we know it works

`ic eval` — 100 synthetic incidents, scripted evidence, deterministic:

```
workflows completed                     100/100
incident classification                 100.0%
location extraction                     100.0%
required fields extracted               100.0%
schema completeness                      97.2%
behavioural checks passed               234/234
structured extraction accuracy          100.0%
tool-call success rate                   99.7%
external claims source-attributed       100.0%
unsupported claims presented as fact         0
advisories presented as confirmed            0
refusals correctly escalated               2/2
actions completed                    490/490
```

Plus 278 unit tests.

**`schema completeness` is 97.2% and stays there.** Some incidents genuinely
have fields no public source can fill. A scorecard reading 100% everywhere
measures how flattering the metrics are.

**Required-field extraction reached 100% by fixing a bug, not lowering a bar.**
The eval kept a second copy of the schema's required fields. It drifted: it
graded against `hazards` while the picture had been renamed to emit `external
hazards`, so that gap could never close and completeness was understated on
every fire and gas call — 36 of 36. The eval now derives its expectations from
the schema.

**We test the tests.** Every check is run against a deliberately broken result
and must reject it. That negative control caught one of our own checks that
could never fail (`lambda r: True`).

**The suite found three real bugs in us.** `shoot\w*` never matched *"Shots
reported"*; `fume\b` never matched *"Fumes"*. Classification was 90% before
those fixes; the table above is measured after.

**Live verification**, five incident kinds against the real APIs — fire, gas,
cardiac arrest, armed, missing person, plus an unverifiable address:

```
gas       4/4 calls   100% attributable   0 unsupported
medical   4/4 calls   100% attributable   0 unsupported
armed     4/4 calls   100% attributable   0 unsupported
missing   4/4 calls   100% attributable   0 unsupported
bad address           REFUSED — workflow not executed
```

## Limits

- **Not for operational use.** Decision support built in a weekend.
- **An empty hazard scan means nothing was *mapped*** — not that nothing is
  there. The brief says so rather than reading as an all-clear.
- **Cold lookups are slow.** A first query against Overpass measured up to 35s;
  warm, the same run is 0.7s. Warm the cache before a demo.
- **The free tier is not a deployment plan.** Nominatim and Overpass are
  volunteer-run. Production means self-hosting or a commercial geocoder.
- **Argus does not dispatch.** It prepares what a human needs to decide.
