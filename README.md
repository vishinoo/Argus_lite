# Argus Incident Commander

**An evidence-backed incident intelligence agent.** Give it an emergency and it investigates the situation across applications, determines what is known and unknown, and coordinates the resulting intelligence across the response team.

When a 911 call comes in, a dispatcher may need to search maps, web sources, internal records and communications tools before they have a complete picture. We built an agent that does that work — and, more importantly, one that tells you how much of it it actually established.

**The dispatcher stays in control. Argus does not dispatch units. It prepares the intelligence a human needs to decide faster.**

---

## Demo

**Watch the full Argus Incident Commander demo:**

[**▶ Watch the 2-minute demo on YouTube**](https://youtu.be/O0qCljFcMg4)

The demo begins with a simulated 911 call and follows the incident through the Argus agent loop:

**Observe → Investigate → Reason → Recommend**

Argus receives the incident, identifies what needs to be established, investigates across live sources, constructs an evidence-backed incident picture, and delivers the resulting intelligence to the response team.

### Screenshots

<!-- Replace these placeholders with screenshots from your demo -->

#### Incident Intelligence Console

<img width="1189" height="644" alt="Screenshot 2026-09-13 at 5 07 04 PM" src="https://github.com/user-attachments/assets/cc483525-a08c-46ce-84e4-a6bb153be077" />

The console shows the incident as it develops, including sourced findings, unknowns, confidence, tool execution, and operational considerations.

#### Evidence & Investigation

<img width="377" height="677" alt="Screenshot 2026-09-13 at 5 07 22 PM" src="https://github.com/user-attachments/assets/ccfc447c-0e06-496a-8406-a8e00412a7f2" />

Every external claim is tied to the source that established it. Argus distinguishes between **REPORTED**, **VERIFIED**, **INFERRED**, **CONTRADICTED**, and **UNKNOWN** information.

#### Response Team Coordination

<img width="477" height="294" alt="Screenshot 2026-09-13 at 5 07 39 PM" src="https://github.com/user-attachments/assets/9cfd8495-24a4-4219-96c5-abe9a4bdb010" />

<img width="914" height="671" alt="Screenshot 2026-09-13 at 5 08 21 PM" src="https://github.com/user-attachments/assets/a889e3c2-211e-4676-9a47-3adbb4034e7b" />

<img width="1249" height="789" alt="Screenshot 2026-09-13 at 5 10 54 PM" src="https://github.com/user-attachments/assets/20fd69c3-c657-4779-a3ec-820b4f238fea" />

Argus can turn the resulting incident picture into a responder-facing brief and coordinate it through connected communication tools.

---

## It has a job, not a prompt

Argus is not told which tools to call. It is given an incident and a schema of what must be determined for that kind of incident, and it works until the schema is satisfied or nothing more can help.

```text
required for a fire:   location  building  occupancy  access  hazards
                       fire_station  hospital
still unknown:         building, hazards, fire_station, hospital
→ runs osm.survey      because it closes four gaps at once
```

Behaviour changes when the **schema** changes, not when a pipeline does. Adding `utility` to the gas schema makes Argus start investigating utility operators on gas calls, with no new control flow anywhere.

```bash
ic serve          # the console, at http://127.0.0.1:8000
ic run "..."      # the same agent, in the terminal
ic check          # which integrations are live
ic eval           # the reliability suite
```

The console is the same agent: it posts the incident text and renders the result the CLI prints. Nothing is simulated for the browser. `?q=<incident>&auto=1` opens and works an incident directly, so a demo can start the same way twice.

```text
  ✓ maps.geocode             322ms  Coterie, 1001, Van Ness Avenue, Western Addition…
  ✓ osm.survey                 1ms  storeys: 13; occupancy: social_facility; name: Coterie
  ✓ web.public_search        542ms  no public article specific to this address
  ✓ ntfy.alert               412ms  delivered to ntfy.sh/argus-vIfi2FIYKqLvZzgo
  ✓ slack.create_channel     286ms  #incident-ic-1847-1001-van-ness-avenue
  ✓ slack.post_message       310ms  brief posted to noctus-talk.slack.com/archives/…

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

Everything above is live. The geocoder, the building record, the hazards and the station distances are real OpenStreetMap data, keyless. The travel times come from an affine model fitted on 5,437 San Francisco Fire Department dispatches.

## Uncertainty is a first-class field

Every field carries one of four states, and the difference between them is the product:

```text
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

"There are 12 people inside" and "the caller thinks people might be inside" are different sentences. A system that renders them in the same typeface will eventually get someone hurt.

`VERIFIED` cannot be constructed without a source — it raises. When we wrote the test that tries to build an unattributed claim, we could not do it without deliberately bypassing the constructor.

## Where the message actually went

The run used to say `brief posted to #C0C1C6YDTDH` and stop there. That is true and useless: nobody watching can act on a channel id, and a message nobody can find is indistinguishable from one that was never sent. Every delivered action now comes back with a link you can open.

```text
  ✓ ntfy.alert               delivered to ntfy.sh/argus-vIfi2FIYKqLvZzgo
  ✓ slack.post_message       brief posted to
                             noctus-talk.slack.com/archives/C0C1C6YDTDH/p1789337416854919
```

What lands in the channel is the brief, not a headline — laid out for a phone rather than a terminal, with the caller's own words quoted at the top and the three categories kept apart:

```text
  :rotating_light: HIGH PRIORITY — FIRE
  1001 Van Ness Avenue, San Francisco  ·  IC-1847

  A structure fire is reported at a 13-storey social facility.

  > Structure fire at 1001 Van Ness Avenue. Caller reports smoke from the
  > second floor and someone may still be inside.

  ESTABLISHED
  • building — storeys: 13
     OpenStreetMap building record
  • fire_station — San Francisco Fire Station 3 — 0.3 km, est. 2:52
     OpenStreetMap / Overpass
  ...
  ADVISORY — worked out, or reported by the caller
  • access — consider a ladder company for aerial access
     13 storeys exceeds ground-ladder reach
  ...
  NOT ESTABLISHED — no source can settle these before arrival
  • persons_trapped, severity, hazmat, current_access
```

Every established line carries the record it came from. A claim without its source is the one thing this system will not produce, and it does not become one on the way into Slack.

## A call is not one sentence

The line stays open. The smoke changes colour, somebody gets out, the patient turns out to be nine floors up — and each of those either fills a gap or contradicts something already recorded.

```bash
ic run "Cardiac arrest at 233 S Wacker Drive, Chicago. Bystander performing CPR" \
  --update "Caller now says the patient is on the 9th floor"
```

Everything said is posted on every run; the server keeps no session. Each statement stays REPORTED, because arriving later does not make a caller a record — but classification, extraction and the contradiction checks all run over the whole call, so an update can change what kind of incident this is, add people the first sentence never mentioned, or disagree with the building record and be carried as CONTRADICTED.

Statements accumulate rather than replace. A caller who says "one person down" and then "another person is down" gets both — the people row reads *One person down; another person is down*, because two people are down and a brief that names one of them is wrong.

In the console the picture marks what moved, because an update otherwise lands as a wall of identical rows and the one thing that changed is the one thing nobody spots.

## Three disciplines, three sets of advice

An earlier version gave every incident the fire treatment, which on a report of shots fired meant recommending a ladder company and the nearest hydrant. That is the kind of error anyone operational spots in a second.

```text
  FIRE     upwind approach side · wind · what is in the plume · water
           supply · which engine arrives from which side · aerial access
           above ground-ladder reach

  EMS      the floor the patient is on, however the caller phrased it ·
           lift and stretcher route · transport destination, flagged
           TIME-CRITICAL when the caller describes one

  POLICE   nearest mapped police station · who is close enough to matter,
           because a school inside 500 m is a lockdown decision somebody
           has to make early
```

The gating runs the other way too. A shooting gets no wind reading, no hydrant and no responding engine: wind decides a plume and there is no plume, and those rows were crowding the one column a dispatcher is meant to act from.

The EMS one prefers the caller's floor to the building's height, because the building's height was never the question, and because for the towers where it matters most OpenStreetMap frequently has no height at all.

It also will not call a destination an emergency department. `amenity=hospital` covers counselling clinics and outpatient surgery centres, and live this recommended transporting a cardiac arrest to "Cityscape Counseling" under that heading. The nearest *mapped hospital* is what the evidence supports.

## The evidence chain

The brief is visibly *constructed from evidence* rather than produced whole:

```text
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

**A claim that cannot name its source cannot be made.** `Claim.recorded` raises a `ValueError` without a `Source`. That is the mechanism behind "100% of external claims are attributable" — it is a property of the type, not the diligence of a prompt. We tried to construct a violation for the test suite and could not without deliberately bypassing the constructor.

**Confidence is computed, not asserted.** It falls out of how much corroboration there is, whether the location verified, and how long the list of unknowns is. A model that writes "Confidence: 87%" about its own output is marking its own homework. This number can be recomputed by anyone who doubts it.

**It refuses.** Give it an address that does not exist and it will not act — even with `--execute`:

```bash
ic run "Fire at 999999 Unknown Avenue, San Francisco" --execute
```

```text
  ✗ maps.geocode             682ms  no geocoder match
  ✗ osm.survey                 0ms  skipped — location unverified

UNVERIFIED — HUMAN CONFIRMATION REQUIRED
  · the address could not be verified against any public geocoder
  · human confirmation of the address is required before acting

  WORKFLOW NOT EXECUTED
```

This is the one place the agent overrules its operator, and it is the right place: the channel, the brief and the people notified would all be about somewhere that may not exist.

### Measured — in this repository

```text
one incident, live, Edmonton          7.2 s wall clock
tool calls                            4   geocode · survey · public search · weather
model calls                           1
  prompt                              439 tokens
  completion                          28 tokens
metered APIs                          1 of 6
```

Nominatim, Overpass, Open-Meteo, Wikipedia and Esri imagery are keyless and free; ntfy delivers a real push with no account. The single model call is the only metered thing in the system — because the model writes prose and never gathers a fact. That decision was made for provenance. It turns out to set the bill as well.

At the list price quoted for `gemini-2.5-flash` when this was written ($0.30 / 1M input, $2.50 / 1M output — check it, the arithmetic is the point):

```text
439 tokens × $0.30/1M  =  $0.000132
 28 tokens × $2.50/1M  =  $0.000070
                          ─────────
per incident              $0.0002
```

**About two hundredths of a cent per incident.** US fire departments answered roughly 36 million calls in 2022 (NFPA, *Fire Department Calls*). Running this on every one of them is on the order of **$7,000 a year in model spend for the entire United States fire service** — a number small enough that you should want to check it, which is why the multiplication is above it and not behind it.

### Published — not ours, and cited

The dispatch interval is regulated because it is already known to matter.

* **NFPA 1221** sets alarm-processing targets in *seconds* — 90% of alarms within 64 seconds. Nothing in that budget accommodates a dispatcher opening six browser tabs.
* **Out-of-hospital cardiac arrest survival falls roughly 7–10% per minute** without defibrillation (Larsen et al., *Ann Emerg Med*, 1993).
* **A furnished modern room can reach flashover in under five minutes** — UL's 2010 comparison of modern and legacy furnishings measured roughly an order-of-magnitude difference.

These bound the problem. **None of them is evidence about Argus**, and we are not going to multiply one of them by a guess and call the product a life saved.

### Modelled — our arithmetic, with the inputs exposed

The honest claim is narrower than the one a pitch deck would make.

**Argus does not make a dispatcher faster at dispatching.** The call is still worked by a human on the standard clock. What changes is a *different* interval: the one in which the supplementary picture gets assembled — building height, occupancy, nearby hazards, wind direction, the nearest station and which side it arrives from, water supply. Today that picture is assembled over the radio en route, on arrival, or not at all.

```text
                          today             with Argus
  building height         on arrival        before the first unit rolls
  upwind approach side    crew judgement    computed from live wind
  nearest mapped hydrant  on arrival        that, or an explicit "none mapped"
  what is NOT known       implicit          enumerated — 9 open questions
```

The value is not a saved minute we are in any position to claim. It is that **a 13-storey building is known to be 13 storeys at the moment the assignment is made** — while an aerial can still be added to the first alarm instead of requested as a second one. Whether that changes an outcome is an operational question for a fire chief, not an arithmetic one for us, so there is no dollar figure attached to it here. We would not trust one that was.

What we will claim is the asymmetry: the marginal cost of finding out is $0.0002, and the marginal cost of *not* finding out is whatever a late aerial costs. No agency needs a business case to justify the first number.

### The cost line we have not measured

**The free tier is not a deployment plan.** Nominatim and Overpass are volunteer-run, and their usage policies do not contemplate an agency's call volume — running production traffic through them would be both a breach and a bad dependency. Real deployment means self-hosted Nominatim and Overpass instances or a commercial geocoder. That is a genuine recurring cost, and this README does not quote a figure for it, because we have not measured it. The $7,000 above is a model-spend number, not a total cost of ownership.

## Honest limits

* **Actions rehearse without credentials.** Slack composes the real message, writes it to `out/`, and reports `rehearsed`. Nothing is faked as delivered, and `delivered` is counted separately from `ok`. The responder alert needs no credentials and is delivered for real either way.
* **OpenStreetMap is incomplete**, unevenly so. An empty hazard scan means nothing was *mapped*, which is not the same as nothing being there — and the brief says exactly that.
* **Public search is filtered hard.** A Wikipedia hit on "San Francisco" is not information about your building. Generic matches are discarded and reported as discarded.
* **Not for operational use.** This is decision support built in a weekend.

## Run it

```bash
pip install -e .
ic run "Structure fire at 1001 Van Ness Avenue, San Francisco"   # warms the cache
ic serve                                                          # then demo from here
pytest -q          # 278 tests
```

No API keys required — every fact-gathering source is keyless, and the brief is complete without a model.

Set `SLACK_BOT_TOKEN` to deliver for real instead of rehearsing. Set `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` and a model writes the two-sentence summary at the top of the brief, instead of the deterministic template.

**The model is on a short leash, deliberately.** It never sees raw tool output and never gathers a fact — it is handed fields Argus has already established, with each field's state attached, and asked to restate them. Its output is then checked against those fields: every number and every distinctive name in the summary has to appear in the evidence, or the summary is discarded and the template is used. The check does not know which provider wrote the text, which is what made adding a second one safe rather than a second risk.

```text
  summary.write    1273ms  gemini: A structure fire is reported on 105 Avenue
                           NW, with smoke showing. The caller reports someone
                           may still be inside.
```

Note what survived the check: *"the caller reports"*. The model was given that field marked `REPORTED` and kept it marked. `ic check` reports which provider is live.

## Where this sits

Argus Incident Commander is one workflow: what happens in the minutes immediately after a call comes in. It is the first piece of **Argus, an intelligence layer for emergency response.**

