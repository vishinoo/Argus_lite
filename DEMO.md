# Demo script — 90 seconds

Run once before the demo so the survey cache is warm; the live run then takes
under two seconds and cannot be taken down by a busy Overpass mirror.

```bash
ic run "Structure fire at 1001 Van Ness Avenue, San Francisco" >/dev/null
```

**1 · The problem (10s).** "When a 911 call comes in, a dispatcher searches
maps, web sources and comms tools before they have a picture. We automated
that."

**2 · The run (40s).** Use the console — `ic serve`, then
`http://127.0.0.1:8000`. Or the terminal:
```bash
ic run "Structure fire at 1001 Van Ness Avenue, San Francisco. \
Caller reports smoke from the second floor and someone may still be inside." \
  --id IC-1847 --execute
```
Point at three things, in this order:

1. **The evidence chain** — "every arrow is a real tool call. The brief is
   built from evidence. The model writes the summary at the top and nothing
   else — and if it introduces a fact that isn't in the evidence, we throw the
   sentence away and use the template."
2. **The five states** — "REPORTED is the caller. VERIFIED named a source.
   These are different sentences and we refuse to render them the same."
   The aerial above them is the real building at those coordinates.
3. **`sought:` on the survey call** — "we never told it to call that tool. The
   schema said occupancy was unknown; it went and found out."

**3 · The refusal (20s).** Click **Try a bad address** in the console, or:
```bash
ic run "Fire at 999999 Unknown Avenue, San Francisco" --execute
```
"It will not act on a location it cannot verify — even when told to." Point at
the stage rail: DECIDE and ACT go red and say *halted*, and the evidence chain
shows each lookup skipped rather than quietly not run.

**4 · The evaluation (20s).**
```bash
ic eval
```
"A hundred incidents. We also test that the tests can fail — and the suite
found three classifier bugs in us, including a missed *Shots reported*.
Classification was 90% before we fixed them."

**If asked what it costs:** one metered call per incident, 439 prompt and 28
completion tokens. Roughly $0.0002 an incident. Every fact-gathering source is
keyless.

Do not say "operating system for emergency services." Say: "This is one
workflow. It's the first piece of Argus."
