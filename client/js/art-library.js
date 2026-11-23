// Saturday Multiverse — Fantasy Art Library (presentation only).
// Browses the 100-image fantasy pack. Does not alter campaign state or saves.

const MANIFEST_URL = "assets/fantasy/asset-manifest.json";
const SCENE_MAP_URL = "assets/fantasy/scene-mapping.json";

let _manifest = null;
let _sceneMap = null;
let _ready = false;

async function ensureLoaded() {
  if (_ready) return;
  const [mRes, sRes] = await Promise.all([
    fetch(MANIFEST_URL, { cache: "no-store" }),
    fetch(SCENE_MAP_URL, { cache: "no-store" }).catch(() => null),
  ]);
  if (mRes.ok) _manifest = await mRes.json();
  if (sRes && sRes.ok) _sceneMap = await sRes.json();
  _ready = true;
}

function assetUrl(file) {
  return `assets/fantasy/${file.replace(/^\/+/, "")}`;
}

function categories() {
  if (!_manifest) return [];
  const set = new Set((_manifest.assets || []).map((a) => a.category));
  return ["All", ...[...set].sort()];
}

function filterAssets({ category = "All", query = "" } = {}) {
  if (!_manifest) return [];
  const q = query.trim().toLowerCase();
  return (_manifest.assets || []).filter((a) => {
    if (category && category !== "All" && a.category !== category) return false;
    if (!q) return true;
    const hay = `${a.id} ${a.title} ${a.location || ""} ${a.intended_use || ""} ${a.weather || ""}`.toLowerCase();
    return hay.includes(q);
  });
}

function stillForLocation(locationId) {
  if (!_sceneMap || !locationId) return null;
  const entry = _sceneMap.locations?.[locationId];
  if (!entry?.still_id) return null;
  const asset = (_manifest?.assets || []).find((a) => a.id === entry.still_id);
  if (!asset) return null;
  return { ...asset, url: assetUrl(asset.file), note: entry.note || "" };
}

function videoHintForLocation(locationId) {
  return _sceneMap?.locations?.[locationId]?.video || null;
}

function renderArtLibraryHTML() {
  const cats = categories();
  return `
    <div class="artlib">
      <div class="artlib-toolbar">
        <input id="artlib-search" class="input" type="search" placeholder="Search id, title, location…" maxlength="80">
        <select id="artlib-cat" class="input artlib-cat">
          ${cats.map((c) => `<option value="${c}">${c}</option>`).join("")}
        </select>
        <span id="artlib-count" class="artlib-count"></span>
      </div>
      <div id="artlib-grid" class="artlib-grid"></div>
      <div id="artlib-preview" class="artlib-preview" hidden>
        <button type="button" id="artlib-preview-close" class="btn btn-small btn-ghost">Close</button>
        <img id="artlib-preview-img" alt="">
        <div id="artlib-preview-meta" class="artlib-preview-meta"></div>
      </div>
      <p class="artlib-footnote">Fantasy Asset Pack — browse only. Living Shore locations keep their established cinematics; Copper Kettle does not replace Salt &amp; Lantern.</p>
    </div>`;
}

function paintGrid(root) {
  const grid = root.querySelector("#artlib-grid");
  const count = root.querySelector("#artlib-count");
  const cat = root.querySelector("#artlib-cat")?.value || "All";
  const query = root.querySelector("#artlib-search")?.value || "";
  const items = filterAssets({ category: cat, query });
  if (count) count.textContent = `${items.length} image${items.length === 1 ? "" : "s"}`;
  if (!grid) return;
  grid.innerHTML = items.map((a) => `
    <button type="button" class="artlib-card" data-id="${a.id}" title="${a.title}">
      <img loading="lazy" src="${assetUrl(a.file)}" alt="${a.title}">
      <span class="artlib-card-id">${a.id}</span>
      <span class="artlib-card-title">${a.title}</span>
    </button>`).join("");
  grid.querySelectorAll(".artlib-card").forEach((btn) => {
    btn.addEventListener("click", () => showPreview(root, btn.dataset.id));
  });
}

function showPreview(root, id) {
  const asset = (_manifest?.assets || []).find((a) => a.id === id);
  const box = root.querySelector("#artlib-preview");
  if (!asset || !box) return;
  const img = root.querySelector("#artlib-preview-img");
  const meta = root.querySelector("#artlib-preview-meta");
  img.src = assetUrl(asset.file);
  img.alt = asset.title;
  meta.innerHTML = `
    <strong>${asset.id} — ${asset.title}</strong>
    <div>${asset.category}</div>
    <div>${asset.location || ""}</div>
    <div class="hint">${asset.weather || ""} · ${asset.time_of_day || ""}</div>
    <p>${asset.intended_use || ""}</p>`;
  box.hidden = false;
}

function bindArtLibrary(root) {
  root.querySelector("#artlib-search")?.addEventListener("input", () => paintGrid(root));
  root.querySelector("#artlib-cat")?.addEventListener("change", () => paintGrid(root));
  root.querySelector("#artlib-preview-close")?.addEventListener("click", () => {
    const box = root.querySelector("#artlib-preview");
    if (box) box.hidden = true;
  });
  paintGrid(root);
}

export const artLibrary = {
  ensureLoaded,
  filterAssets,
  stillForLocation,
  videoHintForLocation,
  renderArtLibraryHTML,
  bindArtLibrary,
  getManifest: () => _manifest,
  getSceneMap: () => _sceneMap,
};

window.__artLibrary = artLibrary;
