// Saturday Multiverse — side panels & settings UI.
import { apiGet, apiSend } from "./api.js?v=30";
import { state, emit } from "./state.js?v=30";
import { portraitSVG } from "./portraits.js?v=30";
import { audio } from "./audio.js?v=30";

const root = document.getElementById("panel-root");
const settingsRoot = document.getElementById("settings-root");
const panelTitle = document.getElementById("panel-title");
const panelBody = document.getElementById("panel-body");
const settingsBody = document.getElementById("settings-body");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- drawer plumbing ----------
export function openPanel(name) {
  panelTitle.textContent = { map: "Map of the Shore", journal: "Journal Log", inventory: "Pack",
    quests: "Quests & Mysteries", dice: "Dice Log", character: "Character",
    ledger: "The Memory Ledger", omens: "The Omen Deck", shore: "The Growing Shore",
    worlds: "Known Worlds", party: "The Party", combat: "Combat",
    director: "The Living Director" }[name] || "Panel";
  panelBody.innerHTML = { map: panelMap, journal: panelJournal, inventory: panelInventory,
    quests: panelQuests, dice: panelDice, character: panelCharacter,
    ledger: panelLedger, omens: panelOmens, shore: panelShore, worlds: panelWorlds,
    party: panelParty, combat: panelCombat, director: panelDirector }[name]?.() || "";
  wirePanel(name);
  root.hidden = false;
  audio.ui();
  if (name === "ledger" || name === "shore" || name === "party") refreshPanelExtras(name);
  if (name === "ledger") {
    refreshCheckpoints?.();
    document.querySelector("[data-cp-save]")?.addEventListener("click", async () => {
      try {
        await apiSend(`/api/campaigns/${window.__campaignId}/checkpoints`, "POST", { name: "manual checkpoint" });
        window.__toast?.("Checkpoint saved.", "good");
        refreshCheckpoints?.();
      } catch (e) { window.__toast?.(e.message, "bad"); }
    });
  }
  if (name === "combat") refreshCombatPanel();
  if (name === "director") refreshDirectorPanel();
  if (name === "party") refreshPartySplit?.();
}

export function closePanel() { root.hidden = true; }

export function openSettings() {
  settingsBody.innerHTML = settingsHTML();
  wireSettings();
  settingsRoot.hidden = false;
  audio.ui();
}

export function closeSettings() { settingsRoot.hidden = true; }

// ---------- shared bits ----------
const kindLabel = { tool: "tool", weapon: "weapon", light: "light", charm: "charm", provision: "provision", relic: "relic", key: "key", lore: "lore" };

function itemRow(i) {
  const use = i.item?.use;
  const usable = use && (use.text || use.heal || use.fact || use.flag);
  return `<div class="item-row">
    <span class="item-kind">${kindLabel[i.kind] || i.kind}</span>
    <span class="item-name">${esc(i.name)}${i.qty > 1 ? ` ×${i.qty}` : ""}</span>
    ${usable ? `<button class="btn btn-small" data-use="${esc(i.item_id)}">Use</button>` : ""}
    <button class="btn btn-small btn-ghost" data-inspect="${esc(i.item_id)}">?</button>
    <span class="item-desc">${esc(i.item?.desc || "")}</span>
  </div>`;
}

// ---------- panels ----------
function panelCharacter() {
  const v = state.view;
  const ch = v.character;
  return `
  <div class="sect" style="display:flex; gap:1em; align-items:center;">
    <div class="portrait-frame" style="width:110px">${portraitSVG(ch.portrait.seed, ch.portrait.palette, ch.archetype)}</div>
    <div>
      <h3 style="margin:0">${esc(ch.name)}</h3>
      <div style="color:var(--dim)">${esc(ch.archetype)} · ${esc(v.pack.name)}</div>
      <div style="margin-top:0.5em">
        Vigor <strong style="color:var(--teal)">${ch.vigor}/${ch.vigor_max}</strong> ·
        Nerve <strong style="color:var(--glow)">${ch.nerve}/${ch.nerve_max}</strong>
      </div>
    </div>
  </div>
  <div class="sect"><h4>Stats</h4>
    ${Object.entries(ch.attributes).map(([k, n]) => `<span class="chip" style="margin-right:0.4em">${k} ${n >= 0 ? "+" : ""}${n}</span>`).join("")}
  </div>
  <div class="sect"><h4>Skills</h4>
    ${Object.entries(ch.skills).map(([k, n]) => `<span class="chip" style="margin-right:0.4em">${k} ${n ? "+1" : "—"}${ch.data.specialty === k ? " ★" : ""}</span>`).join("")}
  </div>
  <div class="sect"><h4>What the shore knows about you</h4>
    ${v.facts.length ? v.facts.map((f) => `<div class="fact-line">· ${esc(f)}</div>`).join("") : "<div class='fact-line'>Nothing yet. The shore is patient.</div>"}
  </div>
  <div class="sect"><h4>Companions & strangers</h4>
    ${v.npcs.length ? v.npcs.map((n) => `<div class="npc-row"><strong>${esc(n.name)}</strong><span class="npc-rel">${n.rel > 0 ? "+" : ""}${n.rel}</span></div>`).join("") : "<div class='fact-line'>You have met no one worth remembering. Yet.</div>"}
  </div>`;
}

function panelInventory() {
  const v = state.view;
  const items = v.inventory;
  if (!items.length) return "<div class='fact-line'>Your pack is empty. The sea provides — eventually.</div>";
  return items.map(itemRow).join("") +
    `<div class="sect" style="margin-top:1.2em"><h4>Scanned sigils</h4>
     <div class="fact-line">Scan a QR card (or paste its code anywhere) to inspect artifacts, trigger approved events, or open panels. See Settings → QR cards.</div></div>`;
}

function panelJournal() {
  const v = state.view;
  return `
  <div class="setting-row">
    <input id="journal-input" class="input" placeholder="Add a note to the journal…" maxlength="600">
    <button id="journal-add" class="btn btn-small btn-primary">Write</button>
  </div>
  <div class="setting-row">
    <input id="journal-search" class="input" placeholder="Search everything that has happened…" maxlength="120">
    <div id="journal-results"></div>
  </div>
  <div class="sect" id="journal-entries">
    ${v.journal.length ? v.journal.map((j) => `
      <div class="journal-entry kind-${esc(j.kind)}">
        <span class="je-kind">${esc(j.kind)} · ${esc((j.ts || "").slice(0, 16).replace("T", " "))}</span>
        <div class="je-text">${esc(j.text)}</div>
      </div>`).join("") : "<div class='fact-line'>The journal is blank sand. Walk a while.</div>"}
  </div>`;
}

function panelQuests() {
  const v = state.view;
  return `
  <div class="sect"><h4>Quests</h4>
    ${v.quests.length ? v.quests.map((q) => `
      <div class="quest-row"><strong>${esc(q.title)}</strong>
        <span class="q-status ${esc(q.status)}">${esc(q.status)}</span></div>
      ${q.notes?.length ? `<div class="fact-line" style="margin-left:1em">${esc(q.notes.join(" · "))}</div>` : ""}`).join("")
      : "<div class='fact-line'>No obligations. The door is patient.</div>"}
  </div>
  <div class="sect"><h4>The tide</h4>
    <div class="fact-line">${v.tide === "low" ? "Low tide — the cave and the Marrow Bell wreck are showing." : "High tide — hidden places keep their secrets for now."}</div>
    <div class="fact-line">Weather: ${esc(v.weather?.desc || "—")}</div>
    <div class="fact-line">Turn ${v.turn} · endings witnessed: ${v.endings_seen.length ? v.endings_seen.map(esc).join(", ") : "none"}</div>
  </div>`;
}

function panelDice() {
  const v = state.view;
  return `
  <div class="sect"><h4>Recent rolls</h4>
    ${v.dice_log.length ? v.dice_log.map((d) => `
      <div class="dice-row">
        <span style="color:var(--faint)">${esc((d.ts || "").slice(11, 19))}</span>
        <strong>${esc(d.skill || "roll")}</strong>
        <span>[${d.dice.join(" · ")}] → <strong>${d.total}</strong></span>
        <span class="dr-outcome outcome-${esc(d.outcome)}">${esc(d.outcome)}</span>
      </div>`).join("") : "<div class='fact-line'>No dice yet.</div>"}
  </div>
  <div class="sect"><h4>Manual check</h4>
    <div class="setting-row">
      <select id="dice-skill" class="input" style="max-width:12em">
        ${["notice", "lore", "persuade", "fight", "endure", "bind"].map((s) => `<option>${s}</option>`).join("")}
      </select>
      <label style="display:flex;gap:0.4em;align-items:center;color:var(--dim);font-size:0.85em">
        <input type="checkbox" id="dice-hard"> hard (−1 band)
      </label>
      <label style="display:flex;gap:0.4em;align-items:center;color:var(--gold);font-size:0.85em" title="+2 to the roll, but any failure deals 2 extra harm">
        <input type="checkbox" id="dice-risk"> risk it (+2 / fail hurts)
      </label>
      <button id="dice-roll" class="btn btn-small btn-primary">Roll 2d6</button>
    </div>
  </div>
  <div class="sect"><h4>Last omen</h4>
    ${v.omen ? `<div class="omen-card"><span class="omen-kind">${esc(v.omen.kind)}</span> — <strong>${esc(v.omen.title)}</strong><br>${esc(v.omen.text)}</div>` : "<div class='fact-line'>The deck is quiet.</div>"}
  </div>`;
}

const MAP_POS = {
  tidegate: [46, 46], camp: [22, 62], tavern: [34, 55], lighthouse: [80, 30],
  seacave: [68, 38], wreck: [63, 68], saltgrave_gate: [58, 14], umbral_reach: [24, 14],
  ninth_wave: [12, 40], "": [50, 50],
};

function panelMap() {
  const v = state.view;
  const here = v.location?.id;
  const pins = (v.pack?.locations || []).concat(v.world ? [{
    id: v.world.id, name: v.world.name,
  }] : []);
  const disc = v.discovered || {};
  const svgPins = pins.map((l) => {
    const [px, py] = MAP_POS[l.id] || [50, 50];
    const known = l.id === here || disc[l.id] || ["tidegate", "camp", "tavern"].includes(l.id) || l.id === v.world?.id;
    const isHere = l.id === here;
    const color = isHere ? "#43e8d8" : known ? "#9b8cff" : "#4a4560";
    const label = known ? l.name : "unmarked";
    return `<g class="map-pin" data-travel="${esc(l.id)}" data-locked="${!known}">
      <circle class="pin-ring" cx="${px}" cy="${py}" r="3.4" fill="none" stroke="${color}" stroke-width="0.4" opacity="0.35"/>
      <circle cx="${px}" cy="${py}" r="1.5" fill="${color}"/>
      ${isHere ? `<circle cx="${px}" cy="${py}" r="2.8" fill="none" stroke="#43e8d8" stroke-width="0.4"><animate attributeName="r" values="2.4;4.4;2.4" dur="2.4s" repeatCount="indefinite"/></circle>` : ""}
      <text x="${px}" y="${py - 4}" text-anchor="middle" font-size="3" fill="${isHere ? "#43e8d8" : "#9d96b8"}" font-family="Georgia,serif">${esc(label)}</text>
    </g>`;
  }).join("");
  return `
  <div class="map-wrap">
    <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" style="aspect-ratio:1">
      <defs><linearGradient id="seaG" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#120e24"/><stop offset="100%" stop-color="#1c1440"/></linearGradient></defs>
      <rect width="100" height="100" fill="url(#seaG)"/>
      <path d="M8 72 Q22 52 40 58 Q58 64 74 48 Q84 40 94 44 L94 96 L8 96Z" fill="#171223"/>
      <path d="M8 72 Q22 52 40 58 Q58 64 74 48 Q84 40 94 44" fill="none" stroke="#43e8d8" stroke-width="0.5" opacity="0.5"/>
      <line x1="4" y1="24" x2="96" y2="18" stroke="#9b8cff" stroke-width="0.6" opacity="0.55"/>
      <text x="50" y="12" text-anchor="middle" font-size="4.4" fill="#9b8cff" opacity="0.8" font-family="Georgia,serif">the Beam</text>
      <text x="50" y="88" text-anchor="middle" font-size="4.4" fill="#6b6584" font-family="Georgia,serif">the Living Shore</text>
      ${svgPins}
    </svg>
  </div>
  <div class="fact-line" style="margin-top:0.8em">Click a marked place to walk there. The Beam carries four doors: two open, one sealed — and the Unstable Door, which opens for whispered seeds.</div>
  <div class="fact-line">${v.tide === "low" ? "Low tide: the cave and the wreck are reachable." : "High tide: the cave and the wreck are under water."}
  ${v.tide_phase ? `Tide changes in ${v.tide_phase.beats_to_change} beats.` : ""}</div>`;
}

// ---------- M1.5 / 2.0 / 2.5 panels ----------
let ledgerCache = null;

async function refreshPanelExtras(name) {
  if (name === "ledger") {
    try {
      ledgerCache = await apiGet(`/api/campaigns/${state.view.id}/ledger`);
      const box = panelBody.querySelector("#ledger-body");
      if (box) box.innerHTML = ledgerHTML(ledgerCache);
      wireLedger();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  } else if (name === "shore") {
    try {
      const res = await apiGet(`/api/campaigns/${state.view.id}/upgrades`);
      const box = panelBody.querySelector("#shore-body");
      if (box) box.innerHTML = shoreHTML(res);
      wireShore();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  } else if (name === "party") {
    try {
      const v = await apiGet(`/api/mp/view/${state.view.id}`);
      window.__mpSession = v;
      const box = panelBody.querySelector("#party-body");
      if (box) box.innerHTML = partyHTML(v);
      wireParty();
    } catch (e) {
      const box = panelBody.querySelector("#party-body");
      if (box) box.innerHTML = `<div class="fact-line">${esc(e.message)}</div>`;
    }
  }
}

function panelParty() {
  return `<div id="party-body"><div class="fact-line">Gathering the party…</div></div>`;
}

function partyHTML(v) {
  const me = v.you;
  const roster = (v.members || []).map((m) => {
    const ch = m.character || {};
    return `
    <div class="ledger-card ${m.presence === "connected" ? "card-paid" : "card-used"}">
      <div class="lc-kind">${m.is_host ? "host · " : ""}${esc(m.presence)}${m.status === "pending" ? " · awaiting welcome" : ""}</div>
      <div style="display:flex;gap:0.7em;align-items:flex-start;justify-content:space-between">
        <div>
          <strong>${esc(m.name)}</strong>
          <div class="fact-line">${esc(ch.name || "—")} · ${esc(ch.archetype || "")} · ♥${ch.vigor ?? "?"}/${ch.vigor_max ?? "?"} ✦${ch.nerve ?? "?"}/${ch.nerve_max ?? "?"}</div>
          <div class="fact-line" style="color:${esc(m.color)}">their color on the shore</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:0.3em">
          ${m.player_id !== me.player_id ? `
            <button class="btn btn-small" data-gift="${esc(m.player_id)}" data-gname="${esc(m.name)}">Gift beads</button>
            <button class="btn btn-small btn-ghost" data-trade-to="${esc(m.player_id)}" data-tname="${esc(m.name)}">Offer item</button>
            ${me.is_host ? `<button class="btn btn-small btn-ghost" data-kick="${esc(m.player_id)}">Send away</button>` : ""}
            ${me.is_host && m.status === "pending" ? `<button class="btn btn-small btn-primary" data-approve="${esc(m.player_id)}">Welcome</button>` : ""}` : ""}
        </div>
      </div>
    </div>`;
  }).join("");
  const offers = (v.offers_for_you || []).map((o) => `
    <div class="ledger-card card-paid">
      <div class="lc-kind">offer for you</div>
      <strong>${esc(o.item_name)} ×${o.qty}</strong>
      <div class="fact-line">from ${esc(o.from_name)}</div>
      <button class="btn btn-small btn-primary" data-offer-accept="${esc(o.id)}">Accept</button>
      <button class="btn btn-small btn-ghost" data-offer-decline="${esc(o.id)}">Decline</button>
    </div>`).join("");
  const splitControls = `
    <div class="sect"><h4>Walk apart / gather</h4>
      <div class="fact-line">Splitting is individual; shared travel always regroups the party.</div>
      <div class="chip-row" id="split-locations"></div>
      <div class="setting-row">
        <button class="btn btn-small" data-split="1">Walk apart to the chosen place</button>
        <button class="btn btn-small btn-ghost" data-regroup="1">Return to the party</button>
        ${me.is_host ? `<button class="btn btn-small btn-ghost" data-regroup-all="1">Gather everyone (host)</button>` : ""}
        ${me.is_host ? `<button class="btn btn-small btn-ghost" data-spectator-invite="1">Invite a spectator</button>` : ""}
      </div>
    </div>`;
  const hostTools = me.is_host ? `
    <div class="sect"><h4>Host controls</h4>
      <div class="chip-row">
        <span class="chip ${v.mode === "freeform" ? "selected" : ""}" data-mode="freeform">freeform</span>
        <span class="chip ${v.mode === "turns" ? "selected" : ""}" data-mode="turns">turn order</span>
      </div>
      <div class="setting-row">
        <button class="btn btn-small" data-session="pause">Pause</button>
        <button class="btn btn-small" data-session="resume">Resume</button>
        <button class="btn btn-small btn-ghost" data-session="end">End the voyage</button>
      </div>
      <div class="fact-line">Invitations: ${(v.invites || []).map((i) =>
        `#${i.id.slice(-4)} ${i.revoked ? "(revoked)" : i.expires_at ? "(expires " + i.expires_at.slice(0, 10) + ")" : "(open)"}`).join(", ") || "none yet"}</div>
    </div>` : "";
  return `
  <div class="sect"><h4>Together on the shore</h4>${roster}</div>
  ${offers ? `<div class="sect"><h4>Offers waiting for you</h4>${offers}</div>` : ""}
  ${hostTools}
  <div class="sect"><h4>Trade & gifts</h4>
    <div class="fact-line">Use the buttons beside each traveler. Trades need their consent;
    glassbead gifts are immediate, 1–10 beads. Contributions to shared shore improvements
    live on the Shore panel.</div>
  </div>`;
}

function wireParty() {
  const v = window.__mpSession || {};
  panelBody.querySelectorAll("[data-kick]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await apiSend(`/api/mp/players/${state.view.id}/remove`, "POST", { player_id: b.dataset.kick });
      refreshPanelExtras("party");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  panelBody.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await apiSend(`/api/mp/players/${state.view.id}/approve`, "POST", { player_id: b.dataset.approve });
      refreshPanelExtras("party");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  panelBody.querySelectorAll("[data-mode]").forEach((c) => c.addEventListener("click", async () => {
    try {
      await apiSend("/api/mp/settings", "POST", { campaign_id: state.view.id, mode: c.dataset.mode });
      window.__toast?.(`Turn order: ${c.dataset.mode}.`, "good");
      refreshPanelExtras("party");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  panelBody.querySelectorAll("[data-session]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await apiSend("/api/mp/session", "POST", { campaign_id: state.view.id, action: b.dataset.session });
      window.__toast?.(`Voyage ${b.dataset.session}.`, "good");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  panelBody.querySelectorAll("[data-gift]").forEach((b) => b.addEventListener("click", () => {
    const amount = prompt(`Gift how many glassbeads to ${b.dataset.gname}? (1–10)`);
    if (!amount) return;
    apiSend("/api/mp/gift", "POST", { campaign_id: state.view.id, to_player: b.dataset.gift,
                                      amount: parseInt(amount, 10) })
      .then((r) => { window.__toast?.(r.narration, "good"); window.__refreshView?.(); refreshPanelExtras("party"); })
      .catch((e) => window.__toast?.(e.message, "bad"));
  }));
  panelBody.querySelectorAll("[data-trade-to]").forEach((b) => b.addEventListener("click", () => {
    const inv = state.view.inventory || [];
    if (!inv.length) { window.__toast?.("Your pack is empty.", "bad"); return; }
    const list = inv.map((i, idx) => `${idx}: ${i.name} ×${i.qty}`).join("\n");
    const pick = prompt(`Offer which item to ${b.dataset.tname}?

${list}

Enter the number:`);
    if (pick === null) return;
    const row = inv[parseInt(pick, 10)];
    if (!row) return;
    apiSend("/api/mp/trade", "POST", { campaign_id: state.view.id, to_player: b.dataset.tradeTo,
                                       item_row_id: row.id, qty: 1 })
      .then((r) => { window.__toast?.(r.narration, "good"); })
      .catch((e) => window.__toast?.(e.message, "bad"));
  }));
  panelBody.querySelectorAll("[data-offer-accept]").forEach((b) => b.addEventListener("click", () => {
    apiSend("/api/mp/trade/respond", "POST", { campaign_id: state.view.id, offer_id: b.dataset.offerAccept, accept: true })
      .then((r) => { window.__toast?.(r.narration, "good"); window.__refreshView?.(); refreshPanelExtras("party"); })
      .catch((e) => window.__toast?.(e.message, "bad"));
  }));
  panelBody.querySelectorAll("[data-offer-decline]").forEach((b) => b.addEventListener("click", () => {
    apiSend("/api/mp/trade/respond", "POST", { campaign_id: state.view.id, offer_id: b.dataset.offerDecline, accept: false })
      .then(() => { refreshPanelExtras("party"); })
      .catch((e) => window.__toast?.(e.message, "bad"));
  }));
}

function panelLedger() {
  return `<div id="ledger-body"><div class="fact-line">Opening the ledger…</div></div>
    <div class="sect"><h4>Checkpoints</h4>
      <div class="setting-row"><button class="btn btn-small" data-cp-save="1">Save a checkpoint</button></div>
      <div id="checkpoint-body"><div class="fact-line">…</div></div></div>`;
}

function ledgerHTML(led) {
  const worldCards = led.worlds.map((w) => `
    <div class="ledger-card card-world">
      <div class="lc-kind">world · visited ${w.visits}×</div>
      <strong>${esc(w.name)}</strong>
      <div class="fact-line">${esc(w.archetype)} · seed: “${esc(w.seed)}”</div>
      ${w.hooks?.length ? `<div class="fact-line" style="color:var(--gold)">hook: ${esc(w.hooks[0])}</div>` : ""}
      <button class="btn btn-small" data-world-seed="${esc(w.seed)}">The door remembers</button>
    </div>`).join("") || "<div class='fact-line'>No worlds discovered yet. Whisper a seed at the Unstable Door.</div>";

  const people = led.people.map((p) => `
    <div class="npc-row"><strong>${esc(p.name)}</strong>
      <span class="npc-rel">${p.reputation ? "reputation" : p.met ? `rel ${p.rel > 0 ? "+" : ""}${p.rel}` : "has heard of you"}</span></div>`).join("")
    || "<div class='fact-line'>No one worth remembering yet.</div>";

  const threads = led.threads.map((t) => `
    <div class="ledger-card ${t.paid ? "card-paid" : ""}">
      <div class="lc-kind">mystery · ${t.count}/${t.threshold} clues</div>
      <strong>${esc(t.title)}</strong> ${t.paid ? `<span class="chip good">paid off</span>` : ""}
      ${t.clues.map((c) => `<div class="fact-line">· ${esc(c.text)}</div>`).join("")}
    </div>`).join("") || "<div class='fact-line'>No mysteries yet.</div>";

  const cons = led.consequences.map((c) => `
    <div class="fact-line" style="color:var(--gold)">◈ ${esc(c.summary)}</div>`).join("")
    || "<div class='fact-line'>No echoes between worlds yet.</div>";

  const echoes = led.echoes.map((e) => `
    <div class="ledger-card ${e.used_in ? "card-used" : "card-paid"}">
      <div class="lc-kind">echo · ${esc(e.kind)}${e.used_in ? " · woven into a later voyage" : " · waiting"}</div>
      <strong>${esc(e.title)}</strong>
      <div class="fact-line">${esc(e.detail)}</div>
    </div>`).join("") || "<div class='fact-line'>No echoes yet — finish an adventure to leave one.</div>";

  const memories = led.memories.slice(0, 14).map((m) => `
    <div class="fact-line"><span style="color:var(--faint)">[${esc(m.kind)}]</span> ${esc(m.text)}</div>`).join("");

  return `
  <div class="sect"><h4>Known worlds</h4><div class="card-grid">${worldCards}</div></div>
  <div class="sect"><h4>People</h4>${people}</div>
  <div class="sect"><h4>Mysteries & threads</h4>${threads}</div>
  <div class="sect"><h4>Cross-world consequences</h4>${cons}</div>
  <div class="sect"><h4>Echoes</h4><div class="card-grid">${echoes}</div></div>
  <div class="sect"><h4>What the tavern talks about</h4>${memories}</div>
  <div class="sect"><h4>Chronological log</h4>
    ${state.view.journal.map((j) => `
      <div class="journal-entry kind-${esc(j.kind)}">
        <span class="je-kind">${esc(j.kind)} · ${esc((j.ts || "").slice(0, 16).replace("T", " "))}</span>
        <div class="je-text">${esc(j.text)}</div>
      </div>`).join("")}
  </div>`;
}

function wireLedger() {
  panelBody.querySelectorAll("[data-world-seed]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/worlds`, "POST", { seed: b.dataset.worldSeed });
      if (res.entry_location) { closePanel(); window.__travel?.(res.entry_location); }
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
}

function panelOmens() {
  const v = state.view;
  const hand = v.omen_hand || { hand: [], draws_left: 0, hand_max: 2 };
  return `
  <div class="sect"><h4>Your hand — ${hand.hand.length}/${hand.hand_max} held</h4>
    <div class="fact-line">Drawing costs 1 Nerve; the deck gives ${hand.draws_left} more until you rest.
    Edges grant +1 on their skill when played; turn-cards steady you. Complications play themselves.</div>
    <div id="omen-hand-box">
      ${hand.hand.map((c) => `
        <div class="ledger-card ${c.kind === "edge" ? "card-paid" : ""}">
          <div class="lc-kind">${esc(c.kind)}</div>
          <strong>${esc(c.title)}</strong>
          <div class="fact-line">${esc(c.text)}</div>
          ${c.kind !== "complication" ? `<button class="btn btn-small" data-play-omen="${esc(c.id)}">Play</button>` : `<div class="fact-line" style="color:var(--danger)">it will land when it lands</div>`}
        </div>`).join("") || "<div class='fact-line'>Your hand is empty.</div>"}
    </div>
    <div class="setting-row">
      <button id="omen-draw" class="btn btn-small btn-primary" ${hand.draws_left > 0 ? "" : "disabled"}>Draw an omen (1 Nerve)</button>
    </div>
  </div>
  <div class="sect"><h4>Last drawn by the tide</h4>
    ${v.omen ? `<div class="omen-card"><span class="omen-kind">${esc(v.omen.kind)}</span> — <strong>${esc(v.omen.title)}</strong><br>${esc(v.omen.text)}</div>`
      : "<div class='fact-line'>The deck is quiet.</div>"}
  </div>`;
}

function panelShore() {
  return `<div id="shore-body"><div class="fact-line">Surveying the shore…</div></div>`;
}

function shoreHTML(res) {
  return `
  <div class="sect"><h4>Glassbeads: ${res.beads}</h4>
    <div class="fact-line">The shore's small coin — sea-glass polished by the Beam. Adventure endings,
    wash-ashore finds and worlds pay in beads. Build improvements where they belong: stand at the
    camp, the tavern, or the lighthouse to build there.</div>
  </div>
  ${res.upgrades.map((u) => `
    <div class="ledger-card ${u.owned ? "card-paid" : ""}">
      <div class="lc-kind">${esc(u.location)} · ${u.owned ? "built" : `${u.cost} glassbeads`}</div>
      <strong>${esc(u.name)}</strong>
      <div class="fact-line">${esc(u.desc)}</div>
      ${!u.owned && u.affordable ? `<button class="btn btn-small btn-primary" data-build="${esc(u.id)}">Build here</button>` : ""}
      ${!u.owned && !u.affordable ? `<div class="fact-line" style="color:var(--faint)">needs ${u.cost - res.beads} more bead${u.cost - res.beads === 1 ? "" : "s"}${u.location !== state.view.location?.id ? ` · travel to the ${esc(u.location)}` : ""}</div>` : ""}
    </div>`).join("")}`;
}

function wireShore() {
  panelBody.querySelectorAll("[data-build]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/upgrades`, "POST", { upgrade_id: b.dataset.build });
      window.__toast?.(res.narration, "good");
      window.__refreshView?.();
      refreshPanelExtras("shore");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
}

function panelWorlds() {
  return `<div id="ledger-body"><div class="fact-line">Opening the worlds list…</div></div>`;
}

// ---------- talk (M1.5) ----------
export async function openTalk(npcId) {
  const v = state.view;
  const byLocation = { tavern: "maren", camp: "old_cardo", umbral_reach: "ledger_keeper" };
  const who = npcId || byLocation[v.location?.id];
  if (!who) return;
  panelTitle.textContent = "A conversation";
  panelBody.innerHTML = `
    <div id="talk-box"><div class="fact-line">Listening…</div></div>
    <div class="chip-row" id="talk-topics">
      ${["what's new", "rumors", "the shore"].map((t) => `<span class="chip" data-topic="${esc(t)}">${esc(t)}</span>`).join("")}
    </div>`;
  root.hidden = false;
  await loadTalk(who, "what's new");
  panelBody.querySelectorAll("[data-topic]").forEach((c) =>
    c.addEventListener("click", () => loadTalk(who, c.dataset.topic)));
  audio.ui();
}

async function loadTalk(npcId, topic) {
  const box = panelBody.querySelector("#talk-box");
  try {
    const res = await apiSend(`/api/campaigns/${state.view.id}/talk`, "POST", { npc_id: npcId, topic });
    box.innerHTML = res.lines.map((l) => `
      <div class="journal-entry" style="border-color:var(--gold)">
        <span class="je-kind">${esc(res.npc.name)}${res.meta.ai_used ? "" : " · offline voice"}</span>
        <div class="je-text" style="font-family:var(--serif)">${esc(l)}</div>
      </div>`).join("");
  } catch (e) { if (box) box.innerHTML = `<div class="fact-line">${esc(e.message)}</div>`; }
}

// ---------- seed gate (M2.0) ----------
export async function openSeedGate() {
  const seedRoot = document.getElementById("seed-root");
  const body = document.getElementById("seed-body");
  let suggestions = [];
  try { suggestions = (await apiGet("/api/seeds/suggest")).suggestions; } catch { /* ignore */ }
  let worlds = [];
  try { worlds = (await apiGet(`/api/campaigns/${state.view.id}/worlds`)).worlds; } catch { /* ignore */ }
  body.innerHTML = `
    <div class="fact-line">The Unstable Door is half-here. Whisper a seed — a word, a name, a short
    phrase — and somewhere new answers. The same seed always opens the same world, and the world
    remembers you between visits.</div>
    <div class="setting-row">
      <input id="seed-input" class="input" maxlength="120" placeholder="whisper a seed… (e.g. Clockwork Ocean)">
      <button id="seed-open" class="btn btn-primary btn-small">Open the door</button>
    </div>
    <div class="chip-row">${suggestions.map((s) => `<span class="chip" data-seed="${esc(s)}">${esc(s)}</span>`).join("")}</div>
    <div id="seed-result" style="margin-top:0.8em"></div>
    <div class="sect"><h4>Worlds already discovered (${worlds.length})</h4>
      ${worlds.map((w) => `
        <div class="ledger-card"><div class="lc-kind">visited ${w.visits}×</div>
        <strong>${esc(w.name)}</strong> <span class="fact-line">seed “${esc(w.seed)}”</span>
        <button class="btn btn-small" data-return-world="${esc(w.seed)}">Return</button></div>`).join("")
        || "<div class='fact-line'>None yet. The first seed costs nothing but a whisper.</div>"}
    </div>`;
  seedRoot.hidden = false;
  body.querySelectorAll("[data-seed]").forEach((c) => c.addEventListener("click", () => {
    body.querySelector("#seed-input").value = c.dataset.seed;
  }));
  body.querySelectorAll("[data-return-world]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/worlds`, "POST", { seed: b.dataset.returnWorld });
      document.getElementById("seed-root").hidden = true;
      window.__travel?.(res.entry_location);
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  body.querySelector("#seed-open").addEventListener("click", async () => {
    const inp = body.querySelector("#seed-input");
    const result = body.querySelector("#seed-result");
    if (!inp.value.trim()) return;
    result.innerHTML = "<div class='fact-line'>The door listens…</div>";
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/worlds`, "POST", { seed: inp.value });
      result.innerHTML = `
        <div class="omen-card"><strong>${esc(res.name)}</strong> — ${esc(res.archetype)}
        ${res.existing ? "· the door remembers this world" : "· a new world answers"}</div>
        <button id="seed-enter" class="btn btn-primary btn-small">Step through</button>`;
      result.querySelector("#seed-enter").addEventListener("click", () => {
        document.getElementById("seed-root").hidden = true;
        window.__travel?.(res.entry_location);
      });
    } catch (e) { result.innerHTML = `<div class="fact-line" style="color:var(--danger)">${esc(e.message)}</div>`; }
  });
  audio.ui();
}

// ---------- echoes (M2.5) ----------
export function showEchoOffers(offers) {
  const echoRoot = document.getElementById("echo-root");
  const body = document.getElementById("echo-body");
  body.innerHTML = `
    <div class="fact-line">This ending offered ${offers.length} echo${offers.length > 1 ? "es" : ""} — pieces of
    this journey the multiverse keeps. They are saved already. Begin a <strong>New Voyage</strong> and
    weave up to two of them into whoever walks the shore next.</div>
    ${offers.map((o) => `
      <div class="ledger-card card-paid"><div class="lc-kind">echo · ${esc(o.kind)}</div>
      <strong>${esc(o.title)}</strong><div class="fact-line">${esc(o.detail || "")}</div></div>`).join("")}
    <div class="setting-row"><button class="btn btn-small btn-primary" data-close-echo>Carry on</button></div>`;
  echoRoot.hidden = false;
  body.querySelectorAll("[data-close-echo]").forEach((el) => el.addEventListener("click", () => { echoRoot.hidden = true; }));
  audio.chime();
}

export async function openEchoShelf() {
  const echoRoot = document.getElementById("echo-root");
  const body = document.getElementById("echo-body");
  let echoes = [];
  try { echoes = (await apiGet("/api/echoes")).echoes; } catch { /* ignore */ }
  body.innerHTML = `
    <div class="fact-line">Echoes are what finished adventures leave behind. Up to two can be woven
    into a new voyage at character creation — each echo can only be woven once.</div>
    ${echoes.map((e) => `
      <div class="ledger-card ${e.used_in ? "card-used" : "card-paid"}">
        <div class="lc-kind">echo · ${esc(e.kind)} · ${e.used_in ? "woven" : "waiting"}</div>
        <strong>${esc(e.title)}</strong>
        <div class="fact-line">${esc(e.detail)}</div>
      </div>`).join("") || "<div class='fact-line'>The shelf is empty. Finish an adventure.</div>"}
    <div class="setting-row"><button class="btn btn-small" data-close-echo>Close</button></div>`;
  echoRoot.hidden = false;
  body.querySelectorAll("[data-close-echo]").forEach((el) => el.addEventListener("click", () => { echoRoot.hidden = true; }));
}

function wirePanel(name) {
  if (name === "party") {
    (async () => {
      try {
        const v = await apiGet(`/api/campaigns/${window.__campaignId}/view`);
        const pack = await apiGet("/api/packs");
        const box = document.getElementById("split-locations");
        if (box && pack) {
          box.innerHTML = (pack.packs || []).flatMap((pk) => (pk.locations || [])).length
            ? (pack.packs || []).filter((pk) => pk.id === (v.pack_id || "")).flatMap((pk) => (pk.locations || []))
                .map((l) => `<span class="chip" data-loc="${esc(l.id)}">${esc(l.name)}</span>`).join("")
            : "";
          let chosen = null;
          box.querySelectorAll("[data-loc]").forEach((c) => c.addEventListener("click", () => {
            box.querySelectorAll("[data-loc]").forEach((x) => x.classList.remove("selected"));
            c.classList.add("selected");
            chosen = c.dataset.loc;
          }));
          const act = (url, payload) => apiSend(url, "POST", payload)
            .then(() => { window.__toast?.("Done.", "good"); openPanel("party"); })
            .catch((e) => window.__toast?.(e.message, "bad"));
          document.querySelector("[data-split]")?.addEventListener("click", () => {
            if (!chosen) { window.__toast?.("Choose a place to walk to.", "bad"); return; }
            act(`/api/campaigns/${window.__campaignId}/mp/split`, { location_id: chosen });
          });
          document.querySelector("[data-regroup]")?.addEventListener("click", () =>
            act(`/api/campaigns/${window.__campaignId}/mp/regroup`, {}));
          document.querySelector("[data-regroup-all]")?.addEventListener("click", () =>
            act(`/api/campaigns/${window.__campaignId}/mp/regroup`, { everyone: true }));
          document.querySelector("[data-spectator-invite]")?.addEventListener("click", async () => {
            try {
              const inv = await apiSend(`/api/campaigns/${window.__campaignId}/mp/invite-spectator`, "POST", { uses: 3 });
              window.__toast?.(`Spectator link created (tell a friend): ${inv.token.slice(0, 8)}…`, "good");
            } catch (e) { window.__toast?.(e.message, "bad"); }
          });
        }
      } catch { /* not in a session */ }
    })();
  }

  panelBody.querySelectorAll("[data-use]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/use_item`, "POST", { item_id: b.dataset.use });
      window.__refreshView?.();
      window.__toast?.(res.narration, "good");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  panelBody.querySelectorAll("[data-inspect]").forEach((b) => b.addEventListener("click", () => {
    const it = state.view.inventory.find((x) => x.item_id === b.dataset.inspect);
    if (it) window.__toast?.(`${it.name} — ${it.item?.desc || ""}`, "good");
  }));
  panelBody.querySelectorAll(".map-pin[data-locked='false']").forEach((p) => p.addEventListener("click", () => {
    window.__travel?.(p.dataset.travel);
    closePanel();
  }));
  const ja = panelBody.querySelector("#journal-add");
  if (ja) ja.addEventListener("click", async () => {
    const inp = panelBody.querySelector("#journal-input");
    if (!inp.value.trim()) return;
    try { await apiSend(`/api/campaigns/${state.view.id}/journal`, "POST", { text: inp.value }); inp.value = ""; window.__refreshView?.(); }
    catch (e) { window.__toast?.(e.message, "bad"); }
  });
  const js = panelBody.querySelector("#journal-search");
  if (js) {
    let timer = null;
    js.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (!js.value.trim()) { panelBody.querySelector("#journal-results").innerHTML = ""; return; }
        try {
          const res = await apiGet(`/api/campaigns/${state.view.id}/search?q=${encodeURIComponent(js.value)}`);
          panelBody.querySelector("#journal-results").innerHTML =
            res.results.map((r) => `<div class="journal-entry"><span class="je-kind">${esc(r.kind)}</span><div class="je-text">${esc(r.snippet)}</div></div>`).join("")
            || "<div class='fact-line'>Nothing found.</div>";
        } catch { /* ignore */ }
      }, 250);
    });
  }
  const roll = panelBody.querySelector("#dice-roll");
  if (roll) roll.addEventListener("click", async () => {
    const skill = panelBody.querySelector("#dice-skill").value;
    const hard = panelBody.querySelector("#dice-hard").checked;
    const risk = panelBody.querySelector("#dice-risk")?.checked || false;
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/check`, "POST", { skill, hard, risk });
      audio.dice();
      window.__showDice?.(res);
      window.__refreshView?.();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });
  panelBody.querySelectorAll("[data-play-omen]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/omen/play`, "POST", { card_id: b.dataset.playOmen });
      window.__toast?.(res.narration, "good");
      window.__refreshView?.();
      openPanel("omens");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  }));
  const omenDraw = panelBody.querySelector("#omen-draw");
  if (omenDraw) omenDraw.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/omen/draw`, "POST", {});
      audio.chime();
      window.__toast?.(res.narration, "good");
      window.__refreshView?.();
      openPanel("omens");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });
}

// ---------- settings ----------
function settingsHTML() {
  const v = state.view;
  return `
  <div class="setting-block">
    <h4>Game Master personality</h4>
    <div class="fact-line">The Game Master's voice — narration style and outcome lines. Personality never
    becomes rules authority: dice, state and consequences stay in the engine.</div>
    <div class="chip-row" id="gm-style-row">
      ${["classic", "grimdark", "cosmic", "noir", "whimsical", "mythic", "custom"].map((s) => `
        <span class="chip ${v.gm_style?.id === s ? "selected" : ""}" data-style="${s}">${s}</span>`).join("")}
    </div>
    <div class="setting-row" id="gm-custom-row" ${v.gm_style?.id === "custom" ? "" : "hidden"}>
      <input id="gm-custom-text" class="input" maxlength="400" placeholder="Describe the tone you want…"
             value="${esc(window.__gmCustomText || "")}">
    </div>
    <div class="setting-row"><button id="gm-style-save" class="btn btn-small btn-primary">Save persona</button></div>
  </div>

  <div class="setting-block">
    <h4>AI Game Master — any OpenAI-compatible endpoint</h4>
    <div class="fact-line">Works with local model servers (Ollama, LM Studio, llama.cpp, KoboldCpp, vLLM…) or remote providers. Your key stays in your local database and is never sent anywhere except the endpoint you configure.</div>
    <div class="setting-row"><label><input type="checkbox" id="ai-enabled" ${window.__aiCfg?.enabled ? "checked" : ""}> enable AI Game Master</label></div>
    <div class="setting-row"><label>Endpoint URL</label><input id="ai-url" class="input" placeholder="http://127.0.0.1:11434/v1" value="${esc(window.__aiCfg?.base_url || "")}"></div>
    <div class="setting-row"><label>Model name</label><input id="ai-model" class="input" placeholder="e.g. qwen2.5:7b  ·  gpt-4o-mini  ·  local-model" value="${esc(window.__aiCfg?.model || "")}"></div>
    <div class="setting-row"><label>API key (optional)</label><input id="ai-key" class="input" type="password" placeholder="${window.__aiCfg?.has_key ? "stored — type to replace" : "only if your provider needs one"}"></div>
    <div class="setting-row"><label>Creativity</label><input id="ai-temp" type="range" min="0.1" max="1.6" step="0.05" value="${esc(window.__aiCfg?.temperature ?? 0.8)}" style="flex:1"><span id="ai-temp-val">${esc(window.__aiCfg?.temperature ?? 0.8)}</span></div>
    <div class="setting-row"><label>Narration length</label><input id="ai-words" type="range" min="90" max="450" step="10" value="${esc(window.__aiCfg?.narration_words ?? 220)}" style="flex:1"><span id="ai-words-val">${esc(window.__aiCfg?.narration_words ?? 220)} words</span></div>
    <div class="setting-row">
      <button id="ai-save" class="btn btn-primary btn-small">Save</button>
      <button id="ai-test" class="btn btn-small">Test connection</button>
    </div>
    <div id="ai-status" class="ai-status" hidden></div>
  </div>

  <div class="setting-block">
    <h4>Sound & motion</h4>
    <div class="slider-row"><label>Music</label><input type="range" id="vol-music" min="0" max="1" step="0.05" value="${audio.prefs.music}"></div>
    <div class="slider-row"><label>Ambience</label><input type="range" id="vol-amb" min="0" max="1" step="0.05" value="${audio.prefs.amb}"></div>
    <div class="slider-row"><label>Effects</label><input type="range" id="vol-sfx" min="0" max="1" step="0.05" value="${audio.prefs.sfx}"></div>
    <div class="setting-row"><label><input type="checkbox" id="vol-mute" ${audio.prefs.muted ? "checked" : ""}> mute everything</label></div>
    <div class="setting-row"><label><input type="checkbox" id="calm-mode" ${localStorage.getItem("sm_calm") === "1" ? "checked" : ""}> calm mode (gentler animation, no rain)</label></div>
  </div>

  <div class="setting-block">
    <h4>Saves & data</h4>
    <div class="data-links">
      ${v ? `<a class="btn btn-small" href="/api/campaigns/${esc(v.id)}/export" download="export">Export this campaign (JSON)</a>` : ""}
      <button id="btn-backup" class="btn btn-small">Back up database</button>
      <label class="btn btn-small">Import campaign<input type="file" id="import-file" accept=".json" hidden></label>
      <button id="btn-qr-cards" class="btn btn-small btn-ghost">QR cards…</button>
    </div>
    <div id="backup-list" style="margin-top:0.7em"></div>
  </div>

  <div class="setting-block">
    <h4>QR & scanner cards</h4>
    <div class="fact-line">Scanners that emulate keyboards are supported automatically: just scan while playing. Payloads are data-only and must match the allowlist below — scanned codes can never execute anything on your machine.</div>
    <div class="fact-line" style="font-family:monospace">SM:CMD:INVENTORY · SM:CMD:JOURNAL · SM:CMD:MAP · SM:CMD:QUESTS · SM:CMD:REST<br>
    SM:ITEM:&lt;item_id&gt; · SM:LORE:&lt;lore_id&gt; · SM:EVT:&lt;event_id&gt;</div>
    <div class="fact-line">Generate printable cards with <code>python scripts/make_qr_cards.py</code>.</div>
  </div>

  <div class="setting-block">
    <h4>About</h4>
    <div class="fact-line">Saturday Multiverse runs entirely on your machine. The host process is authoritative: nothing you see can silently alter the world; mechanics, dice and state are computed in application code, never by the model.</div>
  </div>`;
}

function wireSettings() {
  const $ = (s) => settingsBody.querySelector(s);
  const temp = $("#ai-temp"), words = $("#ai-words");
  temp?.addEventListener("input", () => { $("#ai-temp-val").textContent = temp.value; });
  words?.addEventListener("input", () => { $("#ai-words-val").textContent = `${words.value} words`; });

  let chosenStyle = state.view?.gm_style?.id || "classic";
  settingsBody.querySelectorAll("#gm-style-row [data-style]").forEach((c) => {
    c.addEventListener("click", () => {
      chosenStyle = c.dataset.style;
      settingsBody.querySelectorAll("#gm-style-row [data-style]").forEach((x) => x.classList.toggle("selected", x === c));
      const row = $("#gm-custom-row");
      if (row) row.hidden = chosenStyle !== "custom";
      audio.ui();
    });
  });
  $("#gm-style-save")?.addEventListener("click", async () => {
    if (!state.view) { window.__toast?.("Enter a campaign first.", "bad"); return; }
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/style`, "POST",
        { style_id: chosenStyle, custom_text: $("#gm-custom-text")?.value || "" });
      window.__toast?.(`Game Master persona: ${res.label}.`, "good");
      window.__refreshView?.();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });

  $("#ai-save")?.addEventListener("click", async () => {
    const patch = {
      enabled: $("#ai-enabled").checked,
      base_url: $("#ai-url").value.trim(),
      model: $("#ai-model").value.trim(),
      temperature: parseFloat(temp.value),
      narration_words: parseInt(words.value, 10),
    };
    const key = $("#ai-key").value;
    if (key) patch.api_key = key;
    try {
      const res = await apiSend("/api/settings", "PUT", { ai: patch });
      window.__aiCfg = res.ai;
      window.__toast?.("Model settings saved.", "good");
      window.__refreshAIBadge?.();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });

  $("#ai-test")?.addEventListener("click", async () => {
    const st = $("#ai-status");
    st.hidden = false; st.className = "ai-status"; st.textContent = "Reaching out across the dark…";
    const patch = {
      enabled: true,
      base_url: $("#ai-url").value.trim(),
      model: $("#ai-model").value.trim(),
      temperature: parseFloat(temp.value),
      narration_words: parseInt(words.value, 10),
    };
    const key = $("#ai-key").value;
    if (key) patch.api_key = key;
    try {
      const res = await apiSend("/api/ai/test", "POST", { ai: patch });
      if (res.ok) { st.className = "ai-status ok"; st.textContent = `Connected (${res.model || "model"}, ${res.latency_ms} ms). The shore has a voice.`; }
      else { st.className = "ai-status bad"; st.textContent = res.detail || "Could not connect."; }
    } catch (e) { st.className = "ai-status bad"; st.textContent = e.message; }
  });

  for (const [id, bus] of [["#vol-music", "music"], ["#vol-amb", "amb"], ["#vol-sfx", "sfx"]]) {
    $(id)?.addEventListener("input", (e) => audio.setBus(bus, parseFloat(e.target.value)));
  }
  $("#vol-mute")?.addEventListener("change", (e) => audio.setMuted(e.target.checked));
  $("#calm-mode")?.addEventListener("change", (e) => {
    localStorage.setItem("sm_calm", e.target.checked ? "1" : "0");
    document.body.classList.toggle("calm", e.target.checked);
    window.__hub?.setCalm(e.target.checked);
    window.__toast?.(e.target.checked ? "Calm mode on — the shore moves gently." : "Calm mode off.", "good");
  });

  $("#btn-backup")?.addEventListener("click", async () => {
    try {
      await apiSend("/api/backup", "POST", {});
      window.__toast?.("Database backed up.", "good");
      refreshBackups();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });
  refreshBackups();

  settingsBody.querySelector("#import-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const res = await apiSend("/api/import", "POST", data);
      window.__toast?.(`Imported campaign ${res.campaign_id}`, "good");
      window.__refreshCampaignList?.();
    } catch (err) { window.__toast?.(`Import failed: ${err.message}`, "bad"); }
  });
}

async function refreshBackups() {
  const list = settingsBody.querySelector("#backup-list");
  if (!list) return;
  try {
    const res = await apiGet("/api/backups");
    list.innerHTML = res.backups.slice(0, 5).map((b) => `
      <div class="setting-row"><span style="flex:1;color:var(--dim);font-size:0.85em">${esc(b.created_at)} · ${(b.size / 1024).toFixed(0)} KB</span>
      <button class="btn btn-small btn-ghost" data-restore="${esc(b.id)}">Restore</button></div>`).join("")
      || "<div class='fact-line'>No backups yet.</div>";
    list.querySelectorAll("[data-restore]").forEach((b) => b.addEventListener("click", async () => {
      try {
        await apiSend(`/api/backups/${b.dataset.restore}/restore`, "POST", {});
        window.__toast?.("Restored. Reloading…", "good");
        setTimeout(() => location.reload(), 900);
      } catch (e) { window.__toast?.(e.message, "bad"); }
    }));
  } catch { /* offline */ }
}

async function refreshCheckpoints() {
  const box = document.getElementById("checkpoint-body");
  if (!box) return;
  try {
    const res = await apiGet(`/api/campaigns/${window.__campaignId}/checkpoints`);
    box.innerHTML = (res.checkpoints || []).map((cp) => `
      <div class="setting-row"><span style="flex:1;color:var(--dim);font-size:0.85em">${esc(cp.name)} · ${esc(cp.created_at)}</span>
      <button class="btn btn-small btn-ghost" data-cp-restore="${esc(cp.id)}">Restore as new</button></div>`).join("")
      || "<div class='fact-line'>No checkpoints yet — save one before big decisions.</div>";
    box.querySelectorAll("[data-cp-restore]").forEach((b) => b.addEventListener("click", async () => {
      try {
        const r = await apiSend(`/api/campaigns/${window.__campaignId}/checkpoints/${b.dataset.cpRestore}/restore`, "POST", {});
        window.__toast?.(`Restored as a new campaign (${r.campaign_id}).`, "good");
      } catch (e) { window.__toast?.(e.message, "bad"); }
    }));
  } catch { /* ignore */ }
}
window.__refreshCheckpoints = refreshCheckpoints;

async function refreshLedgerViews() { /* reserved: additional ledger views render via panelLedger */ }

async function refreshPartySplit() {
  const box = document.getElementById("split-locations");
  if (!box) return;
  try {
    const v = await apiGet(`/api/campaigns/${window.__campaignId}/view`);
    const pack = await apiGet("/api/packs");
    const pk = (pack.packs || []).find((p) => p.id === v.pack_id) || {};
    box.innerHTML = (pk.locations || []).map((l) =>
      `<span class="chip" data-loc="${esc(l.id)}">${esc(l.name)}</span>`).join("");
    let chosen = null;
    box.querySelectorAll("[data-loc]").forEach((cl) => cl.addEventListener("click", () => {
      box.querySelectorAll("[data-loc]").forEach((x) => x.classList.remove("selected"));
      cl.classList.add("selected");
      chosen = cl.dataset.loc;
    }));
    const act = (url, payload) => apiSend(url, "POST", payload)
      .then(() => { window.__toast?.("Done.", "good"); openPanel("party"); })
      .catch((e) => window.__toast?.(e.message, "bad"));
    document.querySelector("[data-split]")?.addEventListener("click", () => {
      if (!chosen) { window.__toast?.("Choose a place to walk to.", "bad"); return; }
      act(`/api/campaigns/${window.__campaignId}/mp/split`, { location_id: chosen });
    });
    document.querySelector("[data-regroup]")?.addEventListener("click", () =>
      act(`/api/campaigns/${window.__campaignId}/mp/regroup`, {}));
    document.querySelector("[data-regroup-all]")?.addEventListener("click", () =>
      act(`/api/campaigns/${window.__campaignId}/mp/regroup`, { everyone: true }));
    document.querySelector("[data-spectator-invite]")?.addEventListener("click", async () => {
      try {
        const inv = await apiSend(`/api/campaigns/${window.__campaignId}/mp/invite-spectator`, "POST", { uses: 3 });
        window.__toast?.("Spectator link created — share it with a friend.", "good");
      } catch (e) { window.__toast?.(e.message, "bad"); }
    });
  } catch { /* not in a session */ }
}

export function initPanelChrome() {
  document.querySelectorAll("[data-close-panel]").forEach((el) => el.addEventListener("click", closePanel));
  document.querySelectorAll("[data-close-settings]").forEach((el) => el.addEventListener("click", closeSettings));
  document.querySelectorAll("[data-close-seed]").forEach((el) =>
    el.addEventListener("click", () => { document.getElementById("seed-root").hidden = true; }));
  document.querySelectorAll("#hud-nav [data-panel]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.panel === "settings") openSettings();
      else openPanel(b.dataset.panel);
    }));
  document.getElementById("hud-char").addEventListener("click", () => openPanel("character"));
}


// ---------- v0.3.6 panels: combat, director, split-party ----------
function panelCombat() {
  return `<div id="combat-body"><div class="fact-line">The field is quiet — no encounter runs.</div></div>`;
}

function panelDirector() {
  return `<div id="director-body"><div class="fact-line">Consulting the Director…</div></div>`;
}

export async function refreshCombatPanel() {
  const body = document.getElementById("combat-body");
  if (!body) return;
  try {
    const res = await apiGet(`/api/campaigns/${window.__campaignId}/combat`);
    const enc = res.encounter;
    if (!enc) { body.innerHTML = "<div class='fact-line'>The field is quiet — no encounter runs.</div>"; return; }
    const me = enc.players.find((p) => p.is_me);
    const hpBar = (hp, max) => `<span class="bar bar-vigor" style="width:90px"><i style="width:${max ? Math.max(0, Math.min(100, hp / max * 100)) : 0}%"></i></span>`;
    const players = enc.players.map((p) => `
      <div class="fact-line"><strong>${esc(p.name)}${p.is_me ? " (you)" : ""}</strong> — ♥${p.hp}/${p.hp_max}
        ${hpBar(p.hp, p.hp_max)} ${p.conditions.length ? esc(p.conditions.join(", ")) : ""}</div>`).join("");
    const monsters = enc.monsters.map((m) => `
      <div class="fact-line">${m.alive ? "⚔" : "☠"} <strong>${esc(m.name)}</strong> — AC ${m.ac} ·
        <span style="color:var(--dim)">${esc(m.hp_word)}</span>${m.conditions.length ? " · " + esc(m.conditions.join(", ")) : ""}
        ${m.alive && enc.my_turn ? `<button class="btn btn-small" data-attack="${m.idx}">Strike</button>` : ""}</div>`).join("");
    const log = enc.log.map((l) => `<div class="fact-line">• ${esc(l)}</div>`).join("");
    const spells = (enc.spells || []).map((s) => {
      const sp = { }[s] || s;
      return `<span class="chip" data-cast="${esc(s)}">${esc(String(sp).replace(/_/g, " "))}</span>`;
    }).join(" ");
    const items = (window.__combatItems || []).map((i) =>
      `<span class="chip" data-use-item="${esc(i.item_id || i.id)}">${esc(i.name || i.item_id)}</span>`).join(" ");
    const acts = enc.my_turn ? `
      <div class="sect"><h4>Your turn — round ${enc.round}</h4>
        <div class="chip-row">
          <span class="chip" data-act="defend">Defend</span>
          <span class="chip" data-act="retreat">Retreat</span>
          <span class="chip" data-act="second_wind">Second wind</span>
          <span class="chip" data-act="breath_weapon">Breath weapon</span>
        </div>
        ${spells ? `<div class="fact-line">cast: ${spells}</div>` : ""}
        ${items ? `<div class="fact-line">use: ${items}</div>` : ""}
      </div>` : `<div class="fact-line">${enc.status === "complete" ? "The encounter is over." : "Not your turn — " + esc(enc.turn?.name || "waiting") + " acts."}</div>`;
    body.innerHTML = `
      <div class="sect"><h4>${esc(enc.monster_name)} — round ${enc.round}</h4>${players}<div class="sect"></div>${monsters}</div>
      ${acts}
      <div class="sect"><h4>Log</h4>${log}</div>`;
    body.querySelectorAll("[data-attack]").forEach((b) => b.addEventListener("click", () =>
      window.__combatAct({ type: "attack", target: parseInt(b.dataset.attack, 10) })));
    body.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () =>
      window.__combatAct({ type: b.dataset.act })));
    body.querySelectorAll("[data-cast]").forEach((b) => b.addEventListener("click", () =>
      window.__combatAct({ type: "cast", spell: b.dataset.cast,
                           target: body.querySelector("[data-attack]") ? 0 : null })));
    body.querySelectorAll("[data-use-item]").forEach((b) => b.addEventListener("click", () =>
      window.__combatAct({ type: "item", item: b.dataset.useItem })));
  } catch (e) {
    body.innerHTML = `<div class='fact-line'>${esc(e.message)}</div>`;
  }
}

export async function refreshDirectorPanel() {
  const body = document.getElementById("director-body");
  if (!body) return;
  try {
    const d = await apiGet(`/api/campaigns/${window.__campaignId}/director`);
    const threads = (d.threads || []).map((t) => `
      <div class="fact-line"><strong>${esc(t.title)}</strong>
        <span class="chip">${esc(t.status)}</span> <span class="lc-kind">${esc(t.kind)}</span></div>`).join("")
      || "<div class='fact-line'>No threads yet — the story is young.</div>";
    const sugg = (d.suggestions || []).map((s) =>
      `<div class="ledger-card"><div class="lc-kind">optional pacing</div>${esc(s.suggestion)}</div>`).join("");
    body.innerHTML = `
      <div class="sect"><h4>Story threads (what actually happened)</h4>${threads}</div>
      ${sugg ? `<div class="sect"><h4>Optional beats — your call, always</h4>${sugg}</div>` : ""}
      <div class="sect"><h4>Intervention</h4>
        <div class="chip-row">
          ${["off", "gentle", "active"].map((m) => `<span class="chip ${d.mode === m ? "selected" : ""}" data-dmode="${m}">${m}</span>`).join("")}
        </div>
        <div class="fact-line">The Director suggests; it never forces, never rewrites history, never touches dice.</div>
      </div>
      <div class="sect"><h4>Continuity flags</h4><div id="continuity-body"><div class="fact-line">…</div></div></div>`;
    body.querySelectorAll("[data-dmode]").forEach((b) => b.addEventListener("click", async () => {
      await apiSend(`/api/campaigns/${window.__campaignId}/director/mode`, "POST", { mode: b.dataset.dmode });
      window.__toast?.(`Director: ${b.dataset.dmode}`, "good");
      refreshDirectorPanel();
    }));
    try {
      const cont = await apiGet(`/api/campaigns/${window.__campaignId}/continuity`);
      const cb = document.getElementById("continuity-body");
      cb.innerHTML = (cont.findings || []).map((f) =>
        `<div class="fact-line">⚠ ${esc(f.detail)}</div>`).join("") || "<div class='fact-line'>The story holds together.</div>";
    } catch { /* ignore */ }
  } catch (e) {
    body.innerHTML = `<div class='fact-line'>${esc(e.message)}</div>`;
  }
}
