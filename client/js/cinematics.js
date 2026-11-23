// Saturday Multiverse — cinematic presentation layer.
// Plays pre-rendered MP4s from assets/cinematics/. Never blocks game state,
// never talks to OpenFilm/AI, and never mutates shared multiplayer state.
// Selection is deterministic from location / weather / portal id.

const STORAGE_PREFS = "sm_cinematics_prefs_v1";
const STORAGE_SEEN = "sm_cinematics_seen_v1";

const DEFAULT_PREFS = {
  enabled: true,
  volume: 0.45,
  ambient_audio: false, // ambient loops stay muted by default (game audio.js already plays beds)
  oneshot_audio: true,
};

function loadPrefs() {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(STORAGE_PREFS) || "{}") };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

function savePrefs(p) {
  localStorage.setItem(STORAGE_PREFS, JSON.stringify(p));
}

function loadSeen() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_SEEN) || "{}");
  } catch {
    return {};
  }
}

function saveSeen(map) {
  localStorage.setItem(STORAGE_SEEN, JSON.stringify(map));
}

function prefersReducedMotion() {
  if (document.body.classList.contains("reduced-motion")) return true;
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function videoUrl(file) {
  return `assets/cinematics/videos/${encodeURIComponent(file)}`;
}

function stillUrl(file) {
  return `assets/cinematics/stills/${encodeURIComponent(file)}`;
}

function isCalm() {
  return document.body.classList.contains("calm") || localStorage.getItem("sm_calm") === "1";
}

class CinematicPlayer {
  constructor() {
    this.prefs = loadPrefs();
    this.catalog = null;
    this._ready = false;
    this._ambientFile = null;
    this._stillFile = null;
    this._oncePlaying = false;
    this._prevLocationId = null;
    this._els = {};
  }

  async init() {
    if (this._ready) return;
    this._ensureDom();
    try {
      const res = await fetch("assets/cinematics/meta/game-catalog.json", { cache: "no-store" });
      if (res.ok) this.catalog = await res.json();
    } catch {
      this.catalog = null;
    }
    this._ready = true;
    this._applyPrefsToUi();
  }

  _ensureDom() {
    const stage = document.getElementById("scene-stage");
    if (!stage || document.getElementById("cine-layer")) {
      this._cacheEls();
      return;
    }
    const layer = document.createElement("div");
    layer.id = "cine-layer";
    layer.className = "cine-layer";
    layer.hidden = true;
    layer.innerHTML = `
      <img id="cine-still" class="cine-still" alt="" hidden>
      <video id="cine-ambient" class="cine-video cine-ambient" muted loop playsinline preload="none"></video>
      <video id="cine-once" class="cine-video cine-once" playsinline preload="none"></video>
      <div id="cine-chrome" class="cine-chrome">
        <button type="button" id="cine-skip" class="btn btn-small cine-btn" hidden>Skip</button>
        <button type="button" id="cine-replay" class="btn btn-small cine-btn" hidden>Replay</button>
        <label class="cine-mute-label" title="Cinematic audio">
          <input type="checkbox" id="cine-mute-toggle"> mute cine
        </label>
      </div>
      <div id="cine-fallback-note" class="cine-fallback-note" hidden>Cinematic unavailable — shore canvas remains.</div>
    `;
    // Place behind HUD but over canvas/vignette
    const tip = document.getElementById("scene-tooltip");
    if (tip) stage.insertBefore(layer, tip);
    else stage.appendChild(layer);
    this._cacheEls();
    this._els.skip?.addEventListener("click", () => this.skipOnce());
    this._els.replay?.addEventListener("click", () => this.replayLastOnce());
    this._els.muteToggle?.addEventListener("change", (e) => {
      this.prefs.oneshot_audio = !e.target.checked;
      this.prefs.ambient_audio = !e.target.checked;
      savePrefs(this.prefs);
      this._syncAudioBuses();
    });
    this._els.once?.addEventListener("ended", () => this._endOnce());
    this._els.ambient?.addEventListener("error", () => this._ambientFailed());
    this._els.once?.addEventListener("error", () => this._endOnce(true));
  }

  _cacheEls() {
    this._els = {
      layer: document.getElementById("cine-layer"),
      still: document.getElementById("cine-still"),
      ambient: document.getElementById("cine-ambient"),
      once: document.getElementById("cine-once"),
      skip: document.getElementById("cine-skip"),
      replay: document.getElementById("cine-replay"),
      muteToggle: document.getElementById("cine-mute-toggle"),
      note: document.getElementById("cine-fallback-note"),
    };
  }

  _applyPrefsToUi() {
    if (this._els.muteToggle) {
      this._els.muteToggle.checked = !(this.prefs.oneshot_audio || this.prefs.ambient_audio);
    }
  }

  setPrefs(patch) {
    this.prefs = { ...this.prefs, ...patch };
    savePrefs(this.prefs);
    this._applyPrefsToUi();
    if (!this.prefs.enabled) this.stopAll();
    else this._syncAudioBuses();
  }

  getPrefs() {
    return { ...this.prefs };
  }

  /** Presentation layer allowed (stills and/or video). */
  enabled() {
    return !!(this.prefs.enabled && this.catalog);
  }

  /** Motion video allowed — suppressed by reduced-motion and calm mode. */
  videoEnabled() {
    return this.enabled() && !prefersReducedMotion() && !isCalm();
  }

  _fileExistsInCatalog(file) {
    if (!file || !this.catalog) return false;
    return (this.catalog.assets || []).some((a) => a.file === file);
  }

  _pickWeather(table, weatherKey) {
    if (!table) return null;
    const by = table.by_weather || {};
    if (weatherKey && by[weatherKey]) return by[weatherKey];
    return table.default || null;
  }

  selectAmbient(view) {
    if (!this.videoEnabled() || !view) return null;
    const locId = view.location?.id;
    const weather = view.weather?.key || "mist";
    const locs = this.catalog.selection?.locations || {};
    const exterior = ["tidegate", "camp"].includes(locId) || !locId;
    // interiors / adventure destinations with specific mapping
    if (locId && locs[locId]?.ambient) {
      let file = this._pickWeather(locs[locId].ambient, weather);
      // tavern supernatural: Beam-adjacent omen / adventure scene brief cues only when scene beat present
      if (locId === "tavern" && view.scene?.beat && locs.tavern.ambient.supernatural) {
        file = locs.tavern.ambient.supernatural;
      }
      return this._fileExistsInCatalog(file) ? file : null;
    }
    // outdoor shore canvas locations (tidegate handled above; also default shore)
    if (!locId || exterior || locId === "tidegate") {
      const shore = this.catalog.selection?.shore_exterior?.ambient;
      // tidegate prefers Beam loop via locations.tidegate
      if (locId === "tidegate") {
        const file = this._pickWeather(locs.tidegate?.ambient, weather);
        return this._fileExistsInCatalog(file) ? file : null;
      }
      const file = this._pickWeather(shore, weather);
      return this._fileExistsInCatalog(file) ? file : null;
    }
    return null;
  }

  /** Still image path for location — used when video unavailable / reduced-motion / calm. */
  selectStill(view) {
    if (!this.enabled() || !view) return null;
    const locId = view.location?.id;
    const locs = this.catalog.selection?.locations || {};
    const stills = this.catalog.stills || {};
    if (locId && locs[locId]?.still) return locs[locId].still;
    if (locId === "wreck" && stills.wreck) return stills.wreck;
    if (locId === "tavern" && stills.tavern) return stills.tavern;
    if (locId === "camp" && stills.campfire) return stills.campfire;
    if (locId === "saltgrave_gate" && stills.saltgrave) return stills.saltgrave;
    if ((locId === "tidegate" || locId === "lighthouse" || !locId) && stills.shore) return stills.shore;
    return null;
  }

  selectEnterOnce(view, prevLocationId) {
    if (!this.videoEnabled() || !view) return null;
    const locId = view.location?.id;
    if (!locId || locId === prevLocationId) return null;
    const entry = this.catalog.selection?.locations?.[locId]?.enter_once;
    if (!entry || !this._fileExistsInCatalog(entry)) return null;
    const cid = view.id || "solo";
    const key = `${cid}::enter::${locId}::${entry}`;
    const seen = loadSeen();
    if (seen[key]) return null;
    seen[key] = Date.now();
    saveSeen(seen);
    return entry;
  }

  selectPortal(portalId) {
    if (!this.videoEnabled()) return null;
    const portals = this.catalog.selection?.portals || {};
    const file = (portalId && portals[portalId]) || portals.default;
    return this._fileExistsInCatalog(file) ? file : null;
  }

  selectAdventureIntro(view) {
    if (!this.videoEnabled() || !view) return null;
    const advId = view.scene?.adventure_id || view.location?.adventure;
    if (!advId) return null;
    const intro = this.catalog.selection?.adventures?.[advId]?.intro;
    if (!intro || !this._fileExistsInCatalog(intro)) return null;
    // Salt-Grave intro is tied to the Drowned Bay location
    if (advId === "salt_grave_signal" && view.location?.id !== "saltgrave_gate") return null;
    const cid = view.id || "solo";
    const key = `${cid}::adv::${advId}::${intro}`;
    const seen = loadSeen();
    if (seen[key]) return null;
    seen[key] = Date.now();
    saveSeen(seen);
    return intro;
  }

  async setAmbient(file) {
    await this.init();
    const amb = this._els.ambient;
    const layer = this._els.layer;
    if (!this.videoEnabled() || !file || !amb) {
      this.clearAmbientVideo();
      return;
    }
    if (this._ambientFile === file && !amb.error) {
      layer.hidden = false;
      document.body.classList.add("cine-active");
      this.clearStill();
      return;
    }
    this._ambientFile = file;
    amb.loop = true;
    amb.src = videoUrl(file);
    amb.muted = !this.prefs.ambient_audio;
    amb.volume = Math.max(0, Math.min(1, this.prefs.volume));
    layer.hidden = false;
    document.body.classList.add("cine-active");
    if (this._els.note) this._els.note.hidden = true;
    this.clearStill();
    try {
      await amb.play();
    } catch {
      // Autoplay policies — keep muted retry
      amb.muted = true;
      try { await amb.play(); } catch { this._ambientFailed(); }
    }
  }

  setStill(file) {
    const img = this._els.still;
    const layer = this._els.layer;
    if (!this.enabled() || !file || !img) {
      this.clearStill();
      return;
    }
    if (this._stillFile === file) {
      layer.hidden = false;
      document.body.classList.add("cine-active", "cine-still-active");
      return;
    }
    this._stillFile = file;
    img.src = stillUrl(file);
    img.hidden = false;
    layer.hidden = false;
    document.body.classList.add("cine-active", "cine-still-active");
    if (this._els.note) this._els.note.hidden = true;
  }

  clearStill() {
    const img = this._els.still;
    if (img) {
      img.hidden = true;
      img.removeAttribute("src");
    }
    this._stillFile = null;
    document.body.classList.remove("cine-still-active");
  }

  clearAmbientVideo() {
    const amb = this._els.ambient;
    if (amb) {
      amb.pause();
      amb.removeAttribute("src");
      amb.load();
    }
    this._ambientFile = null;
  }

  clearAmbient() {
    this.clearAmbientVideo();
    this.clearStill();
    if (!this._oncePlaying) {
      if (this._els.layer) this._els.layer.hidden = true;
      document.body.classList.remove("cine-active");
    }
  }

  _ambientFailed() {
    this.clearAmbientVideo();
    // Prefer still over blank canvas when ambient video fails
    const still = this._pendingStill;
    if (still) this.setStill(still);
    else if (this._els.note) this._els.note.hidden = false;
    if (!this._stillFile && !this._oncePlaying) {
      if (this._els.layer) this._els.layer.hidden = true;
      document.body.classList.remove("cine-active");
    }
  }

  _syncAudioBuses() {
    const amb = this._els.ambient;
    const once = this._els.once;
    if (amb) {
      amb.muted = !this.prefs.ambient_audio;
      amb.volume = this.prefs.volume;
    }
    if (once) {
      once.muted = !this.prefs.oneshot_audio;
      once.volume = this.prefs.volume;
    }
  }

  async playOnce(file, { portal = false } = {}) {
    await this.init();
    if (!this.videoEnabled() || !file) return;
    const once = this._els.once;
    const layer = this._els.layer;
    if (!once || !layer) return;
    this._lastOnce = file;
    this._oncePlaying = true;
    layer.hidden = false;
    document.body.classList.add("cine-active", "cine-oneshot");
    if (this._els.skip) this._els.skip.hidden = false;
    if (this._els.replay) this._els.replay.hidden = true;
    once.src = videoUrl(file);
    once.loop = false;
    once.muted = !this.prefs.oneshot_audio;
    once.volume = this.prefs.volume;
    try {
      await once.play();
    } catch {
      once.muted = true;
      try { await once.play(); } catch { this._endOnce(true); }
    }
  }

  skipOnce() {
    this._endOnce();
  }

  async replayLastOnce() {
    if (this._lastOnce) await this.playOnce(this._lastOnce);
  }

  _endOnce(failed = false) {
    const once = this._els.once;
    if (once) {
      once.pause();
      once.removeAttribute("src");
      once.load();
    }
    this._oncePlaying = false;
    document.body.classList.remove("cine-oneshot");
    if (this._els.skip) this._els.skip.hidden = true;
    if (this._els.replay) this._els.replay.hidden = !this._lastOnce;
    if (failed && this._els.note) this._els.note.hidden = false;
    if (!this._ambientFile) {
      if (this._els.layer) this._els.layer.hidden = true;
      document.body.classList.remove("cine-active");
    }
  }

  stopAll() {
    this._endOnce();
    this.clearAmbient();
  }

  /**
   * Update presentation for the current view. Never awaits network game APIs.
   * @param {object} view campaign view
   * @param {{ prevLocationId?: string, portalId?: string|null }} opts
   */
  async updateForView(view, opts = {}) {
    await this.init();
    if (!this.enabled()) {
      this.stopAll();
      return;
    }
    const prev = opts.prevLocationId ?? this._prevLocationId;
    const portalId = opts.portalId || null;
    const still = this.selectStill(view);
    this._pendingStill = still;

    // Priority: matching video → matching still → canvas/SVG fallback
    if (this.videoEnabled()) {
      // Portal oneshot — fire-and-forget; does not block travel
      if (portalId) {
        const pfile = this.selectPortal(portalId);
        if (pfile) this.playOnce(pfile, { portal: true });
      } else {
        const enter = this.selectEnterOnce(view, prev);
        const adv = this.selectAdventureIntro(view);
        const once = enter || adv;
        if (once) this.playOnce(once);
      }

      const ambient = this.selectAmbient(view);
      if (ambient) {
        await this.setAmbient(ambient);
      } else if (still) {
        this.clearAmbientVideo();
        this.setStill(still);
      } else {
        this.clearAmbient();
      }
    } else if (still) {
      // Reduced-motion / calm: static plate only
      this.clearAmbientVideo();
      this._endOnce();
      this.setStill(still);
    } else {
      this.stopAll();
    }

    this._prevLocationId = view?.location?.id || null;
  }

  /** Map a travel target location back to a portal id when known. */
  portalIdForTarget(view, targetLocationId) {
    const portals = view?.portals || [];
    const hit = portals.find((p) => p.target_location === targetLocationId && !p.sealed);
    return hit?.id || null;
  }
}

export const cinematics = new CinematicPlayer();
window.__cinematics = cinematics;
