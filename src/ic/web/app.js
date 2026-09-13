/* Argus Incident Commander — console.
 *
 * The agent runs server-side and returns the whole result. The reveal here
 * replays the *real* per-call latencies from the transcript rather than
 * inventing a loading animation: what you watch is what actually happened, at
 * the speed it happened, capped so a slow lookup does not stall a demo.
 */

const STAGES = [
  ["observe", "Incident received"],
  ["investigate", "Querying external sources"],
  ["reason", "Evaluating evidence"],
  ["decide", "Determining actions"],
  ["act", "Notifying responders"],
  ["document", "Evidence chain recorded"],
];

const $ = (id) => document.getElementById(id);
const rail = $("rail");
const out = $("out");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function drawRail(states = {}) {
  rail.innerHTML = `<div class="eyebrow">Agent loop</div>` + STAGES.map(([key, note]) => `
    <div class="stage" data-state="${states[key] || "idle"}">
      <span class="dot"></span>
      <span>
        <span class="name">${key}</span>
        <span class="note">${states[key] === "blocked" ? "halted" : note}</span>
      </span>
    </div>`).join("");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));

async function run(text) {
  $("go").disabled = $("fail").disabled = true;
  out.innerHTML = "";
  const states = { observe: "done", investigate: "active" };
  drawRail(states);

  let data;
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    });
    data = await res.json();
    if (data.error) throw new Error(data.error);
  } catch (err) {
    out.innerHTML = `<div class="refusal glass"><h2>Could not run</h2>
      <p>${esc(err.message)}</p></div>`;
    drawRail({ observe: "done", investigate: "blocked" });
    $("go").disabled = $("fail").disabled = false;
    return;
  }

  await render(data, states);
  $("go").disabled = $("fail").disabled = false;
}

async function render(data, states) {
  const lookups = data.transcript.calls.filter(
    (c) => !["slack", "gmail", "calendar", "ntfy"].includes(c.tool.split(".")[0]));
  const actions = data.transcript.calls.filter(
    (c) => ["slack", "gmail", "calendar", "ntfy"].includes(c.tool.split(".")[0]));

  // ---- evidence chain, revealed at the pace it actually ran
  const chain = document.createElement("section");
  chain.className = "panel glass reveal";
  chain.innerHTML = `<h2>Evidence chain</h2><div class="chain" id="chain">
    <div class="node"><span class="mark">●</span><span class="what">Caller report</span></div>
    <div class="node"><span class="rule">↓</span>
      <span class="detail">${esc(data.incident.description)}</span></div>
  </div>`;
  out.appendChild(chain);
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

  states.investigate = "done";
  states.reason = "active";
  drawRail(states);
  await sleep(260);

  // ---- the picture
  const b = data.brief;
  if (b.picture) out.appendChild(picturePanel(b, data));
  if (b.picture && (b.picture.ledger || []).length) out.appendChild(ledgerPanel(b.picture));

  states.reason = "done";
  states.decide = data.refused ? "blocked" : "done";
  drawRail(states);
  await sleep(200);

  if (data.refused) {
    out.insertAdjacentHTML("afterbegin", `
      <div class="refusal glass reveal">
        <h2>Workflow not executed</h2>
        <p>${esc(data.refused)}</p>
      </div>`);
    states.act = "blocked";
  } else if (actions.length) {
    out.appendChild(actionsPanel(actions));
    states.act = "done";
  }
  drawRail(states);
  await sleep(200);

  out.appendChild(metricsPanel(data));
  states.document = "done";
  drawRail(states);
}

const SECTIONS = [
  ["situation", "Situation", ""],
  ["people", "People", ""],
  ["threats", "Threats", "— can make this worse"],
  ["exposures", "Exposures", "— at risk if this spreads"],
  ["resources", "Resources", ""],
  ["approach", "Approach", "— second agent: upwind side, plume, water"],
  ["open_questions", "Open questions", "— no source can settle these before arrival"],
];

function picturePanel(brief, data) {
  const p = brief.picture;
  const body = SECTIONS.map(([key, title, why]) => {
    const items = p[key] || [];
    if (!items.length) return "";
    return `<div class="section"><h3>${title} <span class="why">${why}</span></h3>
      ${items.map((a) => `
        <div class="row">
          <span class="state" data-s="${esc(a.status)}">${esc(a.status)}</span>
          <span class="field">${esc(a.field)}</span>
          <span class="value">${a.value ? esc(a.value) : '<span class="none">not established</span>'}
            ${(a.evidence_ids || []).map((id) => `<span class="ev">${esc(id)}</span>`).join("")}
            <span class="cite">${esc(a.source || a.evidence)}</span></span>
        </div>`).join("")}
    </div>`;
  }).join("");

  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>${esc(brief.priority)} — ${esc(brief.headline)}
    <span class="qualifier">· ${esc(brief.address)}</span></h2>${body}
    <p class="footnote">Advisory only. Argus does not dispatch; a human decides.</p>`;
  return panel;
}

function ledgerPanel(picture) {
  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>Evidence ledger
      <span class="qualifier">· every verified claim points at a row here</span></h2>
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
  const panel = document.createElement("section");
  panel.className = "panel glass reveal";
  panel.innerHTML = `<h2>Actions</h2><div class="chain">${actions.map((a) => `
    <div class="node"><span class="mark ${a.ok ? "" : "bad"}">${a.ok ? "✓" : "✗"}</span>
      <span class="what">${esc(a.tool)}
        ${a.rehearsed ? '<span class="sought">— rehearsed, not delivered</span>' : ""}</span></div>
    <div class="node"><span class="rule">↓</span>
      <span class="detail">${esc(a.summary)}</span></div>`).join("")}</div>`;
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
      <div class="v ${tone}">${v}</div></div>`).join("")}</div>
    <p class="footnote">Open questions are counted as a result, not a gap:
      they are what no desk can answer before a crew arrives.</p>`;
  return panel;
}

async function integrations() {
  try {
    const res = await fetch("/api/integrations");
    const items = await res.json();
    const live = items.filter((i) => i.live).length;
    $("integrations").innerHTML =
      `<b>${live}/${items.length}</b> integrations live` +
      (live < items.length ? " · rest rehearsing" : "");
  } catch { /* header detail only; never block the run */ }
}

$("form").addEventListener("submit", (e) => { e.preventDefault(); run($("text").value); });
$("fail").addEventListener("click", () => {
  $("text").value = "Fire at 999999 Unknown Avenue, San Francisco";
  run($("text").value);
});

drawRail();
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
