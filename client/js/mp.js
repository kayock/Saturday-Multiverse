// Saturday Multiverse — The Shared Shore (multiplayer client).
//
// One SSE stream per client: authoritative events replayed from the last
// seen sequence, then followed live. The token never appears in a URL —
// short-lived one-time tickets authenticate the stream.

import { apiGet, apiSend, setMpToken, getMpToken } from "./api.js?v=30";
import { state, setView } from "./state.js?v=30";
import { audio } from "./audio.js?v=30";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const mp = {
  active: false,
  campaignId: null,
  playerId: null,
  playerName: "",
  isHost: false,
  lastSeq: 0,
  view: null,          // session view (lobby / party state)
  source: null,
  reconnectTimer: null,
  proposalsSeen: new Set(),
};

const $ = (id) => document.getElementById(id);
const toast = (m, k) => window.__toast?.(m, k);

// ---------------------------------------------------------------- storage
function tokenKey(cid) { return `sm_mp_${cid}`; }
function seqKey(cid) { return `sm_mp_seq_${cid}`; }

function saveSession(cid, token) {
  localStorage.setItem(tokenKey(cid), token);
}
function loadSession(cid) {
  try { return JSON.parse(localStorage.getItem(tokenKey(cid)) || "null"); } catch { return null; }
}
function dropSession(cid) {
  localStorage.removeItem(tokenKey(cid));
  localStorage.removeItem(seqKey(cid));
}

// ---------------------------------------------------------------- screens
export function isJoinLink() {
  return new URLSearchParams(location.search).has("join");
}

export function bootFromLink() {
  const params = new URLSearchParams(location.search);
  const invite = params.get("join");
  if (!invite) return false;
  history.replaceState({}, "", location.pathname);
  showJoinScreen(invite);
  return true;
}

export function showHostScreen() {
  $("mp-host-campaigns").innerHTML = "<div class='fact-line'>Reading the shore's ledger…</div>";
  setScreen("screen-mp-host");
  apiGet("/api/campaigns").then((d) => {
    const rows = (d.campaigns || []).map((c) => `
      <div class="ledger-card">
        <div class="lc-kind">voyage · turn ${c.turn}</div>
        <strong>${esc(c.name)}</strong>
        <div class="fact-line">${esc(c.char_name || "")} — ${esc(c.archetype || "")}</div>
        <button class="btn btn-small btn-primary" data-mp-open="${esc(c.id)}"
                data-mp-cname="${esc(c.name)}">Host this voyage</button>
      </div>`).join("");
    $("mp-host-campaigns").innerHTML = rows ||
      "<div class='fact-line'>No voyages yet — create one in single-player first, then host it.</div>";
    $("mp-host-campaigns").querySelectorAll("[data-mp-open]").forEach((b) =>
      b.addEventListener("click", () => openHostSession(b.dataset.mpOpen)));
    audio.ui();
  }).catch((e) => { $("mp-host-campaigns").innerHTML = `<div class='fact-line'>${esc(e.message)}</div>`; });
}

async function openHostSession(cid) {
  try {
    const res = await apiSend("/api/mp/host", "POST", { campaign_id: cid, display_name: "Host" });
    setMpToken(res.token);
    saveSession(cid, JSON.stringify({ token: res.token, player_id: res.player_id }));
    mp.active = true; mp.campaignId = cid; mp.playerId = res.player_id;
    mp.view = res.view; mp.isHost = true;
    audio.portal();
    renderLobby();
    connectStream();
  } catch (e) { toast(e.message, "bad"); }
}

export function showJoinScreen(inviteToken) {
  $("mp-join").dataset.invite = inviteToken;
  setScreen("screen-mp-join");
}

export async function confirmJoin() {
  const invite = $("mp-join").dataset.invite;
  const name = ($("mp-join-name").value || "").trim();
  const charName = ($("mp-join-charname").value || "").trim() || name;
  if (!name) { toast("Your name, traveler.", "bad"); return; }
  try {
    const res = await apiSend("/api/mp/join", "POST", {
      invite_token: invite,
      display_name: name,
      character: { name: charName, archetype: $("mp-join-arch").value, specialty: $("mp-join-spec").value },
    });
    setMpToken(res.token);
    saveSession(res.campaign_id, JSON.stringify({ token: res.token, player_id: res.player_id }));
    mp.active = true; mp.campaignId = res.campaign_id; mp.playerId = res.player_id;
    mp.isHost = !!res.view?.you?.is_host;
    audio.portal();
    if (res.status === "pending") {
      toast("Waiting for the host to welcome you…", "");
      renderLobby();
      connectStream();
      return;
    }
    renderLobby();
    connectStream();
  } catch (e) { toast(e.message, "bad"); }
}

// ------------------------------------------------------------------ lobby
export function renderLobby() {
  const v = mp.view;
  if (!v) return;
  setScreen("screen-mp-lobby");
  $("mp-lobby-title").textContent = v.campaign_name;
  $("mp-lobby-status").textContent =
    v.status === "lobby" ? "gathered at the foam-line"
    : v.status === "paused" ? "the voyage is paused"
    : v.status === "ended" ? "the voyage has ended"
    : "sailing";
  const members = (v.members || []).map((m) => `
    <div class="ledger-card ${m.presence === "connected" ? "card-paid" : "card-used"}">
      <div class="lc-kind">${m.is_host ? "host · " : ""}${esc(m.presence)}${m.status === "pending" ? " · awaiting welcome" : ""}</div>
      <div style="display:flex;gap:0.6em;align-items:center">
        <div class="portrait-frame" style="width:52px;--tint:${esc(m.color)}">${
          m.character ? portrait(m.character) : "—"}</div>
        <div>
          <strong>${esc(m.name)}</strong>
          ${m.character ? `<div class="fact-line">${esc(m.character.name)} · ${esc(m.character.archetype)} · ♥${m.character.vigor}/${m.character.vigor_max} ✦${m.character.nerve}/${m.character.nerve_max}</div>` : ""}
          ${m.ready ? "<span class='chip good'>ready</span>" : "<span class='chip'>not ready</span>"}
        </div>
        ${mp.isHost && !m.is_host ? `<button class="btn btn-small btn-ghost" data-mp-remove="${esc(m.player_id)}">Send away</button>` : ""}
        ${mp.isHost && m.status === "pending" ? `<button class="btn btn-small btn-primary" data-mp-approve="${esc(m.player_id)}">Welcome</button>` : ""}
      </div>
    </div>`).join("");
  $("mp-lobby-members").innerHTML = members;
  wireLobbyMembers();
  $("btn-mp-ready").textContent = v.you.ready ? "Ready ✓" : "Ready up";
  $("btn-mp-ready").classList.toggle("btn-primary", !v.you.ready);
  $("mp-start-row").hidden = !mp.isHost;
  const inviteBox = $("mp-invite-box");
  if (mp.isHost) {
    inviteBox.hidden = false;
    const link = `${location.origin}/?join=${mp.lastInviteToken || ""}`;
    $("mp-invite-link").textContent = mp.lastInviteToken ? link : "Make an invitation below.";
  } else {
    inviteBox.hidden = true;
  }
  if (v.status === "active" && mp.entered !== true) {
    mp.entered = true;
    enterSharedShore();
  }
}

function portrait(ch) {
  // lightweight procedural presence marker (matches server portrait palettes)
  return `<svg viewBox="0 0 40 48" width="100%" height="100%">
    <circle cx="20" cy="16" r="9" fill="rgba(30,24,52,0.9)" stroke="rgba(155,140,255,0.5)" stroke-width="1"/>
    <path d="M6 46 Q20 26 34 46 Z" fill="rgba(30,24,52,0.9)" stroke="rgba(155,140,255,0.5)" stroke-width="1"/>
    <circle cx="17" cy="15" r="1.6" fill="#43e8d8"/><circle cx="23" cy="15" r="1.6" fill="#9b8cff"/>
  </svg>`;
}

function wireLobbyMembers() {
  document.querySelectorAll("[data-mp-remove]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await apiSend(`/api/mp/players/${mp.campaignId}/remove`, "POST",
        { player_id: b.dataset.mpRemove, ban: false });
      toast("They were sent on their way.", "");
      await refreshSessionView();
    } catch (e) { toast(e.message, "bad"); }
  }));
  document.querySelectorAll("[data-mp-approve]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await apiSend(`/api/mp/players/${mp.campaignId}/approve`, "POST",
        { player_id: b.dataset.mpApprove });
      await refreshSessionView();
    } catch (e) { toast(e.message, "bad"); }
  }));
}

export async function refreshSessionView() {
  if (!mp.campaignId || !getMpToken()) return;
  try {
    mp.view = await apiGet(`/api/mp/view/${mp.campaignId}`);
    mp.isHost = !!mp.view.you.is_host;
    if ($("screen-mp-lobby").classList.contains("active")) renderLobby();
    updatePartyHud();
  } catch (e) {
    if (e.status === 403 || e.status === 404) { dropSession(mp.campaignId); mp.active = false; stopStream(); }
  }
}

export async function makeInvite() {
  try {
    const res = await apiSend("/api/mp/invite", "POST",
      { campaign_id: mp.campaignId, label: "friends", uses: 0 });
    mp.lastInviteToken = res.token;
    const link = `${location.origin}/?join=${res.token}`;
    $("mp-invite-link").textContent = link;
    try { await navigator.clipboard.writeText(link); toast("Invitation copied to the clipboard.", "good"); }
    catch { toast("Invitation ready — copy it from the box.", "good"); }
    await refreshSessionView();
  } catch (e) { toast(e.message, "bad"); }
}

export async function toggleReady() {
  const v = mp.view;
  try {
    await apiSend("/api/mp/ready", "POST", { campaign_id: mp.campaignId, ready: !v.you.ready });
    await refreshSessionView();
  } catch (e) { toast(e.message, "bad"); }
}

export async function startVoyage() {
  try {
    const res = await apiSend("/api/mp/start", "POST", { campaign_id: mp.campaignId });
    mp.view = res.view;
    renderLobby();
  } catch (e) { toast(e.message, "bad"); }
}

export function leaveLobbyBack() {
  setScreen("screen-title");
  mp.active = false; stopStream();
}

// ------------------------------------------------------- shared shore live
function enterSharedShore() {
  // resume into the game screen with this player's character view
  apiGet(`/api/campaigns/${mp.campaignId}`).then((view) => {
    window.__enterShared?.(view);
    startChatBridge();
  }).catch((e) => toast(e.message, "bad"));
}

// ------------------------------------------------------------------ stream
async function connectStream() {
  stopStream();
  const token = getMpToken();
  if (!token || !mp.campaignId) return;
  mp.lastSeq = parseInt(localStorage.getItem(seqKey(mp.campaignId)) || "0", 10);
  try {
    const t = await apiSend("/api/mp/stream-ticket", "POST", { campaign_id: mp.campaignId });
    const es = new EventSource(`/api/mp/stream?ticket=${encodeURIComponent(t.ticket)}&last_seq=${mp.lastSeq}`);
    mp.source = es;
    es.onmessage = (ev) => {
      try { applyEvent(JSON.parse(ev.data)); } catch { /* keep-alive noise */ }
    };
    es.onerror = () => {
      // EventSource retries the SAME ticket — which is one-time — so restart
      // manually with a fresh ticket after a beat.
      es.close(); mp.source = null;
      clearTimeout(mp.reconnectTimer);
      mp.reconnectTimer = setTimeout(() => { if (mp.active) connectStream(); }, 2500);
      setConnBadge("reconnecting");
    };
    setConnBadge("connected");
  } catch (e) {
    setConnBadge("offline");
    mp.reconnectTimer = setTimeout(() => { if (mp.active) connectStream(); }, 3000);
  }
}

export function stopStream() {
  if (mp.source) { mp.source.close(); mp.source = null; }
  clearTimeout(mp.reconnectTimer);
}

function setConnBadge(state) {
  const el = $("mp-conn");
  if (!el) return;
  el.textContent = state;
  el.className = `chip chip-conn mp-conn-${state}`;
}

function applyEvent(ev) {
  mp.lastSeq = Math.max(mp.lastSeq, ev.seq || 0);
  localStorage.setItem(seqKey(mp.campaignId), String(mp.lastSeq));
  const d = ev.data || {};
  switch (ev.type) {
    case "narration":
      window.__mpNarration?.(d);
      pushChatLine("narration", d);
      break;
    case "dice":
      window.__mpDice?.(d);
      pushChatLine("dice", d);
      break;
    case "chat":
      pushChatLine("chat", d);
      audio.ui();
      break;
    case "system":
      pushChatLine("system", d);
      break;
    case "combat":
      pushChatLine("combat", d);
      window.__openCombatPanel?.();
      window.__refreshCombatPanel?.();
      break;
    case "presence":
      pushChatLine("presence", d);
      window.__refreshView?.();
      break;
    case "travel":
      pushChatLine("system", { text: `The party arrives at ${d.name || d.location}.` });
      window.__refreshView?.();
      audio.portal();
      break;
    case "travel_proposal":
      showTravelProposal(d);
      break;
    case "trade_offer":
      toast(`${d.from} offers ${d.item} ×${d.qty} — open the Party panel.`, "good");
      window.__refreshView?.();
      break;
    case "turn":
      pushChatLine("system", { text: `${d.name} holds the lantern.` });
      updateTurnHud(d);
      break;
    case "ready":
      refreshSessionView();
      break;
    case "session_ended":
      toast("The voyage has ended.", "");
      mp.active = false; stopStream(); dropSession(mp.campaignId);
      location.href = location.pathname;
      break;
    default:
      break;
  }
  refreshSessionViewThrottled();
}

let refreshTimer = null;
function refreshSessionViewThrottled() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(() => { refreshTimer = null; refreshSessionView(); }, 1200);
}

// -------------------------------------------------------------- chat drawer
function pushChatLine(kind, d) {
  const box = $("chat-lines");
  if (!box) return;
  const line = document.createElement("div");
  if (kind === "narration") {
    line.className = "chat-line chat-narration";
    line.innerHTML = `<span class="chat-who">GM</span><span class="chat-text">${esc(d.text || "")}</span>`;
  } else if (kind === "dice") {
    line.className = "chat-line chat-dice";
    line.innerHTML = `<span class="chat-who">${esc(d.name || "")}</span><span class="chat-text">${esc(d.text || "")}</span>`;
  } else if (kind === "chat") {
    line.className = "chat-line chat-player";
    line.innerHTML = `<span class="chat-who" style="color:${esc(d.color || "#9b8cff")}">${esc(d.name || "")}</span><span class="chat-text">${esc(d.text || "")}</span>`;
  } else {
    line.className = "chat-line chat-system";
    line.innerHTML = `<span class="chat-text">${esc(d.text || "")}</span>`;
  }
  box.appendChild(line);
  while (box.children.length > 120) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

export function toggleChat(open) {
  const drawer = $("chat-drawer");
  const show = open === undefined ? drawer.hidden : !drawer.hidden;
  drawer.hidden = !show;
  if (!show) $("chat-input").focus();
}

export async function sendChat() {
  const input = $("chat-input");
  const text = (input.value || "").trim();
  if (!text) return;
  input.value = "";
  try {
    await apiSend("/api/mp/chat", "POST", { campaign_id: mp.campaignId, text });
  } catch (e) { toast(e.message, "bad"); }
}

function startChatBridge() {
  // prefill from the durable log so history survives reloads
  const v = mp.view;
  if (v?.chat) {
    const box = $("chat-lines");
    if (box && !box.children.length) {
      for (const c of v.chat.slice(-30)) {
        if (c.type === "chat") pushChatLine("chat", c.data);
        else if (c.type === "system" || c.type === "presence") pushChatLine("system", c.data);
        else if (c.type === "dice") pushChatLine("dice", c.data);
      }
    }
  }
}

// ------------------------------------------------------ party HUD + travel
function updatePartyHud() {
  const chip = $("hud-party");
  if (!chip) return;
  const v = mp.view;
  if (!v || !mp.active) { chip.hidden = true; return; }
  chip.hidden = false;
  const online = (v.members || []).filter((m) => m.presence === "connected");
  chip.textContent = `⚓ ${online.length}/${(v.members || []).length}`;
  chip.title = `Together on the shore: ${online.map((m) => m.name).join(", ")}`;
  // presence markers for the canvas
  window.__hub?.setParty(
    (v.members || [])
      .filter((m) => m.presence === "connected" && m.character)
      .map((m) => ({
        name: m.name, color: m.color,
        charName: m.character.name,
        isMe: m.player_id === mp.playerId,
      })),
  );
}

function updateTurnHud(d) {
  const chip = $("hud-turn-queue");
  if (!chip) return;
  const v = mp.view;
  if (!v || v.mode !== "turns") { chip.hidden = true; return; }
  const current = (v.members || []).find((m) => m.player_id === d.player_id);
  chip.hidden = false;
  chip.textContent = `lantern: ${d.name || "?"}`;
  chip.classList.toggle("mine", d.player_id === mp.playerId);
}

function showTravelProposal(d) {
  if (mp.proposalsSeen.has(d.destination + d.by)) return;
  mp.proposalsSeen.add(d.destination + d.by);
  const box = $("travel-proposal");
  $("tp-text").innerHTML = `<strong>${esc(d.by)}</strong> proposes the party step through to
    <strong>${esc(d.name || d.destination)}</strong>.`;
  box.hidden = false;
  $("tp-yes").onclick = async () => {
    box.hidden = true;
    try { await apiSend("/api/mp/travel/vote", "POST", { campaign_id: mp.campaignId, accept: true }); }
    catch (e) { toast(e.message, "bad"); }
  };
  $("tp-no").onclick = async () => {
    box.hidden = true;
    try { await apiSend("/api/mp/travel/vote", "POST", { campaign_id: mp.campaignId, accept: false }); }
    catch (e) { toast(e.message, "bad"); }
  };
  setTimeout(() => { box.hidden = true; }, 45000);
}

// ------------------------------------------------------------------ export
export async function resumeIfHosted(cid) {
  const stored = loadSession(cid);
  if (!stored || !stored.token) return false;
  try {
    setMpToken(stored.token);
    const res = await apiSend("/api/mp/reconnect", "POST",
      { campaign_id: cid, token: stored.token });
    mp.active = true; mp.campaignId = cid;
    mp.playerId = res.player_id;
    mp.isHost = !!res.view.you.is_host;
    mp.view = res.view;
    if (res.view.status === "active") mp.entered = true;
    connectStream();
    updatePartyHud();
    $("mp-conn").hidden = false;
    $("nav-chat").hidden = false;
    return true;
  } catch (e) {
    dropSession(cid);
    return false;
  }
}

export function mpState() { return mp; }
export function setSessionView(v) { mp.view = v; }
export function markEntered() { mp.entered = true; }

function setScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(id).classList.add("active");
}
