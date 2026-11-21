// Saturday Multiverse — side panels & settings UI.
import { apiGet, apiSend } from "./api.js";
import { state, emit } from "./state.js";
import { portraitSVG } from "./portraits.js";
import { audio } from "./audio.js";

const root = document.getElementById("panel-root");
const settingsRoot = document.getElementById("settings-root");
const panelTitle = document.getElementById("panel-title");
const panelBody = document.getElementById("panel-body");
const settingsBody = document.getElementById("settings-body");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- drawer plumbing ----------
export function openPanel(name) {
  panelTitle.textContent = { map: "Map of the Shore", journal: "Journal", inventory: "Pack",
    quests: "Quests & Mysteries", dice: "Dice Log", character: "Character" }[name] || "Panel";
  panelBody.innerHTML = { map: panelMap, journal: panelJournal, inventory: panelInventory,
    quests: panelQuests, dice: panelDice, character: panelCharacter }[name]?.() || "";
  wirePanel(name);
  root.hidden = false;
  audio.ui();
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
};

function panelMap() {
  const v = state.view;
  const here = v.location?.id;
  const pins = v.pack?.locations || [];
  const disc = v.discovered || {};
  const svgPins = pins.map((l) => {
    const [px, py] = MAP_POS[l.id] || [50, 50];
    const known = l.id === here || disc[l.id] || ["tidegate", "camp", "tavern"].includes(l.id);
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
  <div class="fact-line" style="margin-top:0.8em">Click a marked place to walk there. The Beam carries the doors: two stand open, one is sealed.</div>
  <div class="fact-line">${v.tide === "low" ? "Low tide: the cave and the wreck are reachable." : "High tide: the cave and the wreck are under water."}</div>`;
}

function wirePanel(name) {
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
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/check`, "POST", { skill, hard });
      audio.dice();
      window.__showDice?.(res);
      window.__refreshView?.();
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });
}

// ---------- settings ----------
function settingsHTML() {
  const v = state.view;
  return `
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
    <h4>Sound</h4>
    <div class="slider-row"><label>Music</label><input type="range" id="vol-music" min="0" max="1" step="0.05" value="${audio.prefs.music}"></div>
    <div class="slider-row"><label>Ambience</label><input type="range" id="vol-amb" min="0" max="1" step="0.05" value="${audio.prefs.amb}"></div>
    <div class="slider-row"><label>Effects</label><input type="range" id="vol-sfx" min="0" max="1" step="0.05" value="${audio.prefs.sfx}"></div>
    <div class="setting-row"><label><input type="checkbox" id="vol-mute" ${audio.prefs.muted ? "checked" : ""}> mute everything</label></div>
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

export function initPanelChrome() {
  document.querySelectorAll("[data-close-panel]").forEach((el) => el.addEventListener("click", closePanel));
  document.querySelectorAll("[data-close-settings]").forEach((el) => el.addEventListener("click", closeSettings));
  document.querySelectorAll("#hud-nav [data-panel]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.panel === "settings") openSettings();
      else openPanel(b.dataset.panel);
    }));
  document.getElementById("hud-char").addEventListener("click", () => openPanel("character"));
}
