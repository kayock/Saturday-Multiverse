// Saturday Multiverse — client orchestrator.
// Screens: title → (create | continue) → game. All mechanics live on the
// server; this file only renders state and forwards intent.

import { apiGet, apiSend } from "./api.js?v=30";
import { state, setView } from "./state.js?v=30";
import { ShoreScene } from "./scene.js?v=30";
import { renderVignette } from "./vignettes.js?v=30";
import { portraitSVG } from "./portraits.js?v=30";
import { audio } from "./audio.js?v=30";
import { attachScanner } from "./qr.js?v=30";
import { openPanel, openSettings, closeSettings, initPanelChrome,
         openSeedGate, openTalk, showEchoOffers, openEchoShelf } from "./ui.js?v=33";
import * as mpui from "./mp.js?v=30";
import * as libui from "./library.js?v=33";

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
        try {
          // resume a shared session FIRST so the view fetch carries the token
          const resumed = await mpui.resumeIfHosted(row.dataset.cid);
          enterGame(await apiGet(`/api/campaigns/${row.dataset.cid}`), resumed);
        }
        catch (e) { toast(e.message, "bad"); }
      }));
    } else { box.hidden = true; box.innerHTML = ""; }
  } catch { /* server asleep */ }
}
window.__refreshCampaignList = refreshCampaignList;

// ---------- character creation ----------
let createSel = { archetype: "sensitive", stat: "bind", specialty: "bind", seed: "",
  echoes: [], pack: "living_shore", ruleset: "undertow",
  dndClass: "fighter", dndSpecies: "human", dndBackground: "folk_hero" };

const DND_CLASSES = { fighter: "Fighter — steel and second wind", rogue: "Rogue — locks, shadows, escape",
  cleric: "Cleric — healing and sacred flame", wizard: "Wizard — missile, shield, fire bolt" };
const DND_SPECIES = { human: "Human — versatile", elf: "Elf — keen senses", dwarf: "Dwarf — stout",
  halfling: "Halfling — lucky" };
const DND_BACKGROUNDS = { folk_hero: "Folk Hero", sage: "Sage", soldier: "Soldier", charlatan: "Charlatan" };

async function showCreate(preselectPack) {
  showScreen("screen-create");
  try {
    const res = await apiGet("/api/packs");
    state.packs = res.packs;
  } catch (e) { toast(e.message, "bad"); return; }
  if (preselectPack) createSel.pack = preselectPack;
  if (!state.packs.some((p) => p.id === createSel.pack)) {
    createSel.pack = (state.packs.find((p) => p.id === "living_shore") || state.packs[0]).id;
  }
  const detail = await fetchPackDetail(createSel.pack);
  renderCreate(detail);
  renderEchoChoices();
}

async function fetchPackDetail(packId) {
  const res = await apiSend("/api/packs/detail", "POST", { pack_id: packId });
  return res.pack;
}

async function renderEchoChoices() {
  createSel.echoes = [];
  let echoes = [];
  try { echoes = (await apiGet("/api/echoes?unused=1")).echoes; } catch { /* ignore */ }
  let box = document.getElementById("create-echoes");
  if (!box) {
    box = document.createElement("div");
    box.id = "create-echoes";
    document.querySelector(".create-actions").before(box);
  }
  if (!echoes.length) {
    box.innerHTML = `<label class="field-label">The multiverse remembers</label>
      <div class="fact-line" style="color:var(--dim)">No echoes yet — finished adventures leave legacies here
      that new voyages can weave in.</div>`;
    return;
  }
  box.innerHTML = `
    <label class="field-label">The multiverse remembers — weave up to 2 echoes into this wanderer</label>
    <div class="card-grid">${echoes.map((e) => `
      <div class="ledger-card card-paid echo-pick ${createSel.echoes.includes(e.id) ? "selected" : ""}" data-echo="${esc(e.id)}">
        <div class="lc-kind">echo · ${esc(e.kind)}</div>
        <strong>${esc(e.title)}</strong>
        <div class="fact-line">${esc(e.detail)}</div>
      </div>`).join("")}</div>`;
  box.querySelectorAll("[data-echo]").forEach((c) => c.addEventListener("click", () => {
    const id = c.dataset.echo;
    if (createSel.echoes.includes(id)) createSel.echoes = createSel.echoes.filter((x) => x !== id);
    else if (createSel.echoes.length < 2) createSel.echoes.push(id);
    else { toast("Only two echoes can be woven into one voyage.", "bad"); return; }
    c.classList.toggle("selected", createSel.echoes.includes(id));
    audio.ui();
  }));
}

function renderCreate(pack) {
  // pack picker (every installed adventure is a door)
  const packChips = state.packs.map((p) =>
    `<span class="chip ${createSel.pack === p.id ? "selected" : ""}" data-pack="${esc(p.id)}">${esc(p.name)}</span>`).join("");
  const packBox = $("create-packs") || (() => {
    const box = document.createElement("div");
    box.id = "create-packs";
    $("create-archetypes").before(box);
    return box;
  })();
  packBox.innerHTML = `<label class="field-label">Your door — which story do you walk into?</label>
    <div class="chip-row">${packChips}</div>
    <label class="field-label">Ruleset</label>
    <div class="chip-row">
      <span class="chip ${createSel.ruleset === "undertow" ? "selected" : ""}" data-ruleset="undertow">Undertow 2d6</span>
      <span class="chip ${createSel.ruleset === "dnd5e" ? "selected" : ""}" data-ruleset="dnd5e">D&amp;D-compatible (SRD)</span>
    </div>`;
  packBox.querySelectorAll("[data-pack]").forEach((el) => el.addEventListener("click", async () => {
    createSel.pack = el.dataset.pack; audio.ui();
    renderCreate(await fetchPackDetail(createSel.pack));
  }));
  packBox.querySelectorAll("[data-ruleset]").forEach((el) => el.addEventListener("click", () => {
    createSel.ruleset = el.dataset.ruleset; audio.ui(); renderCreate(pack);
  }));

  // D&D mode replaces the Undertow roads with class/species/background
  if (createSel.ruleset === "dnd5e") {
    const chipRow = (label, options, key) => `
      <label class="field-label">${label}</label>
      <div class="chip-row">${Object.entries(options).map(([k, v]) =>
        `<span class="chip ${createSel[key] === k ? "selected" : ""}" data-dnd="${key}:${k}">${esc(v)}</span>`).join("")}</div>`;
    const dndBox = $("create-dnd") || (() => {
      const box = document.createElement("div");
      box.id = "create-dnd";
      $("create-archetypes").after(box);
      return box;
    })();
    dndBox.innerHTML = chipRow("Class", DND_CLASSES, "dndClass")
      + chipRow("Species", DND_SPECIES, "dndSpecies")
      + chipRow("Background", DND_BACKGROUNDS, "dndBackground");
    dndBox.querySelectorAll("[data-dnd]").forEach((el) => el.addEventListener("click", () => {
      const [key, val] = el.dataset.dnd.split(":");
      createSel[key] = val; audio.ui(); renderCreate(pack);
    }));
    $("create-archetypes").style.display = "none";
    const statBox = $("create-stat-boost");
    if (statBox) statBox.style.display = "none";
    const specBox = $("create-specialty");
    if (specBox) specBox.closest("label") ? ($("create-specialty").style.display = "none") : ($("create-specialty").style.display = "none");
    updatePortrait();
    return;
  }
  $("create-archetypes").style.display = "";
  const statBox0 = $("create-stat-boost");
  if (statBox0) statBox0.style.display = "";
  const specBox0 = $("create-specialty");
  if (specBox0) specBox0.style.display = "";
  const dndBox0 = $("create-dnd");
  if (dndBox0) dndBox0.remove();

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
    onTravel: (locId) => { if (locId) doTravel(locId); else openSeedGate(); },
    onHotspot: (hotspotId) => showHotspot(hotspotId),
    onSealed: (p) => { toast(p.hint || "Sealed for now.", ""); audio.ui(); },
    onSeed: () => openSeedGate(),
    onWash: async () => {
      try {
        const res = await apiSend(`/api/campaigns/${state.view.id}/washashore`, "POST", {});
        toast(res.narration, "good");
        if (res.changes?.length) showChanges(res.changes);
        audio.chime();
        await refreshView();
      } catch (e) { toast(e.message, "bad"); }
    },
    onHover: (h) => {
      const tip = $("scene-tooltip");
      if (!h || $("shore-canvas").clientWidth === 0) { tip.hidden = true; return; }
      tip.hidden = false;
      tip.style.left = `${h.x * 100}%`;
      tip.style.top = `${(h.y - h.h / 2) * 100}%`;
      tip.innerHTML = `<span class="tt-label">${esc(h.label)}</span> — ${esc(h.hint || "")}`;
    },
  });
  hub.setCalm(localStorage.getItem("sm_calm") === "1");
  window.__hub = hub;
  return hub;
}

function enterGame(view, shared = false) {
  showScreen("screen-game");
  ensureHub();
  setView(view);
  window.__campaignId = view.id;
  window.__refreshCombatPanel?.();
  refreshView();
  showRecapIfReturning(view.id);
  if (shared) {
    $("nav-chat").hidden = false;
    $("nav-party").hidden = false;
    $("mp-conn").hidden = false;
    toast("You are back on the shared shore.", "good");
  }
}

// ---------- v0.4.0: interactive tutorial + accessibility ----------
const TUTORIAL_KEY = "sm_tutorial_done_v1";
const TUTORIAL_STEPS = [
  { sel: "#hud-nav", text: "These are your panels: the map, your journal, the Memory Ledger, quests, dice — everything the shore remembers lives here." },
  { sel: "#scene-stage", text: "This is the Living Shore — a persistent beach between worlds. Doors in the shallows are portals into adventures." },
  { sel: "#composer", text: "Say anything in your own words — the Game Master listens. The engine decides all dice and consequences; the GM only narrates them." },
  { sel: "#dock-choices", text: "Choices offered here are always valid — picking one moves the story through engine-validated steps." },
  { sel: "#hud-char", text: "Your character: vigor and nerve are your health and resolve. Rest at safe places to recover." },
];
const DND_TUTORIAL_NOTES = {
  combat: "D&D combat is turn-based: initiative decides the order, you act on your own turn, and the engine rolls every die. HP persists between fights — the dead stay dead.",
  dice: "D&D checks are d20 + modifier against a difficulty. 20s crit, 1s fail badly. Death saves happen when you drop to 0 HP.",
};

function tutorialSteps() {
  const steps = TUTORIAL_STEPS.slice();
  if ((window.__ruleset || "") === "dnd5e") {
    steps.splice(2, 0, { sel: "#composer", text: DND_TUTORIAL_NOTES.combat, dnd: true });
    steps.splice(4, 0, { sel: "#dock-dice", text: DND_TUTORIAL_NOTES.dice, dnd: true });
  }
  return steps;
}

function startTutorial(force = false) {
  if (!force && localStorage.getItem(TUTORIAL_KEY)) return;
  const steps = tutorialSteps();
  let i = 0;
  const prev = document.createElement("div");
  prev.id = "tutorial-overlay";
  prev.style.cssText = "position:fixed;inset:0;background:rgba(4,6,14,0.72);z-index:9999;display:flex;align-items:flex-end;justify-content:center;padding:2vh 3vw;";
  const card = document.createElement("div");
  card.style.cssText = "background:var(--deep,#141a2e);border:1px solid var(--teal,#39d0c4);border-radius:14px;max-width:560px;width:100%;padding:18px 20px;color:var(--text,#e8ecf6);font:inherit;";
  prev.appendChild(card);
  const render = () => {
    const s = steps[i];
    card.innerHTML = `<div style="color:var(--gold,#e8b84b);font-size:0.8em;text-transform:uppercase;letter-spacing:0.12em">First night on the shore · ${i + 1}/${steps.length}${s.dnd ? " · D&D" : ""}</div>
      <p style="margin:0.6em 0">${s.text}</p>
      <div style="display:flex;gap:0.5em;justify-content:flex-end">
        <button data-tut="skip" class="btn btn-small btn-ghost">Skip</button>
        <button data-tut="next" class="btn btn-small btn-primary">${i + 1 === steps.length ? "Set sail" : "Next"}</button>
      </div>`;
    card.querySelector("[data-tut=\"next\"]").onclick = () => {
      i += 1;
      if (i >= steps.length) { finish(); return; }
      render();
      highlight();
    };
    card.querySelector("[data-tut=\"skip\"]").onclick = finish;
  };
  const highlight = () => {
    try {
      const el = document.querySelector(steps[i].sel);
      if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); }
    } catch { /* fine */ }
  };
  const finish = () => {
    localStorage.setItem(TUTORIAL_KEY, "1");
    prev.remove();
  };
  document.body.appendChild(prev);
  render();
  highlight();
}
window.__startTutorial = startTutorial;

function applyAccessibility() {
  const prefs = JSON.parse(localStorage.getItem("sm_a11y") || "{}");
  document.body.classList.toggle("reduced-motion", !!prefs.reduced_motion);
  document.body.classList.toggle("high-contrast", !!prefs.high_contrast);
}
window.__applyAccessibility = applyAccessibility;

async function showRecapIfReturning(cid) {
  try {
    const r = await apiGet(`/api/campaigns/${cid}/recap`);
    const banner = document.getElementById("recap-banner");
    if (!banner) return;
    if (r.is_returning && (r.items || []).length) {
      document.getElementById("recap-items").innerHTML = (r.items || []).map((i) =>
        `<div class="fact-line">• <strong>${esc(i.kind)}</strong>: ${esc(i.text)}</div>`).join("");
      banner.hidden = false;
      document.getElementById("recap-dismiss").onclick = async () => {
        await apiSend(`/api/campaigns/${cid}/recap/dismiss`, "POST", {});
        banner.hidden = true;
      };
    } else {
      banner.hidden = true;
    }
  } catch { /* solo older save without the endpoint */ }
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
  const interior = ["tavern", "lighthouse", "seacave", "wreck", "umbral_reach", "saltgrave_gate", "ninth_wave"]
    .includes(v.location?.id) || !!v.world;
  // canvas vs vignette
  if (inAdventureScene || interior) {
    $("shore-canvas").style.display = "none";
    renderVignette($("vignette-layer"), v, (id) => showHotspot(id));
    // seeded worlds tint their scenes; the shore keeps its own palette
    $("vignette-layer").style.filter = v.world
      ? `hue-rotate(${v.world.tint || 0}deg) saturate(1.15)` : "";
  } else {
    $("shore-canvas").style.display = "block";
    $("vignette-layer").innerHTML = "";
    $("vignette-layer").style.filter = "";
    hub.setView(v);
  }
  // HUD
  const ch = v.character;
  $("hud-name").textContent = ch.name;
  $("hud-portrait").innerHTML = portraitSVG(ch.portrait.seed, ch.portrait.palette, ch.archetype);
  $("hud-vigor").style.width = `${(ch.vigor / ch.vigor_max) * 100}%`;
  $("hud-nerve").style.width = `${(ch.nerve / ch.nerve_max) * 100}%`;
  // tide clock dial
  const phase = v.tide_phase || { tide: v.tide, progress: 0 };
  const circ = 2 * Math.PI * 8;
  $("tide-dial").innerHTML = `
    <circle cx="10" cy="10" r="8" fill="none" stroke="rgba(155,140,255,0.25)" stroke-width="3"/>
    <circle cx="10" cy="10" r="8" fill="none" stroke="${phase.tide === "low" ? "#43e8d8" : "#9b8cff"}"
      stroke-width="3" stroke-linecap="round" stroke-dasharray="${circ}"
      stroke-dashoffset="${(circ * (1 - (phase.progress ?? 0))).toFixed(1)}"
      transform="rotate(-90 10 10)"/>`;
  $("hud-tide-text").textContent = `${phase.tide} tide · ${phase.beats_to_change} beats`;
  $("hud-beads").textContent = `◍ ${v.beads ?? 0}`;
  $("hud-weather").textContent = `${v.weather?.key || ""} · ${v.weather?.desc || ""}`;
  $("hud-turn").textContent = `turn ${v.turn}`;
  refreshAIBadge();
  // dock
  const locTitle = v.scene?.title || v.location?.name || "The Living Shore";
  $("dock-title").textContent = locTitle;
  $("dock-scene-hint").textContent = v.scene?.brief ? "" : (v.location?.short || "");
  // who can be talked to here
  const talkNpc = { camp: "Old Cardo", tavern: "Maren", umbral_reach: "the Ledger-Keeper" }[v.location?.id];
  $("dock-talk").innerHTML = talkNpc
    ? `<button id="btn-talk" class="btn btn-small">${talkNpc ? `Talk — ${esc(talkNpc)}` : ""}</button>` : "";
  $("btn-talk")?.addEventListener("click", () => openTalk());
  // something on the beach?
  if (v.washashore) {
    $("dock-wash").hidden = false;
    $("dock-wash-label").textContent = `Something washed ashore: ${v.washashore.label}`;
  } else {
    $("dock-wash").hidden = true;
  }
  if ($("dock-narration").dataset.pending !== "1") {
    $("dock-narration").textContent = lastNarration || v.summary || v.location?.desc || "The shore waits.";
    $("dock-narration").classList.remove("busy");
  }
  renderChoices();
  renderPendingRoll();
  // audio scene
  const amb = v.location?.id === "camp" ? "camp" : v.location?.id === "tavern" ? "tavern" : "shore";
  audio.setScene(amb, v.weather?.key || "mist", v.tide);
}
window.__refreshAIBadge = refreshAIBadge;

function refreshAIBadge() {
  const cfg = window.__aiCfg || {};
  const route = window.__route || {};
  const chip = $("hud-ai");
  const tb = $("title-ai-badge");
  const offline = () => {
    chip.textContent = "GM offline storyteller";
    chip.className = "chip chip-ai ai-fallback";
    if (tb) tb.textContent = cfg.enabled
      ? "Offline Storyteller — the last turn was not AI narration"
      : "AI Game Master: not configured — offline storyteller active";
  };
  if (!cfg.enabled || route.fallback || route.narration === "offline") { offline(); return; }
  const name = route.model || cfg.model;
  if (!name) { offline(); return; }
  const host = route.host ? ` @ ${route.host}` : "";
  if (route.narration !== "ai") {
    chip.textContent = `GM ready: ${name}${host}`;
    chip.className = "chip chip-ai ai-on";
    if (tb) tb.textContent = `Game Master ready: ${name}${host}`;
    return;
  }
  chip.textContent = `GM: ${name}${host}`;
  chip.className = "chip chip-ai ai-on";
  if (tb) tb.textContent = `AI Game Master: ${name}${host}`;
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

    window.__captureTrace?.(res);
    if (res.meta?.ai_used && res.meta.model) {
      window.__route = { model: res.meta.model, host: res.meta.host || "", latency_ms: res.meta.latency_ms, fallback: false };
    } else if (res.meta) {
      window.__route = { fallback: true };
    }
    refreshAIBadge();
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
    window.__captureTrace?.(res);
    lastNarration = res.narration;
    lastSuggestions = [];
    $("dock-narration").textContent = res.narration;
    $("dock-narration").dataset.pending = "0";
    if (res.dice) {
      audio.dice();
      showDice(res.dice);
      const dock = document.getElementById("dock-dice");
      if (dock && !document.body.classList.contains("reduced-motion")) {
        const outcome = (res.dice.outcome || "").toLowerCase();
        if (outcome.includes("triumph") || outcome.includes("crit") || outcome.includes("great")) {
          dock.classList.add("dice-crit"); setTimeout(() => dock.classList.remove("dice-crit"), 900);
        } else if (outcome.includes("disaster") || outcome.includes("fail") || outcome.includes("wreck")) {
          dock.classList.add("dice-fail"); setTimeout(() => dock.classList.remove("dice-fail"), 900);
        }
      }
    }
    if (res.ending) { audio.chime(); toast(`Ending witnessed: ${res.ending.replace(/_/g, " ")}`, "good"); }
    showChanges(res.changes || []);
    if (res.echo_offers?.length) showEchoOffers(res.echo_offers);
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

// ---------- tactical window (Push / Resist) ----------
function renderPendingRoll() {
  const v = state.view;
  const box = $("dock-dice");
  const p = v.pending_roll;
  if (!p || !v.pending_roll || v.pending_roll.resolved) { return; }
  const canPush = !p.pushed && ["undertow", "riptide"].includes(p.outcome);
  const canResist = !p.resisted && (p.harm || 0) > 0;
  if (!canPush && !canResist) return;
  box.hidden = false;
  const row = document.createElement("div");
  row.className = "pending-row";
  row.innerHTML = `
    ${canPush ? `<button class="btn btn-small" data-tactic="push">Push — 1 Vigor, raise the band</button>` : ""}
    ${canResist ? `<button class="btn btn-small" data-tactic="resist">Resist — 1 Nerve, halve the harm</button>` : ""}
    <button class="btn btn-small btn-ghost" data-tactic="accept">Accept the result</button>`;
  box.appendChild(row);
  row.querySelector("[data-tactic='accept']")?.addEventListener("click", () => acceptPending());
  row.querySelector("[data-tactic='push']")?.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/push`, "POST", {});
      toast(res.narration, "good");
      showChanges(res.changes || []);
      acceptPending();
      await refreshView();
    } catch (e) { toast(e.message, "bad"); }
  });
  row.querySelector("[data-tactic='resist']")?.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/campaigns/${state.view.id}/resist`, "POST", {});
      toast(res.narration, "good");
      showChanges(res.changes || []);
      acceptPending();
      await refreshView();
    } catch (e) { toast(e.message, "bad"); }
  });
}

function acceptPending() {
  const box = $("dock-dice");
  box.querySelector(".pending-row")?.remove();
  if (!box.querySelector(".die")) box.hidden = true;
  // clear the server-side window quietly
  apiSend(`/api/campaigns/${state.view.id}/pending/accept`, "POST", {}).catch(() => {});
}

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
window.__enterShared = (view) => {
  mpui.markEntered();
  showScreen("screen-game");
  ensureHub();
  setView(view);
  renderGame();
  toast("You stand on the shared shore.", "good");
  mpui.refreshSessionView();
};

window.__mpNarration = (d) => {
  lastNarration = d.text || "";
  $("dock-narration").textContent = lastNarration;
  $("dock-narration").dataset.pending = "0";
  showChanges(d.changes || []);
  refreshView();
};

window.__mpDice = (d) => {
  const box = $("dock-dice");
  box.hidden = false;
  const dice = d.dice || [];
  box.innerHTML = `<span class="die ${dice[0] < 4 ? "low" : ""}">${dice[0] ?? "?"}</span>
    <span class="die ${dice[1] < 4 ? "low" : ""}">${dice[1] ?? "?"}</span>
    <span class="dice-outcome outcome-${esc(d.outcome || "")}">${esc(d.name)} — ${esc(d.text || "")}</span>`;
};

function wireMultiplayer() {
  if (mpui.bootFromLink()) return;
}

function wireMultiplayerScreens() {
  $("btn-mp-host").addEventListener("click", () => { audio.ensure(); mpui.showHostScreen(); });
  $("btn-library").addEventListener("click", () => { audio.ensure(); libui.showLibrary(); });
  $("btn-library-back").addEventListener("click", () => libui.leaveLibrary());
  $("btn-library-import").addEventListener("click", () => libui.showImport());
  $("btn-import-go").addEventListener("click", () => libui.doImport());
  window.__startPortal = (packId) => showCreate(packId);
  $("btn-forge-open").addEventListener("click", () => libui.showForge());
  applyAccessibility();
  setTimeout(() => startTutorial(), 900);
  $("btn-workshop-open").addEventListener("click", () => libui.showWorkshop());
  window.__openCombatPanel = () => {
    const b = document.getElementById("nav-combat");
    if (b) { b.hidden = false; b.click(); }
  };
  window.__refreshCombatPanel = () => import("./ui.js?v=30").then((ui) => ui.refreshCombatPanel?.());
  // Engine Trace: keep the last authoritative turn explanation
  window.__captureTrace = (res) => {
    if (res && res.trace) { window.__lastTrace = res.trace; }
  };
  window.__combatAct = async (act) => {
    try {
      const enc = await apiGet(`/api/campaigns/${window.__campaignId}/combat`);
      if (!enc.encounter) { toast("No encounter runs.", ""); return; }
      const res = await apiSend(`/api/campaigns/${window.__campaignId}/combat`, "POST",
        { encounter_id: enc.encounter.encounter_id, ...act });
      if (res.log) toast(res.log[res.log.length - 1] || "", "");
      window.__refreshCombatPanel?.();
      refreshView();
    } catch (e) { toast(e.message, "bad"); }
  };
  // arm the Combat nav chip whenever an encounter exists
  setInterval(async () => {
    try {
      if (document.getElementById("screen-game")?.classList.contains("active") && window.__campaignId) {
        const res = await apiGet(`/api/campaigns/${window.__campaignId}/combat`);
        const b = document.getElementById("nav-combat");
        if (b) b.hidden = !(res.encounter && res.encounter.status === "active");
      }
    } catch { /* ignore */ }
  }, 8000);
  window.__refreshPackList = () => {};
  $("btn-mp-host-back").addEventListener("click", () => mpui.leaveLobbyBack());
  $("btn-mp-join").addEventListener("click", () => mpui.confirmJoin());
  $("btn-mp-invite").addEventListener("click", () => mpui.makeInvite());
  $("btn-mp-ready").addEventListener("click", () => mpui.toggleReady());
  $("btn-mp-start").addEventListener("click", () => mpui.startVoyage());
  $("btn-mp-leave").addEventListener("click", () => mpui.leaveLobbyBack());
  $("btn-chat-close").addEventListener("click", () => mpui.toggleChat(false));
  $("chat-form").addEventListener("submit", (e) => { e.preventDefault(); mpui.sendChat(); });
  $("btn-continue").addEventListener("click", () => { mpui.refreshSessionView(); }, true);
  $("nav-chat").addEventListener("click", () => mpui.toggleChat());
  $("nav-chat").hidden = true;
  const _origEnter = window.__enterShared;
  window.__enterShared = (view) => {
    $("nav-chat").hidden = false;
    $("nav-party").hidden = false;
    $("mp-conn").hidden = false;
    _origEnter(view);
  };
}

async function boot() {
  initPanelChrome();
  wireMultiplayer();
  document.addEventListener("pointerdown", () => audio.ensure(), { once: true });
  document.addEventListener("keydown", attachScanner(handleScan));

  try {
    const health = await apiGet("/api/health");
    const settings = await apiGet("/api/settings");
    window.__aiCfg = settings.ai;
    window.__routing = settings.routing || {};
    window.__route = settings.route || {};
    refreshAIBadge();
    console.info(`Saturday Multiverse ${health.version} — data at ${health.data_dir}`);
  } catch {
    toast("The server is not answering — is it running?", "bad");
  }

  startTitleCanvas();
  await refreshCampaignList();

  $("btn-new-voyage").addEventListener("click", () => { audio.ensure(); audio.ui(); showCreate(); });
  wireMultiplayerScreens();
  $("btn-continue").addEventListener("click", () => { audio.ensure(); audio.ui(); refreshCampaignList(); });
  $("btn-title-settings").addEventListener("click", () => { audio.ensure(); openSettings(); });

  // echo shelf shortcut on the title screen footer
  const shelf = document.createElement("button");
  shelf.className = "btn btn-ghost btn-small";
  shelf.textContent = "Echoes left behind…";
  shelf.addEventListener("click", () => { audio.ensure(); openEchoShelf(); });
  document.querySelector(".title-footer").appendChild(shelf);

  $("create-name").addEventListener("input", updatePortrait);
  $("create-seed").addEventListener("input", updatePortrait);
  $("btn-create-back").addEventListener("click", () => { showScreen("screen-title"); refreshCampaignList(); });
  $("btn-create-begin").addEventListener("click", async () => {
    const name = $("create-name").value.trim();
    if (!name) { toast("Every wanderer needs a name.", "bad"); return; }
    try {
      const res = await apiSend("/api/campaigns", "POST", {
        name: `${name}: a voyage into ${state.packs.find((p) => p.id === createSel.pack)?.name || "the story"}`,
        pack_id: createSel.pack,
        character: createSel.ruleset === "dnd5e" ? {
          name,
          ruleset: "dnd5e",
          class: createSel.dndClass,
          species: createSel.dndSpecies,
          background: createSel.dndBackground,
          portrait_seed: $("create-seed").value.trim() || name,
        } : {
          name, archetype: createSel.archetype,
          extra_stat: { stat: createSel.stat },
          specialty: createSel.specialty,
          portrait_seed: $("create-seed").value.trim() || name,
          echo_ids: createSel.echoes,
        },
      });
      audio.portal();
      enterGame(res.view);
      if (createSel.echoes.length) toast(`The multiverse remembers: ${createSel.echoes.length} echo${createSel.echoes.length > 1 ? "es" : ""} woven in.`, "good");
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
