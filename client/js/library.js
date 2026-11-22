// Saturday Multiverse — The Infinite Library + Campaign Forge (client).

import { apiGet, apiSend } from "./api.js?v=30";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const $ = (id) => document.getElementById(id);
const toast = (m, k) => window.__toast?.(m, k);

function setScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(id).classList.add("active");
}

// ---------------------------------------------------------------- library
export async function showLibrary() {
  setScreen("screen-library");
  $("library-body").innerHTML = "<div class='fact-line'>Opening the stacks…</div>";
  try {
    const data = await apiGet("/api/library");
    renderLibrary(data);
  } catch (e) {
    $("library-body").innerHTML = `<div class='fact-line'>${esc(e.message)}</div>`;
  }
}

function renderLibrary(data) {
  const docs = (data.docs || []).map((d) => `
    <div class="ledger-card">
      <div class="lc-kind">${esc(d.doc_type)} · ${d.n_chunks} passages · ${d.n_words.toLocaleString()} words${d.private ? " · <span class='chip'>private</span>" : ""}</div>
      <strong>${esc(d.title)}</strong>
      <div class="fact-line">${esc(d.author || "unknown author")}${d.source_url ? ` — <a href="${esc(d.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</div>
      <div class="fact-line">license: ${esc(d.license)}</div>
      <button class="btn btn-small btn-primary" data-forge-doc="${esc(d.id)}">Forge a campaign</button>
      <button class="btn btn-small btn-ghost" data-lib-delete="${esc(d.id)}">Remove</button>
    </div>`).join("");
  const packs = (data.packs || []).map((p) => `
    <div class="ledger-card ${p._builtin ? "" : "card-paid"}">
      <div class="lc-kind">${p._builtin ? "starter adventure" : "forged campaign"} · ${esc((p.genre_tags || []).join(", "))}</div>
      <strong>${esc(p.name)}</strong>
      <div class="fact-line">${esc(p.summary || "")}</div>
      <button class="btn btn-small btn-primary" data-preview-pack="${esc(p.id)}">Preview &amp; open a portal</button>
    </div>`).join("");
  $("library-body").innerHTML = `
    <div class="sect"><h4>Installed adventures — each one is a door</h4>${packs || "<div class='fact-line'>No adventures installed yet.</div>"}</div>
    <div class="sect"><h4>The stacks — imported sources</h4>${docs || "<div class='fact-line'>The library stands empty. Import a book below.</div>"}</div>`;
  $("library-body").querySelectorAll("[data-forge-doc]").forEach((b) =>
    b.addEventListener("click", () => forgeDocument(b.dataset.forgeDoc)));
  $("library-body").querySelectorAll("[data-lib-delete]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await apiSend(`/api/library/${b.dataset.libDelete}`, "DELETE");
        toast("Removed from the stacks.", "");
        showLibrary();
      } catch (e) { toast(e.message, "bad"); }
    }));
  $("library-body").querySelectorAll("[data-preview-pack]").forEach((b) =>
    b.addEventListener("click", () => showPreview(b.dataset.previewPack)));
}

export function showImport() {
  setScreen("screen-import");
  $("import-status").textContent = "";
}

export async function doImport() {
  const fileInput = $("import-file");
  const file = fileInput.files && fileInput.files[0];
  if (!file) { toast("Choose a file first — the stacks take PDF, EPUB, DOCX, TXT, Markdown, HTML or pack JSON.", "bad"); return; }
  $("import-status").textContent = "Reading and indexing…";
  const buf = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  try {
    const doc = await apiSend("/api/library/import", "POST", {
      filename: file.name,
      data_b64: btoa(binary),
      title: $("import-title").value.trim(),
      author: $("import-author").value.trim(),
      source_url: $("import-source").value.trim(),
      license: $("import-license").value.trim() || "Private",
      attribution: $("import-attribution").value.trim(),
      private: $("import-private").checked,
    });
    $("import-status").textContent = `Imported: ${doc.title} — ${doc.n_chunks} indexed passages.`;
    toast("The book is on the shelf.", "good");
    setTimeout(() => showLibrary(), 900);
  } catch (e) {
    $("import-status").textContent = `Import failed: ${e.message}`;
    toast(e.message, "bad");
  }
}

// ------------------------------------------------------------------ forge
export function forgeDocument(docId, docTitle) {
  setScreen("screen-forge");
  $("forge-body").innerHTML = `
    <div class="sect"><h4>Forge a campaign from: ${esc(docTitle || "the book")}</h4>
      <div class="fact-line">The model reads the ENTIRE document in bounded windows, consolidates
        the cast and story, builds a world bible (including how the story ends), and drafts the campaign.
        You review before anything plays.</div>
      <label class="field-label">Adaptation mode</label>
      <div class="chip-row" id="forge-mode">
        <span class="chip selected" data-mode="faithful">Faithful Adaptation — follow the book, allow player choices</span>
        <span class="chip" data-mode="rewrite">Alternate History — the world is the book's, and players can change events</span>
        <span class="chip" data-mode="expanded">Expanded Universe — new adventures in the book's world</span>
      </div>
      <label class="field-label">Conversion AI</label>
      <div id="forge-ai-box" class="fact-line">Checking local models…</div>
      <label class="field-label">Campaign scope</label>
      <div class="chip-row" id="forge-scope">
        <span class="chip selected" data-scope="short">Short adventure</span>
        <span class="chip" data-scope="multi_session">Multi-session campaign</span>
        <span class="chip" data-scope="extended">Extended campaign</span>
      </div>
      <div class="create-actions">
        <button id="btn-forge-go" class="btn btn-primary">Begin the conversion</button>
        <button id="btn-forge-back" class="btn btn-ghost">Back</button>
      </div>
    </div>`;
  const pick = (boxId, attr) => {
    let val = null;
    $(boxId).querySelectorAll("[data-" + attr + "]").forEach((c) => c.addEventListener("click", () => {
      $(boxId).querySelectorAll("[data-" + attr + "]").forEach((x) => x.classList.remove("selected"));
      c.classList.add("selected");
      val = c.dataset[attr];
    }));
    return () => val || $(boxId).querySelector(".chip.selected")?.dataset[attr];
  };
  const mode = pick("forge-mode", "mode");
  const scope = pick("forge-scope", "scope");
  $("btn-forge-back").addEventListener("click", () => showLibrary());
  loadForgeAi(docId);
  $("btn-forge-go").addEventListener("click", async () => {
    try {
      const approved = Boolean(document.getElementById("forge-approve")?.checked);
      const job = await apiSend("/api/forge/jobs", "POST",
        { doc_id: docId, mode: mode(), scope: scope(), transmit_approved: approved });
      pollJob(job.id);
    } catch (e) { toast(e.message, "bad"); }
  });
}

async function loadForgeAi(docId) {
  const box = document.getElementById("forge-ai-box");
  if (!box) return;
  try {
    const data = await apiGet(`/api/forge/ai?doc_id=${encodeURIComponent(docId)}`);
    const preview = data.preview || {};
    const cat = data.catalog || {};
    const forge = cat.forge || {};
    const light = (cat.lightweight || []).map((m) =>
      `<option value="${esc(m.base_url)}|${esc(m.model)}">Lightweight · ${esc(m.model)} on ${esc(m.host)}${m.loaded ? " (running)" : ""}</option>`).join("");
    const advanced = (cat.advanced || []).map((m) =>
      `<option value="${esc(m.base_url)}|${esc(m.model)}">Advanced · ${esc(m.model)} on ${esc(m.host)}${m.loaded ? " (running)" : " (not started)"}</option>`).join("");
    const where = preview.locality === "online" ? "online" : (preview.locality === "blocked" ? "blocked — would leave the network" : "local");
    const cost = preview.cost_estimate == null
      ? esc(preview.note || "")
      : `${esc(preview.currency || "USD")} ${preview.cost_estimate} — ${esc(preview.note || "")}`;
    box.innerHTML = `
      <div class="chip-row" id="forge-source">
        <span class="chip ${forge.selection === "auto_local" || !forge.selection ? "selected" : ""}" data-selection="auto_local">Automatic local</span>
        <span class="chip ${forge.selection === "local" ? "selected" : ""}" data-selection="local">Select local model</span>
        <span class="chip ${forge.selection === "online" ? "selected" : ""}" data-selection="online">Online provider</span>
      </div>
      <div class="fact-line">Gameplay Game Master stays on ${esc(preview.gameplay_model || "its own setting")}. This choice is only for conversion.</div>
      <div class="fact-line">Now: ${esc(preview.model || "none")} · ${esc(where)} · ${esc(preview.provider || "")}</div>
      <div class="fact-line">Workload: about ${preview.windows || 0} windows and ${preview.calls || 0} model calls. ${cost}</div>
      <div class="setting-row" id="forge-local-row" ${forge.selection === "local" ? "" : "hidden"}>
        <select id="forge-local-model" class="input"><option value="">Choose a local model</option>${light}${advanced}</select>
      </div>
      <div id="forge-online-row" ${forge.selection === "online" ? "" : "hidden"}>
        <div class="setting-row"><input id="forge-provider" class="input" placeholder="Provider name (OpenRouter, a hosted API, …)" value="${esc(forge.provider_name || "")}"></div>
        <div class="setting-row"><input id="forge-url" class="input" placeholder="https://provider.example/v1" value="${esc(forge.base_url || "")}"></div>
        <div class="setting-row"><input id="forge-model" class="input" placeholder="model id" value="${esc(forge.model || "")}"></div>
        <div class="setting-row"><input id="forge-key" class="input" type="password" placeholder="${forge.has_key ? "key stored — type to replace" : "API key, if the provider requires one"}"></div>
        <div class="setting-row"><input id="forge-price-in" class="input" type="number" min="0" step="0.01" placeholder="optional $ / million input tokens" value="${forge.price_input_per_million ?? ""}"></div>
        <div class="setting-row"><input id="forge-price-out" class="input" type="number" min="0" step="0.01" placeholder="optional $ / million output tokens" value="${forge.price_output_per_million ?? ""}"></div>
        <label class="fact-line"><input type="checkbox" id="forge-approve"> I approve sending this manuscript outside the local network for this conversion only.</label>
      </div>
      <div class="setting-row">
        <button type="button" id="forge-ai-save" class="btn btn-small">Save conversion AI</button>
        <button type="button" id="forge-ai-test" class="btn btn-small">Test connection</button>
      </div>
      <div id="forge-ai-status" class="fact-line"></div>`;
    const pickSel = (id) => {
      box.querySelectorAll("#forge-source .chip").forEach((c) => c.classList.remove("selected"));
      box.querySelector(`[data-selection="${id}"]`)?.classList.add("selected");
      document.getElementById("forge-local-row").hidden = id !== "local";
      document.getElementById("forge-online-row").hidden = id !== "online";
    };
    box.querySelectorAll("#forge-source .chip").forEach((c) =>
      c.addEventListener("click", () => pickSel(c.dataset.selection)));
    document.getElementById("forge-ai-save")?.addEventListener("click", async () => {
      try {
        await apiSend("/api/settings", "PUT", { forge_ai: forgePayload() });
        toast("Conversion model saved. The Game Master is unchanged.", "good");
        loadForgeAi(docId);
      } catch (e) { toast(e.message, "bad"); }
    });
    document.getElementById("forge-ai-test")?.addEventListener("click", async () => {
      const st = document.getElementById("forge-ai-status");
      st.textContent = "Testing the conversion endpoint…";
      try {
        const res = await apiSend("/api/forge/ai/test", "POST", {
          forge_ai: forgePayload(),
          transmit_approved: Boolean(document.getElementById("forge-approve")?.checked),
        });
        st.textContent = res.ok ? `Connected (${res.model || "model"}, ${res.latency_ms} ms). No manuscript was sent.`
          : (res.detail || "Could not connect.");
      } catch (e) { st.textContent = e.message; }
    });
  } catch (e) {
    box.textContent = e.message;
  }
}

function forgePayload() {
  const selected = document.querySelector("#forge-source .chip.selected")?.dataset.selection || "auto_local";
  const payload = { selection: selected };
  if (selected === "local") {
    const raw = document.getElementById("forge-local-model")?.value || "";
    const cut = raw.indexOf("|");
    payload.base_url = cut >= 0 ? raw.slice(0, cut) : "";
    payload.model = cut >= 0 ? raw.slice(cut + 1) : "";
    payload.provider_name = "local";
  }
  if (selected === "online") {
    payload.provider_name = document.getElementById("forge-provider")?.value || "";
    payload.base_url = document.getElementById("forge-url")?.value || "";
    payload.model = document.getElementById("forge-model")?.value || "";
    const key = document.getElementById("forge-key")?.value || "";
    if (key) payload.api_key = key;
    const pin = document.getElementById("forge-price-in")?.value;
    const pout = document.getElementById("forge-price-out")?.value;
    payload.price_input_per_million = pin === "" ? null : Number(pin);
    payload.price_output_per_million = pout === "" ? null : Number(pout);
  }
  return payload;
}

async function pollJob(jobId) {
  setScreen("screen-forge");
  $("forge-body").innerHTML = "<div class='fact-line'>Opening the job…</div>";
  const timer = setInterval(async () => {
    try {
      const job = await apiGet(`/api/forge/jobs/${jobId}`);
      renderJob(job, timer);
      if (["review", "approved", "failed", "cancelled"].includes(job.status)) clearInterval(timer);
    } catch (e) { clearInterval(timer); toast(e.message, "bad"); }
  }, 1500);
}

function renderJob(job, timer) {
  const cov = job.coverage || {};
  const pct = Math.round((job.progress || 0) * 100);
  const notes = (job.notes || []).slice(-6).map((n) => `<div class="fact-line">• ${esc(n)}</div>`).join("");
  $("forge-body").innerHTML = `
    <div class="sect"><h4>Conversion ${esc(job.status.toUpperCase())} — ${pct}%</h4>
      <div class="bar bar-vigor" style="width:100%"><i style="width:${pct}%"></i></div>
      <div class="fact-line">${esc(job.stage || "")}</div>
      ${cov.total_chunks ? `<div class="fact-line">source scan: ${cov.chunks_visited || 0}/${cov.total_chunks} chunks ·
        ${cov.chapters || 0} chapters · ${cov.windows_planned || 0} windows · ${cov.calls_made || 0} model calls ·
        ${cov.windows_failed || 0} failed windows
        ${cov.extraction_successful ? "· extraction complete" : (cov.coverage_complete ? "· scan finished, extraction incomplete" : "· partial")}</div>
        ${(cov.failed_windows || []).map((w) => `<div class="fact-line">failed window ${esc(String(w.window))}: ${esc(w.reason || "")}</div>`).join("")}` : ""}
      ${job.error ? `<div class="fact-line" style="color:#e08">error: ${esc(job.error)}</div>` : ""}
      ${notes}
      <div class="setting-row">
        ${job.status === "review" ? `<button id="btn-job-open" class="btn btn-primary">Open in the editor</button>` : ""}
        ${["queued","analyzing","bible","generating","validating"].includes(job.status)
          ? `<button id="btn-job-cancel" class="btn btn-ghost">Cancel</button>` : ""}
        ${(cov.failed_windows || []).length ? `<button id="btn-job-windows" class="btn btn-small">Retry failed sections</button>` : ""}
        ${["failed","cancelled"].includes(job.status) ? `<button id="btn-job-retry" class="btn btn-primary">Retry</button>` : ""}
      </div>
    </div>`;
  $("btn-job-open")?.addEventListener("click", async () => {
    clearInterval(timer);
    renderDraft(await apiGet(`/api/forge/drafts/${job.draft_id}`));
  });
  $("btn-job-cancel")?.addEventListener("click", async () => {
    await apiSend(`/api/forge/jobs/${job.id}/cancel`, "POST", {});
  });
  $("btn-job-retry")?.addEventListener("click", async () => {
    await apiSend(`/api/forge/jobs/${job.id}/retry`, "POST", {});
    pollJob(job.id);
  });
  $("btn-job-windows")?.addEventListener("click", async () => {
    try {
      const next = await apiSend(`/api/forge/jobs/${job.id}/retry-windows`, "POST", {});
      renderJob(next, timer);
    } catch (e) { toast(e.message, "bad"); }
  });
}

export async function showForge() {
  setScreen("screen-forge");
  try {
    const data = await apiGet("/api/forge/drafts");
    const drafts = (data.drafts || []).map((d) => `
      <div class="ledger-card">
        <div class="lc-kind">draft · ${esc(d.mode)} · ${esc(d.status)} · source: ${esc(d.doc_title)}</div>
        <button class="btn btn-small btn-primary" data-open-draft="${esc(d.id)}">Open in the editor</button>
      </div>`).join("");
    $("forge-body").innerHTML = `
      <div class="sect"><h4>Campaign Forge — drafts</h4>${drafts || "<div class='fact-line'>No drafts yet. Forge one from a book in the Library.</div>"}</div>`;
    $("forge-body").querySelectorAll("[data-open-draft]").forEach((b) =>
      b.addEventListener("click", async () => {
        try { renderDraft(await apiGet(`/api/forge/drafts/${b.dataset.openDraft}`)); }
        catch (e) { toast(e.message, "bad"); }
      }));
  } catch (e) {
    $("forge-body").innerHTML = `<div class='fact-line'>${esc(e.message)}</div>`;
  }
}

function renderDraft(draft) {
  const pack = draft.pack || {};
  const adv = (pack.adventures || [])[0] || {};
  const scenes = adv.scenes ? (Object.values(adv.scenes)) : [];
  const notes = (draft.notes || []).slice(-8).map((n) => `<div class="fact-line">• ${esc(n)}</div>`).join("");
  const scenesHtml = scenes.map((s, i) => `
    <div class="ledger-card">
      <div class="lc-kind">scene · ${esc(s.id)}</div>
      <input class="input" data-edit="adventures.0.scenes.${s.id}.title" value="${esc(s.title)}">
      <input class="input" data-edit="adventures.0.scenes.${s.id}.brief" value="${esc(s.brief || "")}" placeholder="brief">
      <div class="fact-line">choices: ${(s.choices || []).map((c, ci) =>
        `<input class="input" style="max-width:220px;display:inline-block" data-edit="adventures.0.scenes.${s.id}.choices.${ci}.label" value="${esc(c.label)}">`).join(" ")}</div>
      ${(s.choices || []).map((c, ci) => `
        <div class="fact-line">
          <label class="fact-line">choice ${ci + 1} goes to:
            <select class="input" data-edit="adventures.0.scenes.${s.id}.choices.${ci}.goto">
              ${scenes.map((o) => `<option value="${esc(o.id)}" ${c.goto === o.id ? "selected" : ""}>${esc(o.title)}</option>`).join("")}
            </select></label>
        </div>`).join("")}
    </div>`).join("");
  const npcsHtml = (pack.npcs || []).map((n, i) => `
    <div class="ledger-card">
      <input class="input" data-edit="npcs.${i}.name" value="${esc(n.name)}">
      <input class="input" data-edit="npcs.${i}.role" value="${esc(n.role || "")}" placeholder="role">
      <input class="input" data-edit="npcs.${i}.desc" value="${esc(n.desc || "")}" placeholder="description">
    </div>`).join("");
  const questsHtml = (pack.intro_quests || []).map((q, i) => `
    <input class="input" data-edit="intro_quests.${i}.title" value="${esc(q.title)}">`).join("");
  const secretsHtml = (pack.gm_secrets || []).map((s, i) => `
    <input class="input" data-edit="gm_secrets.${i}" value="${esc(s)}">`).join("");
  $("forge-body").innerHTML = `
    <div class="sect"><h4>Draft: <input class="input" data-edit="name" value="${esc(pack.name || "")}">
      <span class="chip">${esc(draft.status)}</span></h4>
      <input class="input" data-edit="summary" value="${esc(pack.summary || "")}" placeholder="summary">
      <input class="input" data-edit="gm_style" value="${esc(pack.gm_style || "")}" placeholder="gm voice">
      ${notes}
      <div class="fact-line" id="forge-problems"></div>
      <div class="setting-row">
        <button class="btn btn-small btn-primary" data-save="1">Save edits</button>
        <button class="btn btn-small" data-regen="world">Regenerate world</button>
        <button class="btn btn-small" data-regen="adventure">Regenerate adventure</button>
        <button class="btn btn-small btn-primary" data-approve="1">Approve &amp; install</button>
        <button class="btn btn-small btn-ghost" data-back="1">Back</button>
      </div>
      <div class="setting-row"><input id="forge-notes" class="input" maxlength="300" placeholder="editor guidance for regeneration (optional)"></div>
    </div>
    <div class="sect"><h4>Adventure flow</h4><div id="flow-graph"></div><div class="fact-line" id="flow-findings"></div></div>
    <div class="sect"><h4>Cast — edit any name or role without asking the AI</h4>${npcsHtml || "<div class='fact-line'>none extracted</div>"}</div>
    <div class="sect"><h4>Adventure: <input class="input" data-edit="adventures.0.title" value="${esc(adv.title || "")}"></h4>${scenesHtml}</div>
    <div class="sect"><h4>Quests</h4>${questsHtml}</div>
    <div class="sect"><h4>Endings</h4><div class="fact-line">${esc(Object.keys(adv.endings || {}).join(", "))}</div></div>
    <div class="sect"><h4>GM secrets (hidden from players)</h4>${secretsHtml}</div>
    <div class="sect"><h4>History</h4><div id="forge-history"><div class="fact-line">…</div></div>
      <div class="setting-row">
        <button class="btn btn-small btn-ghost" data-duplicate="1">Duplicate draft</button>
        <a class="btn btn-small btn-ghost" id="forge-export" download="draft.json">Export JSON</a>
      </div>
    </div>
    <div class="sect"><h4>Licensing (carried from the source)</h4>
      <div class="fact-line">${esc(JSON.stringify(pack.license || {}))}</div></div>`;
  drawFlowGraph(pack);
  loadFlowFindings(draft.id);
  loadHistory(draft.id);
  $("forge-export").href = "data:application/json;charset=utf-8," +
    encodeURIComponent(JSON.stringify(pack, null, 2));
  document.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", async () => {
    const ops = [];
    document.querySelectorAll("[data-edit]").forEach((el) => {
      const path = el.dataset.edit;
      // read the CURRENT value from the live draft for comparison
      ops.push({ op: "set", path, value: el.value });
    });
    try {
      const res = await apiSend(`/api/forge/drafts/${draft.id}/edit`, "POST",
        { ops, note: "manual edit" });
      toast(`Saved (${res.applied} edits, revision ${res.revision}).`, "good");
      renderDraft(res);
    } catch (e) { toast(e.message, "bad"); }
  }));
  document.querySelector("[data-duplicate]")?.addEventListener("click", async () => {
    try {
      const d2 = await apiSend(`/api/forge/drafts/${draft.id}/duplicate`, "POST", {});
      toast("Duplicated — iterate freely.", "good");
      renderDraft(d2);
    } catch (e) { toast(e.message, "bad"); }
  });
  $("forge-body").querySelectorAll("[data-regen]").forEach((b) =>
    b.addEventListener("click", async () => {
      const notesText = ($("forge-notes")?.value || "").trim();
      b.disabled = true;
      try {
        renderDraft(await apiSend(`/api/forge/drafts/${draft.id}/regen`, "POST",
          { section: b.dataset.regen, notes: notesText }));
        toast(`Section regenerated.`, "good");
      } catch (e) { toast(e.message, "bad"); }
    }));
  const approve = $("forge-body").querySelector("[data-approve]");
  approve?.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/forge/drafts/${draft.id}/approve`, "POST");
      toast(`Installed as ${res.pack_id} — it is now a door on the shore.`, "good");
      window.__refreshPackList?.();
      showLibrary();
    } catch (e) { toast(e.message, "bad"); }
  });
  $("forge-body").querySelector("[data-back]")?.addEventListener("click", () => showForge());
}

// ---------------------------------------------------------------- preview
async function showPreview(packId) {
  setScreen("screen-preview");
  $("preview-body").innerHTML = "<div class='fact-line'>Opening the door…</div>";
  try {
    const p = await apiGet(`/api/packs/${packId}/preview`);
    const lic = p.license || {};
    $("preview-body").innerHTML = `
      <div class="sect"><h4>${esc(p.name)}</h4>
        <div class="fact-line">${esc(p.summary)}</div>
        <div class="fact-line">gm voice: ${esc(p.gm_style)}</div>
        <div class="fact-line">rulesets: ${esc((p.supports_rulesets || []).join(", "))} · omens: ${p.n_omens} · items: ${p.n_items}</div>
      </div>
      <div class="sect"><h4>Places</h4>${(p.locations || []).map((l) =>
        `<div class="fact-line"><strong>${esc(l.name)}</strong> — ${esc(l.short)}</div>`).join("")}</div>
      <div class="sect"><h4>Cast</h4>${(p.npcs || []).map((n) =>
        `<div class="fact-line"><strong>${esc(n.name)}</strong> (${esc(n.role)}) — ${esc(n.desc)}</div>`).join("")}</div>
      <div class="sect"><h4>Adventure</h4>${(p.adventures || []).map((a) => `
        <div class="ledger-card"><div class="lc-kind">${esc(a.title)}</div>
          <div class="fact-line">${esc(a.summary)}</div>
          <div class="fact-line">scenes: ${(a.scenes || []).length} · endings: ${esc((a.endings || []).join(", "))}</div>
        </div>`).join("")}</div>
      <div class="sect"><h4>Source &amp; licensing</h4>
        <div class="fact-line">${esc(lic.source_title || "")} — ${esc(lic.author || "")}</div>
        <div class="fact-line">${lic.source_url ? `<a href="${esc(lic.source_url)}" target="_blank" rel="noopener">${esc(lic.source_url)}</a>` : "no source link"}</div>
        <div class="fact-line">${esc(lic.license || "")}</div>
        <div class="fact-line">${esc(lic.attribution || "")}</div>
      </div>
      <div class="create-actions">
        <button id="btn-open-portal" class="btn btn-primary">Open a portal into this story</button>
        <button id="btn-preview-back" class="btn btn-ghost">Back to the Library</button>
      </div>`;
    $("btn-open-portal").addEventListener("click", () => window.__startPortal?.(packId));
    $("btn-preview-back").addEventListener("click", () => showLibrary());
  } catch (e) {
    $("preview-body").innerHTML = `<div class='fact-line'>${esc(e.message)}</div>`;
  }
}

export function leaveLibrary() { setScreen("screen-title"); }

// ---------- v0.3.6: flow graph, history, validation displays ----------
function drawFlowGraph(pack) {
  const box = document.getElementById("flow-graph");
  if (!box) return;
  const adv = (pack.adventures || [])[0] || {};
  const scenes = adv.scenes || {};
  const ids = Object.keys(scenes);
  const endings = Object.keys(adv.endings || {});
  if (!ids.length) { box.innerHTML = "<div class='fact-line'>No scenes yet.</div>"; return; }
  const W = Math.min(760, Math.max(320, ids.length * 130));
  const H = 90 + Math.ceil(ids.length / 6) * 110 + endings.length * 40;
  const pos = {};
  ids.forEach((id, i) => {
    const col = i % 6, row = Math.floor(i / 6);
    pos[id] = { x: 50 + col * (W - 100) / Math.max(1, Math.min(5, ids.length - 1)), y: 40 + row * 110 };
  });
  let edgesSvg = "";
  const drawEdge = (from, to, dashed) => {
    if (!pos[from] || !pos[to]) return;
    const a = pos[from], b = pos[to];
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 14;
    edgesSvg += `<path d="M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}"
      fill="none" stroke="var(--teal)" stroke-opacity="0.7" ${dashed ? "stroke-dasharray='4 3'" : ""}/>
      <circle cx="${b.x}" cy="${b.y}" r="3" fill="var(--teal)"/>`;
  };
  ids.forEach((sid) => {
    (scenes[sid].choices || []).forEach((c) => {
      if (c.goto && scenes[c.goto]) drawEdge(sid, c.goto, false);
      const p = c.on_pass?.goto, f = c.on_fail?.goto;
      if (p && scenes[p]) drawEdge(sid, p, false);
      if (f && scenes[f]) drawEdge(sid, f, true);
    });
  });
  const nodesSvg = ids.map((sid) => {
    const p = pos[sid];
    const isEntry = sid === adv.entry;
    return `<rect x="${p.x - 52}" y="${p.y - 18}" width="104" height="36" rx="8"
      fill="var(--deep)" stroke="${isEntry ? "var(--gold)" : "var(--purple)"}" stroke-width="${isEntry ? 2 : 1}"/>
      <text x="${p.x}" y="${p.y + 4}" text-anchor="middle" fill="var(--text)" font-size="10">${esc((scenes[sid].title || sid).slice(0, 14))}</text>`;
  }).join("");
  const endNodes = endings.map((eid, i) => {
    const y = H - 30;
    const x = W / (endings.length + 1) * (i + 1);
    return `<rect x="${x - 52}" y="${y - 14}" width="104" height="28" rx="8" fill="none" stroke="var(--gold)"/>
      <text x="${x}" y="${y + 4}" text-anchor="middle" fill="var(--gold)" font-size="10">${esc(eid.slice(0, 14))}</text>`;
  }).join("");
  box.innerHTML = `<div style="overflow-x:auto"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="adventure flow graph">
    ${edgesSvg}${nodesSvg}${endNodes}</svg></div>`;
}

async function loadFlowFindings(draftId) {
  const box = document.getElementById("flow-findings");
  const problems = document.getElementById("forge-problems");
  if (!box) return;
  try {
    const res = await apiGet(`/api/forge/drafts/${draftId}/flow`);
    box.innerHTML = (res.findings || []).map((f) => `<div class="fact-line">⚠ ${esc(f)}</div>`).join("")
      || "The flow holds: every scene is reachable, every ending can be earned.";
  } catch { /* ignore */ }
  try {
    const d = await apiGet(`/api/forge/drafts/${draftId}`);
    const pack = d.pack || {};
    const adv = (pack.adventures || [])[0] || {};
    const scenes = adv.scenes || {};
    const missing = [];
    for (const [sid, sc] of Object.entries(scenes)) {
      for (const c of (sc.choices || [])) {
        for (const dest of [c.goto, c.on_pass?.goto, c.on_fail?.goto]) {
          if (dest && !scenes[dest] && !(adv.endings || {})[dest]) {
            missing.push(`${sid} → ${dest}`);
          }
        }
      }
    }
    if (problems) {
      problems.innerHTML = missing.length
        ? `Missing targets: ${esc(missing.join(", "))}`
        : "";
    }
  } catch { /* ignore */ }
}

async function loadHistory(draftId) {
  const box = document.getElementById("forge-history");
  if (!box) return;
  try {
    const res = await apiGet(`/api/forge/drafts/${draftId}/history`);
    const hist = res.history || [];
    box.innerHTML = hist.map((h) => `
      <div class="setting-row"><span style="flex:1;color:var(--dim);font-size:0.85em">
        #${h.seq} · ${esc(h.note)} · ${esc(h.created_at)}</span>
        <button class="btn btn-small btn-ghost" data-restore="${h.seq}">Restore</button>
        <button class="btn btn-small btn-ghost" data-compare="${h.seq}">Compare</button></div>`).join("")
      || "<div class='fact-line'>No revisions yet — save an edit to create one.</div>";
    box.querySelectorAll("[data-restore]").forEach((b) => b.addEventListener("click", async () => {
      try { renderDraft(await apiSend(`/api/forge/drafts/${draftId}/restore`, "POST", { seq: parseInt(b.dataset.restore, 10) })); }
      catch (e) { toast(e.message, "bad"); }
    }));
    box.querySelectorAll("[data-compare]").forEach((b) => b.addEventListener("click", async () => {
      try {
        const latest = hist[hist.length - 1]?.seq || parseInt(b.dataset.compare, 10);
        const diff = await apiGet(`/api/forge/drafts/${draftId}/compare?a=${b.dataset.compare}&b=${latest}`);
        toast(`${diff.n_changed} changed · ${diff.n_added} added · ${diff.n_removed} removed`, "");
      } catch (e) { toast(e.message, "bad"); }
    }));
  } catch { /* ignore */ }
}

// ---------- v0.3.6 steering: the Worldbuilding Workshop ----------
// Collaborative homebrew runs on the SAME universal Forge: drafts, proposals,
// conflict review, and the same engine validation as literary adaptations.
let workshopDraft = null;

export function showWorkshop() {
  setScreen("screen-forge");
  $("forge-body").innerHTML = `
    <div class="sect"><h4>The Worldbuilding Workshop</h4>
      <div class="fact-line">Write a world together on the same Forge the Library uses.
        One creator reviews and approves; collaborators propose NPCs, places, quests,
        dialogue and secrets. Suggestions from the model are only ever suggestions —
        nobody's work is overwritten without a review.</div>
      <div class="setting-row">
        <input id="ws-name" class="input" maxlength="60" placeholder="Name your world">
        <button id="btn-ws-create" class="btn btn-small btn-primary">Open a new world</button>
      </div>
      <div id="ws-body"><div class="fact-line">No world open yet.</div></div>
    </div>`;
  $("btn-ws-create").addEventListener("click", async () => {
    try {
      const v = await apiSend("/api/forge/collab", "POST", { name: $("ws-name").value || "Our World" });
      workshopDraft = v.draft_id;
      renderWorkshop(v);
      toast("World opened — share the shore and invite collaborators.", "good");
    } catch (e) { toast(e.message, "bad"); }
  });
  $("ws-open-existing")?.addEventListener("click", () => {});
}

export async function openWorkshopDraft(draftId) {
  workshopDraft = draftId;
  renderWorkshop(await apiGet(`/api/forge/collab/${draftId}`));
}

export async function renderWorkshop(v) {
  workshopDraft = v.draft_id;
  const pack = v.pack || {};
  const meCreator = v.you_are_creator;
  const head = v.head_rev || 1;
  const contribForm = `
    <div class="sect"><h4>Contribute</h4>
      <div class="fact-line">Your change is proposed, not applied — the creator reviews it.</div>
      <div class="chip-row" id="ws-kind">
        <span class="chip selected" data-k="npc">NPC</span>
        <span class="chip" data-k="location">Location</span>
        <span class="chip" data-k="quest">Quest</span>
        <span class="chip" data-k="lore">Lore</span>
        <span class="chip" data-k="secret">GM secret (hidden)</span>
      </div>
      <div class="setting-row"><input id="ws-f-name" class="input" maxlength="60" placeholder="Name"></div>
      <div class="setting-row"><input id="ws-f-desc" class="input" maxlength="220" placeholder="Description / detail"></div>
      <div class="setting-row">
        <button id="btn-ws-propose" class="btn btn-small btn-primary">Propose it</button>
        <button id="btn-ws-suggest" class="btn btn-small btn-ghost">Ask the model for a suggestion</button>
      </div>
      <div class="fact-line" id="ws-suggest-out"></div>
    </div>`;
  const proposals = (v.proposals || []).map((p) => `
    <div class="ledger-card">
      <div class="lc-kind">${esc(p.status)} · by ${esc(p.author_name)} · base rev ${p.base_rev}</div>
      <div class="fact-line">${esc(p.note || "")}</div>
      ${p.conflicts && p.conflicts.length ? `<div class="fact-line" style="color:#e0a">⚠ conflicts: ${esc(p.conflicts.join(", "))}</div>` : ""}
      ${meCreator && p.status === "proposed" ? `
        <button class="btn btn-small btn-primary" data-apply="${esc(p.id)}" ${p.conflicts && p.conflicts.length ? "" : ""}>Apply</button>
        ${p.conflicts && p.conflicts.length ? `<button class="btn btn-small" data-apply-force="${esc(p.id)}">Apply anyway (resolve conflict)</button>` : ""}
        <button class="btn btn-small btn-ghost" data-reject="${esc(p.id)}">Reject</button>` : ""}
    </div>`).join("") || "<div class='fact-line'>No proposals yet.</div>";
  const secrets = (pack.gm_secrets || []).length;
  $("forge-body").innerHTML = `
    <div class="sect"><h4>${esc(pack.name || "untitled world")} <span class="chip">${esc(v.status)}</span>
      ${meCreator ? `<span class="chip">you are the creator</span>` : `<span class="chip">contributor</span>`}</h4>
      <div class="fact-line">${esc(pack.summary || "")}</div>
      <div class="fact-line">head revision ${head} · ${secrets} hidden secret${secrets === 1 ? "" : "s"} ${meCreator ? "(all visible to you)" : "(yours only — others stay hidden)"}</div>
      <div class="setting-row">
        ${meCreator && v.status === "draft" ? `<button id="btn-ws-playtest" class="btn btn-small">Playtest in an isolated portal</button>
        <button id="btn-ws-playtest-report" class="btn btn-small btn-ghost">Playtest report</button>` : ""}
        ${meCreator && v.status === "draft" ? `<button id="btn-ws-approve" class="btn btn-small btn-primary">Validate &amp; install into the Library</button>` : ""}
        ${v.status === "approved" ? `<span class="chip">installed — it is a playable portal now</span>` : ""}
        <button id="btn-ws-refresh" class="btn btn-small btn-ghost">Refresh</button>
      </div>
    </div>
    ${contribForm}
    <div class="sect"><h4>Proposals</h4>${proposals}</div>
    <div class="sect"><h4>Places</h4><div class="fact-line">${esc((pack.locations || []).map((l) => l.name).join(" · ") || "none yet")}</div></div>
    <div class="sect"><h4>Cast</h4><div class="fact-line">${esc((pack.npcs || []).map((n) => n.name).join(" · ") || "none yet")}</div></div>
    <div class="sect"><h4>Quests</h4><div class="fact-line">${esc((pack.intro_quests || []).map((q) => q.title).join(" · ") || "none yet")}</div></div>`;
  $("btn-ws-refresh").addEventListener("click", () => openWorkshopDraft(v.draft_id));
  $("btn-ws-playtest")?.addEventListener("click", async () => {
    try {
      const r = await apiSend(`/api/forge/collab/${v.draft_id}/playtest`, "POST", {});
      window.__toast?.(`Playtest portal open — a test campaign was created (${r.campaign_id}).`, "good");
      window.__campaignId = r.campaign_id;
      window.location.hash = "#playtest";
      window.__toast?.("The portal is a real campaign from your draft; nothing approved or saved is touched.", "");
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });
  $("btn-ws-playtest-report")?.addEventListener("click", async () => {
    try {
      const r = await apiGet(`/api/forge/collab/${v.draft_id}/playtest/report`);
      const items = [
        ...(r.validation_problems || []).map((x) => `validation: ${x}`),
        ...(r.flow_findings || []).map((x) => `flow: ${x}`),
        ...(r.items_missing || []).map((x) => `items: ${x}`),
        ...(r.continuity_findings || []).map((x) => `continuity: ${x.detail || x}`),
      ];
      window.__toast?.(items.length ? items.slice(0, 3).join(" | ") : "Report clean — no findings.", items.length ? "" : "good");
      if (items.length) console.log("playtest report:", items);
    } catch (e) { window.__toast?.(e.message, "bad"); }
  });
  $("btn-ws-approve")?.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/forge/collab/${v.draft_id}/approve`, "POST", {});
      toast(`Installed: ${res.pack_id || res.draft_id}`, "good");
      openWorkshopDraft(v.draft_id);
    } catch (e) { toast(e.message, "bad"); }
  });
  // contribute form
  let kind = "npc";
  document.querySelectorAll("#ws-kind [data-k]").forEach((c) => c.addEventListener("click", () => {
    document.querySelectorAll("#ws-kind [data-k]").forEach((x) => x.classList.remove("selected"));
    c.classList.add("selected");
    kind = c.dataset.k;
  }));
  const opFor = (k, name, desc) => {
    if (k === "npc") return [{ op: "add", path: "npcs", value: { id: "npc_" + Date.now().toString(36), name, role: desc.slice(0, 40), desc, location: "hub", greeting: "" } }];
    if (k === "location") return [{ op: "add", path: "locations", value: { id: "loc_" + Date.now().toString(36), name, short: desc.slice(0, 80), desc, known: true, flavor: [], rest: { vigor: 2, nerve: 2 } } }];
    if (k === "quest") return [{ op: "add", path: "intro_quests", value: { id: "q_" + Date.now().toString(36), title: name } }];
    if (k === "lore") return [{ op: "add", path: "intro_facts", value: desc }];
    if (k === "secret") return [{ op: "add", path: "gm_secrets", value: desc },
                                { op: "set", path: `secret_authors.${desc.slice(0, 40)}`, value: window.__mpName || "the local player" }];
    return [];
  };
  $("btn-ws-propose").addEventListener("click", async () => {
    const name = $("ws-f-name").value.trim();
    const desc = $("ws-f-desc").value.trim();
    if (!name && kind !== "lore" && kind !== "secret") { toast("Give it a name.", "bad"); return; }
    const ops = opFor(kind, name, desc || name);
    try {
      const res = await apiSend(`/api/forge/collab/${v.draft_id}/contribute`, "POST",
        { ops, note: `${kind}: ${name || desc.slice(0, 30)}`, base_rev: head });
      toast(res.message, res.conflicts && res.conflicts.length ? "" : "good");
      openWorkshopDraft(v.draft_id);
    } catch (e) { toast(e.message, "bad"); }
  });
  $("btn-ws-suggest").addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/forge/collab/${v.draft_id}/suggest`, "POST",
        { kind, prompt: $("ws-f-desc").value || $("ws-f-name").value });
      const s = res.suggestion || {};
      $("ws-suggest-out").textContent =
        `${res.source}: ${s.name || ""} — ${JSON.stringify(s.fields || {})} (${res.note})`;
      if (s.name && !$("ws-f-name").value) $("ws-f-name").value = s.name;
      if (s.fields && s.fields.desc && !$("ws-f-desc").value) $("ws-f-desc").value = s.fields.desc;
    } catch (e) { toast(e.message, "bad"); }
  });
  document.querySelectorAll("[data-apply]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/forge/collab/${v.draft_id}/proposals/${b.dataset.apply}/apply`, "POST", {});
      toast(`Applied as revision ${res.revision}.`, "good");
      openWorkshopDraft(v.draft_id);
    } catch (e) {
      toast(e.message, "bad");
    }
  }));
  document.querySelectorAll("[data-apply-force]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await apiSend(`/api/forge/collab/${v.draft_id}/proposals/${b.dataset.applyForce}/apply`,
        "POST", { force: true });
      toast(`Conflict resolved by your decision — applied as revision ${res.revision}.`, "good");
      openWorkshopDraft(v.draft_id);
    } catch (e) { toast(e.message, "bad"); }
  }));
  document.querySelectorAll("[data-reject]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await apiSend(`/api/forge/collab/${v.draft_id}/proposals/${b.dataset.reject}/reject`, "POST", {});
      toast("Proposal rejected — the author keeps their own notes.", "");
      openWorkshopDraft(v.draft_id);
    } catch (e) { toast(e.message, "bad"); }
  }));
}
