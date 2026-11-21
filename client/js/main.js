// Saturday Multiverse — client orchestrator.
// Screens: title → (create | continue) → game. All mechanics live on the
// server; this file only renders state and forwards intent.

import { apiGet, apiSend } from "./api.js";
import { state, setView } from "./state.js";
import { ShoreScene } from "./scene.js";
import { renderVignette } from "./vignettes.js";
import { portraitSVG } from "./portraits.js";
import { audio } from "./audio.js";
import { attachScanner } from "./qr.js";
import { openPanel, openSettings, closeSettings, initPanelChrome } from "./ui.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- toasts ----------
export function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("toast-root").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}
window.__toast = toast;

// ---------- screens ----------
function showScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(id).classList.add("active");
}

// ---------- title canvas (a single waiting door) ----------
let titleRaf = null;
function startTitleCanvas() {
  const cv = $("title-canvas");
  const ctx = cv.getContext("2d");
  let t0 = performance.now();
  const stars = Array.from({ length: 90 }, () => ({ x: Math.random(), y: Math.random() * 0.7, r: Math.random() * 1.3 + 0.3, p: Math.random() * 6.28 }));
  const draw = (ts) => {
    const t = (ts - t0) / 1000;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = (cv.width = cv.clientWidth * dpr), H = (cv.height = cv.clientHeight * dpr);
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, "#0a0817"); g.addColorStop(0.6, "#1a1030"); g.addColorStop(1, "#0d0a18");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    for (const s of stars) {
      ctx.globalAlpha = 0.4 + 0.5 * Math.sin(t * 1.6 + s.p);
      ctx.fillStyle = "#cfd6ff";
      ctx.beginPath(); ctx.arc(s.x * W, s.y * H, s.r * dpr, 0, 6.283); ctx.fill();
    }
    ctx.globalAlpha = 1;
    // beam
    const by = H * 0.30;
    const bg = ctx.createLinearGradient(0, by - H * 0.05, 0, by + H * 0.05);
    bg.addColorStop(0, "rgba(155,140,255,0.03)"); bg.addColorStop(0.5, "rgba(155,140,255,0.22)"); bg.addColorStop(1, "rgba(67,232,216,0.04)");
    ctx.fillStyle = bg; ctx.fillRect(0, by - H * 0.05, W, H * 0.1);
    // sea
    ctx.fillStyle = "#120e24"; ctx.fillRect(0, H * 0.62, W, H * 0.38);
    for (let b = 0; b < 3; b++) {
      ctx.beginPath(); ctx.moveTo(0, H * (0.66 + b * 0.08));
      for (let x = 0; x <= W; x += 12 * dpr) ctx.lineTo(x, H * (0.66 + b * 0.08) + Math.sin(x / (100 * dpr) + t * (0.6 + b * 0.2)) * 4 * dpr);
      ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath();
      ctx.fillStyle = b % 2 ? "rgba(26,18,58,0.6)" : "rgba(14,10,32,0.6)"; ctx.fill();
    }
    // the waiting door
    const dx = W * 0.5, base = H * 0.72, dh = H * 0.22, dw = H * 0.12;
    const pulse = 0.6 + 0.4 * Math.sin(t * 1.4);
    ctx.save();
    ctx.shadowColor = "rgba(124,92,255,0.9)"; ctx.shadowBlur = 30 * dpr;
    ctx.strokeStyle = "rgba(155,140,255,0.95)"; ctx.lineWidth = 3 * dpr;
    ctx.beginPath();
    ctx.moveTo(dx - dw / 2, base); ctx.lineTo(dx - dw / 2, base - dh * 0.62);
    ctx.quadraticCurveTo(dx, base - dh * 1.25, dx + dw / 2, base - dh * 0.62);
    ctx.lineTo(dx + dw / 2, base); ctx.stroke();
    const pg = ctx.createLinearGradient(0, base - dh, 0, base);
    pg.addColorStop(0, `rgba(124,92,255,${0.4 * pulse + 0.12})`); pg.addColorStop(1, "rgba(124,92,255,0.05)");
    ctx.fillStyle = pg;
    ctx.beginPath();
    ctx.moveTo(dx - dw / 2 + 2 * dpr, base); ctx.lineTo(dx - dw / 2 + 2 * dpr, base - dh * 0.62);
    ctx.quadraticCurveTo(dx, base - dh * 1.18, dx + dw / 2 - 2 * dpr, base - dh * 0.62);
    ctx.lineTo(dx + dw / 2 - 2 * dpr, base); ctx.closePath(); ctx.fill();
    ctx.restore();
    // reflection
    const rg = ctx.createRadialGradient(dx, H * 0.76, 2, dx, H * 0.76, W * 0.06);
    rg.addColorStop(0, "rgba(124,92,255,0.4)"); rg.addColorStop(1, "rgba(124,92,255,0)");
    ctx.fillStyle = rg; ctx.fillRect(dx - W * 0.06, H * 0.72, W * 0.12, H * 0.08);
    titleRaf = requestAnimationFrame(draw);
  };
  titleRaf = requestAnimationFrame(draw);
}

// ---------- campaign list ----------
async function refreshCampaignList() {
  try {
    const res = await apiGet("/api/campaigns");
    state.campaigns = res.campaigns;
    const box = $("title-campaigns");
    if (state.campaigns.length) {
      box.hidden = false;
      box.innerHTML = state.campaigns.map((c) => `
        <div class="campaign-row" data-cid="${esc(c.id)}">
          <div class="cr-name">${esc(c.name)} <span style="color:var(--faint)">· ${esc(c.char_name || "?")}</span></div>
          <div class="cr-meta">turn ${c.turn} · ${esc(c.pack_id)}</div>
        </div>`).join("");
      box.querySelectorAll("[data-cid]").forEach((row) => row.addEventListener("click", async () => {
        try { enterGame(await apiGet(`/api/campaigns/${row.dataset.cid}`)); }
        catch (e) { toast(e.message, "bad"); }
      }));
    } else { box.hidden = true; box.innerHTML = ""; }
  } catch { /* server asleep */ }
}
window.__refreshCampaignList = refreshCampaignList;

// ---------- character creation ----------
let createSel = { archetype: "sensitive", stat: "bind", specialty: "bind", seed: "" };

async function showCreate() {
  showScreen("screen-create");
  try {
    const res = await apiGet("/api/packs");
    state.packs = res.packs;
  } catch (e) { toast(e.message, "bad"); return; }
  const pack = state.packs.find((p) => p.id === "living_shore") || state.packs[0];
  const detail = await apiGet(`/api/packs`).then(() => fetchPackDetail(pack.id));
  renderCreate(detail);
}

async function fetchPackDetail(packId) {
  // full archetypes for the chosen pack come embedded in pack list view's
  // locations; for creation we need the whole manifest — served by the
  // campaign view only after creation, so creation uses a lightweight copy:
  const res = await apiSend("/api/packs/detail", "POST", { pack_id: packId });
  return res.pack;
}

function renderCreate(pack) {
  const archs = pack.archetypes;
  $("create-archetypes").innerHTML = archs.map((a) => `
    <div class="archetype-card ${createSel.archetype === a.id ? "selected" : ""}" data-arch="${esc(a.id)}">
      <h4>${esc(a.name)}</h4>
      <p>${esc(a.blurb)}</p>
      <div class="stats">${Object.entries(a.stats).map(([k, v]) => `${k} ${v >= 0 ? "+" : ""}${v}`).join(" · ")}</div>
      <div class="kit">brings: ${a.kit.map((k) => (pack.items.find((i) => i.id === k) || { name: k }).name).join(", ")}</div>
    </div>`).join("");
  $("create-archetypes").querySelectorAll("[data-arch]").forEach((el) => el.addEventListener("click", () => {
    createSel.archetype = el.dataset.arch; audio.ui(); renderCreate(pack); updatePortrait();
  }));
  const stats = ["wits", "might", "mettle", "bind"];
  $("create-stat-boost").innerHTML = stats.map((s) =>
    `<span class="chip ${createSel.stat === s ? "selected" : ""}" data-stat="${s}">${s} +1</span>`).join("");
  $("create-stat-boost").querySelectorAll("[data-stat]").forEach((el) => el.addEventListener("click", () => {
    createSel.stat = el.dataset.stat; audio.ui(); renderCreate(pack); updatePortrait();
  }));
  const skills = ["notice", "lore", "persuade", "fight", "endure", "bind"];
  $("create-specialty").innerHTML = skills.map((s) =>
    `<span class="chip ${createSel.specialty === s ? "selected" : ""}" data-skill="${s}">${s}</span>`).join("");
  $("create-specialty").querySelectorAll("[data-skill]").forEach((el) => el.addEventListener("click", () => {
    createSel.specialty = el.dataset.skill; audio.ui(); renderCreate(pack);
  }));
  updatePortrait();
}

function updatePortrait() {
  const seed = $("create-seed").value.trim() || $("create-name").value.trim() || "unnamed";
  const archCard = document.querySelector(`[data-arch="${createSel.archetype}"]`);
  const palette = { sensitive: "violet", warden: "iron", deepwright: "brass", lanternist: "ember" }[createSel.archetype] || "tide";
  $("portrait-preview").innerHTML = portraitSVG(seed, palette, createSel.archetype);
  void archCard;
}

// ---------- game screen ----------
let hub = null;

function ensureHub() {
  if (hub) return hub;
  hub = new ShoreScene($("shore-canvas"), {
    onTravel: (locId) => doTravel(locId),
    onHotspot: (hotspotId) => showHotspot(hotspotId),
    onSealed: (p) => { toast(p.hint || "Sealed for now.", ""); audio.ui(); },
    onHover: (h) => {
      const tip = $("scene-tooltip");
      if (!h || $("shore-canvas").clientWidth === 0) { tip.hidden = true; return; }
      tip.hidden = false;
      tip.style.left = `${h.x * 100}%`;
      tip.style.top = `${(h.y - h.h / 2) * 100}%`;
      tip.innerHTML = `<span class="tt-label">${esc(h.label)}</span> — ${esc(h.hint || "")}`;
    },
  });
  return hub;
}

function enterGame(view) {
  showScreen("screen-game");
  ensureHub();
  setView(view);
  refreshView();
}

async function refreshView() {
  if (!state.view) return;
  try {
    const view = await apiGet(`/api/campaigns/${state.view.id}`);
    setView(view);
    renderGame();
  } catch (e) { toast(e.message, "bad"); }
}
window.__refreshView = refreshView;

function renderGame() {
  const v = state.view;
  const inAdventureScene = !!v.scene?.beat;
  // canvas vs vignette
  if (inAdventureScene || ["tavern", "lighthouse", "seacave", "wreck", "umbral_reach", "saltgrave_gate"].includes(v.location?.id)) {
    $("shore-canvas").style.display = "none";
    renderVignette($("vignette-layer"), v, (id) => showHotspot(id));
  } else {
    $("shore-canvas").style.display = "block";
    $("vignette-layer").innerHTML = "";
    hub.setView(v);
  }
  // HUD
  const ch = v.character;
  $("hud-name").textContent = ch.name;
  $("hud-portrait").innerHTML = portraitSVG(ch.portrait.seed, ch.portrait.palette, ch.archetype);
  $("hud-vigor").style.width = `${(ch.vigor / ch.vigor_max) * 100}%`;
  $("hud-nerve").style.width = `${(ch.nerve / ch.nerve_max) * 100}%`;
  $("hud-tide").textContent = `tide: ${v.tide}`;
  $("hud-weather").textContent = `${v.weather?.key || ""} · ${v.weather?.desc || ""}`;
  $("hud-turn").textContent = `turn ${v.turn}`;
  refreshAIBadge();
  // dock
  const locTitle = v.scene?.title || v.location?.name || "The Living Shore";
  $("dock-title").textContent = locTitle;
  $("dock-scene-hint").textContent = v.scene?.brief ? "" : (v.location?.short || "");
  if ($("dock-narration").dataset.pending !== "1") {
    $("dock-narration").textContent = lastNarration || v.summary || v.location?.desc || "The shore waits.";
    $("dock-narration").classList.remove("busy");
  }
  renderChoices();
  // audio scene
  const amb = v.location?.id === "camp" ? "camp" : v.location?.id === "tavern" ? "tavern" : "shore";
  audio.setScene(amb, v.weather?.key || "mist", v.tide);
}
window.__refreshAIBadge = refreshAIBadge;

function refreshAIBadge() {
  const cfg = window.__aiCfg || {};
  const chip = $("hud-ai");
  if (cfg.enabled && cfg.model) { chip.textContent = `GM: ${cfg.model}`; chip.className = "chip chip-ai ai-on"; }
  else { chip.textContent = "GM offline storyteller"; chip.className = "chip chip-ai ai-fallback"; }
  const tb = $("title-ai-badge");
  if (tb) {
    tb.textContent = cfg.enabled && cfg.model ? `AI Game Master: ${cfg.model}` : "AI Game Master: not configured — offline storyteller active";
  }
}

function renderChoices() {
  const v = state.view;
  const box = $("dock-choices");
  box.innerHTML = "";
  const scripted = (v.scene?.choices || []).filter((c) => v.scene?.beat);
  for (const c of scripted) {
    const b = document.createElement("button");
    b.className = "choice-btn" + (c.available ? "" : " locked");
    const checkLine = c.check ? `<span class="choice-dice">${esc(c.check.skill)} check${c.check.hard ? " · hard" : ""}</span>` : "";
    b.innerHTML = `${esc(c.label)}${checkLine}${c.available && c.hint ? `<span class="choice-hint">${esc(c.hint)}</span>` : ""}${!c.available ? `<span class="choice-hint">${esc(c.locked_hint || "")}</span>` : ""}`;
    b.addEventListener("click", () => { if (c.available) doChoose(c.id); else toast(c.locked_hint || "Not yet.", "bad"); });
    box.appendChild(b);
  }
  for (const s of lastSuggestions) {
    const b = document.createElement("button");
    b.className = "choice-btn suggestion";
    b.textContent = s;
    b.addEventListener("click", () => { $("composer-input").value = s; $("composer-input").focus(); });
    box.appendChild(b);
  }
}

// ---------- actions ----------
let busy = false;
let lastNarration = "";
let lastSuggestions = [];

async function act(text) {
  if (busy || !text.trim()) return;
  busy = true;
  $("dock-narration").dataset.pending = "1";
  $("dock-narration").textContent = "The Game Master considers…";
  $("dock-narration").classList.add("busy");
  $("dock-dice").hidden = true; $("dock-omen").hidden = true;
  $("dock-changes").innerHTML = ""; lastSuggestions = [];
  const composerBtn = document.querySelector("#composer button");
  composerBtn.disabled = true;
  try {
    const res = await apiSend(`/api/campaigns/${state.view.id}/action`, "POST", { text });
    audio.ui();
    lastNarration = res.narration;
    lastSuggestions = res.choices || [];
    $("dock-narration").textContent = res.narration;
    $("dock-narration").dataset.pending = "0";
    $("dock-narration").classList.remove("busy");
    $("dock-scene-hint").textContent = res.scene_hint || "";
    showTurnExtras(res);
    if (res.dice) audio.dice();
    if (res.dice && (res.dice.outcome === "undertow" || res.dice.outcome === "wipeout")) audio.harm();
    await refreshView();
    $("dock-narration").textContent = lastNarration;
  } catch (e) {
    $("dock-narration").dataset.pending = "0";
    $("dock-narration").classList.remove("busy");
    toast(e.message, "bad");
  } finally {
    busy = false;
    composerBtn.disabled = false;
  }
}

async function doChoose(choiceId) {
  if (busy) return;
  busy = true;
  try {
    const res = await apiSend(`/api/campaigns/${state.view.id}/choose`, "POST", { choice_id: choiceId });
    lastNarration = res.narration;
    lastSuggestions = [];
    $("dock-narration").textContent = res.narration;
    $("dock-narration").dataset.pending = "0";
    if (res.dice) { audio.dice(); showDice(res.dice); }
    if (res.ending) { audio.chime(); toast(`Ending witnessed: ${res.ending.replace(/_/g, " ")}`, "good"); }
    showChanges(res.changes || []);
    await refreshView();
    $("dock-narration").textContent = lastNarration;
  } catch (e) { toast(e.message, "bad"); }
  finally { busy = false; }
}

async function doTravel(locId) {
  if (busy) return;
  busy = true;
  audio.steps();
  try {
    const res = await apiSend(`/api/campaigns/${state.view.id}/travel`, "POST", { location_id: locId });
    lastNarration = res.narration;
    lastSuggestions = [];
    $("dock-narration").textContent = res.narration;
    $("dock-narration").dataset.pending = "0";
    $("dock-scene-hint").textContent = "";
    audio.portal();
    showChanges(res.changes || []);
    await refreshView();
    $("dock-narration").textContent = lastNarration;
  } catch (e) { toast(e.message, "bad"); }
  finally { busy = false; }
}
window.__travel = doTravel;

function showHotspot(hotspotId) {
  const hs = (state.view?.scene?.hotspots || []).find((h) => h.id === hotspotId);
  if (!hs) return;
  audio.chime();
  lastNarration = hs.text;
  $("dock-narration").textContent = hs.text;
  $("dock-narration").dataset.pending = "0";
  $("dock-title").textContent = hs.label;
}

function showDice(dice) {
  const box = $("dock-dice");
  box.hidden = false;
  box.innerHTML = `
    <span class="die ${dice.dice[0] < 4 ? "low" : ""}">${dice.dice[0]}</span>
    <span class="die ${dice.dice[1] < 4 ? "low" : ""}">${dice.dice[1]}</span>
    <span class="dice-outcome outcome-${esc(dice.outcome)}">${esc(dice.text)}</span>`;
}
window.__showDice = showDice;

function showChanges(changes) {
  const box = $("dock-changes");
  box.innerHTML = (changes || []).map((c) => {
    const bad = /−|lost|harm|nerve|vigor/i.test(c) && !/restored|gained/i.test(c);
    return `<span class="chip ${bad ? "bad" : "good"}">${esc(c)}</span>`;
  }).join("");
}

function showTurnExtras(res) {
  if (res.dice) showDice(res.dice);
  showChanges(res.changes);
  if (res.omen) {
    $("dock-omen").hidden = false;
    $("dock-omen").innerHTML = `<span class="omen-kind">omen · ${esc(res.omen.kind)}</span> — <strong>${esc(res.omen.title)}</strong> ${esc(res.omen.text)}`;
  }
}

// ---------- QR ----------
async function handleScan(payload) {
  if (!state.view) { toast("Scan a sigil while inside a campaign.", "bad"); return; }
  try {
    const res = await apiSend(`/api/campaigns/${state.view.id}/qr`, "POST", { payload });
    if (!res.ok) { toast(res.detail || "The sigil does nothing here.", "bad"); return; }
    if (res.kind === "ui") { openPanel(res.command.toLowerCase()); toast(`Sigil opens: ${res.desc}`, "good"); }
    else if (res.kind === "item") toast(`${res.item.name} — ${res.item.desc || ""}`, "good");
    else if (res.kind === "lore") { toast(res.lore.title, "good"); await refreshView(); }
    else if (res.kind === "event") { toast(res.event.title || "The sigil hums.", "good"); await refreshView(); }
    else if (res.kind === "rest") { toast(res.narration, "good"); await refreshView(); }
    audio.chime();
  } catch (e) { toast(e.message, "bad"); }
}

// ---------- boot ----------
async function boot() {
  initPanelChrome();
  document.addEventListener("pointerdown", () => audio.ensure(), { once: true });
  document.addEventListener("keydown", attachScanner(handleScan));

  try {
    const health = await apiGet("/api/health");
    window.__aiCfg = (await apiGet("/api/settings")).ai;
    refreshAIBadge();
    console.info(`Saturday Multiverse ${health.version} — data at ${health.data_dir}`);
  } catch {
    toast("The server is not answering — is it running?", "bad");
  }

  startTitleCanvas();
  await refreshCampaignList();

  $("btn-new-voyage").addEventListener("click", () => { audio.ensure(); audio.ui(); showCreate(); });
  $("btn-continue").addEventListener("click", () => { audio.ensure(); audio.ui(); refreshCampaignList(); });
  $("btn-title-settings").addEventListener("click", () => { audio.ensure(); openSettings(); });

  $("create-name").addEventListener("input", updatePortrait);
  $("create-seed").addEventListener("input", updatePortrait);
  $("btn-create-back").addEventListener("click", () => { showScreen("screen-title"); refreshCampaignList(); });
  $("btn-create-begin").addEventListener("click", async () => {
    const name = $("create-name").value.trim();
    if (!name) { toast("Every wanderer needs a name.", "bad"); return; }
    try {
      const res = await apiSend("/api/campaigns", "POST", {
        name: `${name}: a Saturday voyage`,
        pack_id: "living_shore",
        character: {
          name, archetype: createSel.archetype,
          extra_stat: { stat: createSel.stat },
          specialty: createSel.specialty,
          portrait_seed: $("create-seed").value.trim() || name,
        },
      });
      audio.portal();
      enterGame(res.view);
    } catch (e) { toast(e.message, "bad"); }
  });

  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const inp = $("composer-input");
    const text = inp.value;
    inp.value = "";
    act(text);
  });
}

boot();
