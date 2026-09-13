/* Argus Incident Commander — console.
 *
 * The agent runs server-side and returns the whole result. The reveal here
 * replays the *real* per-call latencies from the transcript rather than
 * inventing a loading animation: what you watch is what actually happened, at
 * the speed it happened, capped so a slow lookup does not stall a demo.
 */

/* A glyph per state. The word is kept as the title attribute and in the legend,
   so nothing depends on the glyph alone — colour-blind readers and bad
   projectors both need the word somewhere. */
const GLYPH = {
  VERIFIED: "\u2713",       // check — a record says so
  REPORTED: "\u201C",       // open quote — somebody said so
  INFERRED: "\u2234",       // therefore — worked out from something else
  CONTRADICTED: "\u2260",   // not equal — two sources disagree
  UNKNOWN: "?",              // nobody has established this
};

/* One opening line per discipline, and a plausible second thing the caller
   says. The follow-up is the point: a call is not one sentence, and the
   picture has to move when the second sentence arrives. */
const TEMPLATES = {
  fire: {
    text: "Structure fire at 1001 Van Ness Avenue, San Francisco. Caller reports smoke from the second floor and someone may still be inside.",
    then: "Caller now says two people are still inside",
  },
  ems: {
    text: "Cardiac arrest at 233 S Wacker Drive, Chicago. Bystander performing CPR, patient unresponsive.",
    then: "Caller now says the patient is on the 9th floor",
  },
  police: {
    text: "Shots reported at 350 5th Avenue, New York. One person down, suspect seen leaving on foot.",
    then: "Caller now says the suspect is still on scene",
  },
};

/* Everything the caller has said, in order. The opening line plus these is the
   whole call, and every run posts the lot: the server holds no session. */
let updates = [];
let incidentId = null;
/* field -> state, from the last render, so a row that moved can be shown as
   having moved. Without this an update lands as a wall of identical rows and
   the one thing that changed is the thing nobody spots. */
let previous = null;

const $ = (id) => document.getElementById(id);
const rail = $("rail");
const out = $("out");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* The left column used to replay the six stages of the agent loop, which is a
   diagram of our control flow — interesting to us, and nothing a dispatcher
   needs while an incident is open. It now carries the two things they would
   actually act on: how to come at it, and what nobody knows yet. */
function drawPlan(picture, status) {
  const approach = (picture && picture.approach) || [];
  const open = (picture && picture.open_questions) || [];

  const row = (a) => `
    <div class="planrow${movedSince(a) ? " moved" : ""}">
      <span class="state" data-s="${esc(a.status)}" title="${esc(a.status)}"
            aria-label="${esc(a.status)}">${GLYPH[a.status] || "\u00b7"}</span>
      <span class="pv">
        <b>${esc(a.field)}</b>
        ${a.value ? esc(String(a.value).replace(/^RECOMMENDATION:\s*/i, "")) : "—"}
        <span class="cite">${esc(a.source || a.evidence)}</span>
      </span>
    </div>`;

  rail.innerHTML = `
    <section class="plan glass">
      <div class="eyebrow">Approach</div>
      ${approach.length ? approach.map(row).join("")
                        : `<p class="waiting">${esc(status || "—")}</p>`}
    </section>
    <section class="plan glass">
      <div class="eyebrow">Open questions</div>
      ${open.length
        ? `<div class="opens">${open.map((a) =>
            `<span class="open">${esc(a.field)}</span>`).join("")}</div>
           <p class="waiting">No source can settle these before arrival.</p>`
        : `<p class="waiting">—</p>`}
    </section>`;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));

/* A cold lookup against Overpass can run to half a minute. Without this the
   screen is motionless for that whole time and reads as hung, so the active
   stage carries the real elapsed time until the server answers. */
let ticker = null;
function startClock() {
  const t0 = performance.now();
  stopClock();
  ticker = setInterval(() => {
    const el = rail.querySelector(".waiting");
    if (el) el.textContent = `working… ${((performance.now() - t0) / 1000).toFixed(1)}s`;
  }, 100);
}
function stopClock() { clearInterval(ticker); ticker = null; }

function setBusy(busy) {
  $("go").disabled = $("add").disabled = busy;
  document.querySelectorAll(".seg").forEach((b) => (b.disabled = busy));
}

async function run(text) {
  setBusy(true);
  out.innerHTML = "";
  document.querySelectorAll(".aside").forEach((n) => n.remove());
  drawPlan(null, "working…");

  let data;
  startClock();
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text, updates, incident_id: incidentId }),
    });
    data = await res.json();
    stopClock();
    if (data.error) throw new Error(data.error);
  } catch (err) {
    stopClock();
    out.innerHTML = `<div class="refusal glass"><h2>Could not run</h2>
      <p>${esc(err.message)}</p></div>`;
    drawPlan(null, "halted");
    setBusy(false);
    return;
  }

  incidentId = data.incident.id || incidentId;
  await render(data);
  remember(data.brief.picture);
  $("followup").hidden = false;
  setBusy(false);
}

/* What the picture said last time, so the next render can mark what moved. */
const STATE_KEYS = ["situation", "people", "threats", "exposures", "resources",
                    "approach", "open_questions"];

function remember(picture) {
  previous = new Map();
  if (!picture) return;
  for (const key of STATE_KEYS) {
    for (const a of picture[key] || []) {
      previous.set(a.field, `${a.status}|${a.value ?? ""}`);
    }
  }
}

function movedSince(a) {
  if (!previous) return false;
  const now = `${a.status}|${a.value ?? ""}`;
  return !previous.has(a.field) || previous.get(a.field) !== now;
}

async function render(data) {
  const lookups = data.transcript.calls.filter(
    (c) => !["slack", "ntfy"].includes(c.tool.split(".")[0]));
  const actions = data.transcript.calls.filter(
    (c) => ["slack", "ntfy"].includes(c.tool.split(".")[0]));

  // ---- evidence chain, revealed at the pace it actually ran
  const aside = document.createElement("div");
  aside.className = "aside";
  out.parentElement.appendChild(aside);

  const chain = document.createElement("section");
  chain.className = "panel glass reveal";
  chain.innerHTML = `<h2>Evidence chain</h2><div class="chain" id="chain">
    <div class="node"><span class="mark">●</span><span class="what">Caller report</span></div>
    <div class="node"><span class="rule">↓</span>
      <span class="detail">${esc(data.incident.description)}</span></div>
  </div>`;
  aside.appendChild(chain);
  const chainBox = $("chain");

  for (const call of lookups) {
    await sleep(Math.min(call.latency_ms, 900));
    const node = document.createElement("div");
    node.className = "reveal";
    node.innerHTML = `
      <div class="node"><span class="mark ${call.ok ? "" : "bad"}">${call.ok ? "✓" : "✗"}</span>
        <span class="what">${esc(call.tool)}</span></div>
      <div class="node"><span class="rule">↓</span><span class="detail">
        ${esc(call.summary || call.error || "")}
        ${call.args && call.args.because
          ? `<span class="sought"><br>sought: ${esc(call.args.because)}</span>` : ""}
      </span></div>`;
    chainBox.appendChild(node);
  }
  chainBox.insertAdjacentHTML("beforeend",
    `<div class="node"><span class="mark">●</span><span class="what">Argus synthesis</span></div>`);

  await sleep(260);

  // ---- the picture
  const b = data.brief;
  if (b.picture) out.appendChild(picturePanel(b, data));
  drawPlan(b.picture, data.refused ? "halted" : "—");
  if (b.picture && (b.picture.ledger || []).length) aside.appendChild(ledgerPanel(b.picture));
  await sleep(200);

  if (data.refused) {
    out.insertAdjacentHTML("afterbegin", `
      <div class="refusal glass reveal">
        <h2>Workflow not executed</h2>
        <p>${esc(data.refused)}</p>
      </div>`);
  } else if (actions.length) {
    aside.appendChild(actionsPanel(actions));
  }
  await sleep(200);

  aside.appendChild(metricsPanel(data));
}

const SECTIONS = [
  ["situation", "Situation"],
  ["people", "People"],
  ["threats", "Threats"],
  ["exposures", "Exposures"],
  ["resources", "Resources"],
];

function picturePanel(brief, data) {
  const p = brief.picture;
  const body = SECTIONS.map(([key, title]) => {
    const items = p[key] || [];
    if (!items.length) return "";
    return `<div class="section"><h3>${title}</h3>
      ${items.map((a) => `
        <div class="row${movedSince(a) ? " moved" : ""}">
          <span class="state" data-s="${esc(a.status)}" title="${esc(a.status)}"
                aria-label="${esc(a.status)}">${GLYPH[a.status] || "\u00b7"}</span>
          <span class="field">${esc(a.field)}</span>
          <span class="value">${a.value ? esc(a.value) : '<span class="none">not established</span>'}
            ${(a.evidence_ids || []).map((id) => `<span class="ev">${esc(id)}</span>`).join("")}
            <span class="cite">${esc(a.source || a.evidence)}</span></span>
        </div>`).join("")}
    </div>`;
  }).join("");

  const legend = Object.keys(GLYPH).map((k) =>
    `<span class="item"><span class="state" data-s="${k}">${GLYPH[k]}</span>${k}</span>`
  ).join("");

  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>${esc(brief.priority)} — ${esc(brief.headline)}
    <span class="qualifier">· ${esc(brief.address)}</span></h2>
    ${aerial(p)}
    <div class="legend">${legend}</div>
    ${body}
    <p class="footnote">Advisory — Argus does not dispatch.</p>`;

  const img = panel.querySelector(".aerial img");
  if (img) img.addEventListener("load", () => img.classList.add("ready"));
  return panel;
}

function aerial(picture) {
  const view = picture.imagery;
  if (!view) return "";
  return `<figure class="aerial">
      <img src="${esc(view.url)}" alt="Aerial view of ${view.lat.toFixed(5)}, ${view.lon.toFixed(5)}">
      <span class="crosshair"><i></i></span>
      <figcaption class="cap">Esri</figcaption>
    </figure>
    <p class="vintage">Esri World Imagery · capture date not published</p>`;
}

function ledgerPanel(picture) {
  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>Evidence ledger</h2>
    <div class="ledger">${picture.ledger.map((r) => `
      <div class="ledger-row">
        <span class="ev">${esc(r.id)}</span>
        <span class="field">${esc(r.fact)}</span>
        <span class="value">${esc(r.raw)}</span>
        <span class="cite">${esc(r.tool)} · ${esc(r.source)}</span>
      </div>`).join("")}</div>`;
  return panel;
}

function actionsPanel(actions) {
  // Where it went, as something you can open. "posted to #C0C1C6YDTDH" is true
  // and useless on a projector.
  const link = (a) => {
    const url = a.link;
    return url
      ? `<a class="went" href="${esc(url)}" target="_blank" rel="noopener">open it ↗</a>`
      : "";
  };
  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>Actions</h2><div class="chain">${actions.map((a) => `
    <div class="node"><span class="mark ${a.ok ? "" : "bad"}">${a.ok ? "✓" : "✗"}</span>
      <span class="what">${esc(a.tool)}
        ${a.rehearsed ? '<span class="sought">rehearsed</span>' : ""}</span></div>
    <div class="node"><span class="rule">↓</span>
      <span class="detail">${esc(a.summary)} ${link(a)}</span></div>`).join("")}</div>`;
  return panel;
}

function metricsPanel(data) {
  const b = data.brief;
  const t = data.transcript;
  const counts = {};
  for (const key of ["situation", "people", "threats", "exposures", "resources", "open_questions"]) {
    for (const a of (b.picture?.[key] || [])) counts[a.status] = (counts[a.status] || 0) + 1;
  }
  const cells = [
    ["tool calls", `${t.succeeded}/${t.total}`, t.succeeded === t.total ? "good" : "warn"],
    ["verified", counts.VERIFIED || 0, "good"],
    ["reported", counts.REPORTED || 0, ""],
    ["inferred", counts.INFERRED || 0, ""],
    ["contradicted", counts.CONTRADICTED || 0, (counts.CONTRADICTED ? "warn" : "")],
    ["open questions", counts.UNKNOWN || 0, "bad"],
    ["attributable", `${Math.round((b.attribution_rate || 0) * 100)}%`, "good"],
    ["traceable to evidence", `${Math.round((b.picture?.traceability || 0) * 100)}%`, "good"],
    ["unsupported", b.unsupported_claims ?? 0, (b.unsupported_claims ? "bad" : "good")],
    ["delivered / rehearsed", `${data.actions.delivered} / ${data.actions.rehearsed}`, ""],
    ["elapsed", `${data.elapsed_s}s`, ""],
  ];
  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>Run record</h2><div class="metrics">${cells.map(
    ([k, v, tone]) => `<div class="metric"><div class="k">${k}</div>
      <div class="v ${tone}">${v}</div></div>`).join("")}</div>`;
  return panel;
}

async function integrations() {
  try {
    const res = await fetch("/api/integrations");
    const items = await res.json();
    const live = items.filter((i) => i.live).length;
    $("integrations").innerHTML =
      `<b>${live}/${items.length}</b> integrations live`;
  } catch { /* header detail only; never block the run */ }
}

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  // A new opening line is a new call, not a continuation of the last one.
  updates = [];
  incidentId = null;
  previous = null;
  $("followup").hidden = true;
  run($("text").value);
});

$("followup").addEventListener("submit", (e) => {
  e.preventDefault();
  const said = $("more").value.trim();
  if (!said) return;
  updates.push(said);
  $("more").value = "";
  run($("text").value);
});

$("templates").addEventListener("click", (e) => {
  const button = e.target.closest(".seg");
  if (!button) return;
  const template = TEMPLATES[button.dataset.kind];
  if (!template) return;
  document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("on", b === button));
  $("text").value = template.text;
  $("more").placeholder = template.then;
  updates = [];
  incidentId = null;
  previous = null;
  $("followup").hidden = true;
});

$("text").value = TEMPLATES.fire.text;
$("more").placeholder = TEMPLATES.fire.then;

drawPlan(null, "—");
integrations();

/* A run is addressable: ?q=<incident>&auto=1 opens the console and works it.
   Useful for a demo that has to start the same way twice, and for sending
   somebody the exact incident you were looking at. */
(function fromUrl() {
  const params = new URLSearchParams(location.search);
  const q = params.get("q");
  if (q) $("text").value = q;
  if (params.get("auto") === "1") run($("text").value);
})();
