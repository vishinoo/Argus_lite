# Argus Incident Commander

**An evidence-backed incident intelligence agent.** Give it an emergency and it
investigates the situation across applications, determines what is known and
unknown, and coordinates the resulting intelligence across the response team.

When a 911 call comes in, a dispatcher may need to search maps, web sources,
internal records and communications tools before they have a complete picture.
We built an agent that does that work — and, more importantly, one that tells
you how much of it it actually established.

**The dispatcher stays in control. Argus does not dispatch units. It prepares
the intelligence a human needs to decide faster.**

## It has a job, not a prompt

Argus is not told which tools to call. It is given an incident and a schema of
what must be determined for that kind of incident, and it works until the
schema is satisfied or nothing more can help.

```
required for a fire:   location  building  occupancy  access  hazards
                       fire_station  hospital
still unknown:         building, hazards, fire_station, hospital
→ runs osm.survey      because it closes four gaps at once
```

Behaviour changes when the **schema** changes, not when a pipeline does. Adding
`utility` to the gas schema makes Argus start investigating utility operators on
gas calls, with no new control flow anywhere.

```bash
ic serve          # the console, at http://127.0.0.1:8000
ic run "..."      # the same agent, in the terminal
ic check          # which integrations are live
ic eval           # the reliability suite
```

The console is the same agent: it posts the incident text and renders the
result the CLI prints. Nothing is simulated for the browser. `?q=<incident>&auto=1`
opens and works an incident directly, so a demo can start the same way twice.

```
  ✓ maps.geocode             322ms  Coterie, 1001, Van Ness Avenue, Western Addition…
  ✓ osm.survey                 1ms  storeys: 13; occupancy: social_facility; name: Coterie
  ✓ web.public_search        542ms  no public article specific to this address
  ✓ slack.create_channel       2ms  #incident-ic-1847-1001-van-ness-avenue    rehearsed
  ✓ gmail.send                 0ms  brief prepared for command@example.gov    rehearsed

HIGH PRIORITY — FIRE
KNOWN       storeys: 13 · occupancy: social_facility        [recorded] OpenStreetMap
HAZARDS     Sacred Heart Cathedral Preparatory School — 207 m
RESOURCES   Nearest fire station: SFFD Station 3 — 0.3 km, est. 2:52
            Nearest hospital: CPMC Van Ness — 0.1 km, est. 2:36
CONSIDERATIONS (advisory)
            Aerial access likely required — 13 storeys exceeds ground ladders
            Assisted evacuation likely — occupancy implies people who may not self-evacuate
Confidence 85% — computed from 8 sourced findings and 1 open question
```

Everything above is live. The geocoder, the building record, the hazards and
the station distances are real OpenStreetMap data, keyless. The travel times
come from an affine model fitted on 5,437 San Francisco Fire Department
dispatches.

## Uncertainty is a first-class field

Every field carries one of four states, and the difference between them is the
product:

```
  SITUATION
    REPORTED  report         Structure fire, someone may still be inside
      confidence Low     reported by the caller; not independently verified
    VERIFIED  location       Coterie, 1001 Van Ness Avenue, San Francisco
      confidence High    OpenStreetMap / Nominatim
    VERIFIED  building       storeys: 13; occupancy: social_facility
      confidence High    OpenStreetMap building record
    INFERRED  access         aerial access likely required — ladder company
      confidence Medium  13 storeys exceeds ground-ladder reach

  PEOPLE
    VERIFIED  occupancy      social_facility
    INFERRED  vulnerability  occupants may not be able to self-evacuate

  THREATS
    VERIFIED  hazards        Sacred Heart Cathedral Preparatory School — 207 m
    UNKNOWN   utility        no consulted source names the operator for this address

  schema completeness 100% · 6 verified · 1 unknown
```

"There are 12 people inside" and "the caller thinks people might be inside" are
different sentences. A system that renders them in the same typeface will
eventually get someone hurt.

`VERIFIED` cannot be constructed without a source — it raises. When we wrote the
test that tries to build an unattributed claim, we could not do it without
deliberately bypassing the constructor.

## The evidence chain

The brief is visibly *constructed from evidence* rather than produced whole:

```
  CALLER REPORT
    ↓  "Structure fire at 1001 Van Ness Avenue, someone may still be inside"
  ✓ maps.geocode
    ↓  Coterie, 1001, Van Ness Avenue, Western Addition, San Francisco
       sought: location
  ✓ osm.survey
    ↓  storeys: 13; occupancy: social_facility; name: Coterie
       sought: building, occupancy, hazards, fire_station
  ARGUS SYNTHESIS
```

Every arrow is a real tool call with a real latency and a real source.

## The part we think matters

Three properties, each enforced in code rather than asked for in a prompt.

**A claim that cannot name its source cannot be made.** `Claim.recorded` raises
a `ValueError` without a `Source`. That is the mechanism behind "100% of
external claims are attributable" — it is a property of the type, not the
diligence of a prompt. We tried to construct a violation for the test suite and
could not without deliberately bypassing the constructor.

**Confidence is computed, not asserted.** It falls out of how much
corroboration there is, whether the location verified, and how long the list of
unknowns is. A model that writes "Confidence: 87%" about its own output is
marking its own homework. This number can be recomputed by anyone who doubts it.

**It refuses.** Give it an address that does not exist and it will not act —
even with `--execute`:

```bash
ic run "Fire at 999999 Unknown Avenue, San Francisco" --execute
```
```
  ✗ maps.geocode             682ms  no geocoder match
  ✗ osm.survey                 0ms  skipped — location unverified

UNVERIFIED — HUMAN CONFIRMATION REQUIRED
  · the address could not be verified against any public geocoder
  · human confirmation of the address is required before acting

  WORKFLOW NOT EXECUTED
```

This is the one place the agent overrules its operator, and it is the right
place: the channel, the brief and the people notified would all be about
somewhere that may not exist.

## Reliability

```bash
ic eval
```

```
  100 synthetic incidents · scripted evidence

    workflows completed                     100/100
    incident classification                 100.0%
    location extraction                     100.0%
    required fields extracted               100.0%
    schema completeness                      94.5%
    behavioural checks passed               234/234
    tool-call success rate                   99.6%
    external claims source-attributed       100.0%
    unsupported claims presented as fact       0
    advisories presented as confirmed          0
    refusals correctly escalated             2/2
    actions completed                    392/392
```

A hundred incidents across fire, medical, gas, armed, missing-person,
bad-address and evidence-quality categories. Twenty are hand-written and carry
the judgement calls — not "handles gas leaks well" but "raises utility isolation
*and* records that the operator is unconfirmed." Eighty are generated to measure
classification and extraction against phrasing variation rather than against one
sentence per category.

**The suite found three real bugs in us.** `shoot\w*` never matched *"Shots
reported"*, so an armed incident reached the workflow unclassified. `fume\b`
never matched *"Fumes"*. Classification was 90% before those fixes and the
number in this table is the one measured after them.

**We also test the tests.** A suite that always returns 100% measures nothing,
so every check is run against a deliberately broken result and must reject it.
That test has already caught one check of ours that could never fail
(`lambda r: True`) and one naming heuristic that silently excused another.

Evidence is scripted so the numbers are deterministic. A reliability figure
that moves because a volunteer-run tile server was busy measures the weather.

## Honest limits

- **Actions rehearse by default.** Without credentials, Slack/mail/calendar
  compose the real message, write it to `out/`, and report `rehearsed`. Nothing
  is faked as delivered. The calendar writes a real `.ics` either way.
- **OpenStreetMap is incomplete**, unevenly so. An empty hazard scan means
  nothing was *mapped*, which is not the same as nothing being there — and the
  brief says exactly that.
- **Public search is filtered hard.** A Wikipedia hit on "San Francisco" is not
  information about your building. Generic matches are discarded and reported
  as discarded.
- **Not for operational use.** This is decision support built in a weekend.

## Run it

```bash
pip install -e .
ic run "Structure fire at 1001 Van Ness Avenue, San Francisco"   # warms the cache
ic serve                                                          # then demo from here
pytest -q          # 121 tests
```

No API keys required. Set `SLACK_BOT_TOKEN` / `SMTP_USER` + `SMTP_PASS` to
deliver for real instead of rehearsing.

## Where this sits

Argus Incident Commander is one workflow: what happens in the minutes
immediately after a call comes in. It is the first piece of Argus, an
intelligence layer for emergency response.
