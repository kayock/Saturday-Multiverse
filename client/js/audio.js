// Saturday Multiverse — procedural WebAudio engine.
// Every sound is synthesized live: ocean surf, wind, campfire, a slow
// generative music drone, and UI/dice/portal effects. No audio files ship
// with the game, so there is nothing to license and world packs may layer
// their own audio later. Three independent buses (music / ambience / sfx)
// persist to localStorage.

const LS_KEY = "sm_audio_v1";

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; }
}

export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.prefs = Object.assign({ music: 0.5, amb: 0.7, sfx: 0.8, muted: false }, loadPrefs());
    this.buses = {};
    this.layers = {};
    this.scene = { ambience: "surf", weather: "mist", tide: "high" };
    this.musicTimer = null;
    this.fireTimer = null;
    this.chordIndex = 0;
  }

  // ---- lifecycle ----------------------------------------------------------
  ensure() {
    if (this.ctx) { if (this.ctx.state === "suspended") this.ctx.resume(); return this.ctx; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    this.ctx = new AC();
    const master = this.ctx.createGain();
    master.gain.value = this.prefs.muted ? 0 : 1;
    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.ratio.value = 4;
    master.connect(comp); comp.connect(this.ctx.destination);
    this.master = master;
    for (const [name, vol] of [["music", this.prefs.music], ["amb", this.prefs.amb], ["sfx", this.prefs.sfx]]) {
      const g = this.ctx.createGain();
      g.gain.value = this.prefs.muted ? 0 : vol;
      g.connect(master);
      this.buses[name] = g;
    }
    this._noise = this._makeNoise(2.0, "brown");
    this._startAmbience();
    this._startMusic();
    return this.ctx;
  }

  savePrefs() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(this.prefs)); } catch { /* private mode */ }
  }

  setBus(name, value) {
    this.prefs[name] = value;
    if (this.buses[name] && this.ctx) {
      this.buses[name].gain.setTargetAtTime(this.prefs.muted ? 0 : value, this.ctx.currentTime, 0.1);
    }
    this.savePrefs();
  }

  setMuted(m) {
    this.prefs.muted = m;
    if (this.ctx) this.master.gain.setTargetAtTime(m ? 0 : 1, this.ctx.currentTime, 0.1);
    this.savePrefs();
  }

  // ---- helpers ------------------------------------------------------------
  _makeNoise(seconds, color) {
    const ctx = this.ctx;
    const buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * seconds), ctx.sampleRate);
    const d = buf.getChannelData(0);
    let last = 0;
    for (let i = 0; i < d.length; i++) {
      const w = Math.random() * 2 - 1;
      if (color === "brown") { last = (last + 0.02 * w) / 1.02; d[i] = last * 3.2; }
      else d[i] = w;
    }
    return buf;
  }

  _noiseSource(loop = false) {
    const src = this.ctx.createBufferSource();
    src.buffer = this._noise;
    src.loop = loop;
    return src;
  }

  // ---- ambience -----------------------------------------------------------
  _startAmbience() {
    const ctx = this.ctx;
    // surf: brown noise -> lowpass, gain breathing with two LFOs
    const surf = this._noiseSource(true);
    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 420; lp.Q.value = 0.4;
    const g = ctx.createGain(); g.gain.value = 0.18;
    surf.connect(lp); lp.connect(g); g.connect(this.buses.amb);
    const lfo = ctx.createOscillator(); lfo.frequency.value = 0.07;
    const lfoG = ctx.createGain(); lfoG.gain.value = 0.10;
    lfo.connect(lfoG); lfoG.connect(g.gain);
    const lfo2 = ctx.createOscillator(); lfo2.frequency.value = 0.013;
    const lfo2G = ctx.createGain(); lfo2G.gain.value = 0.05;
    lfo2.connect(lfo2G); lfo2G.connect(g.gain);
    surf.start(); lfo.start(); lfo2.start();
    this.layers.surf = { g, lp };

    // wind: same noise idea, bandpass higher, slow drift
    const wind = this._noiseSource(true);
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass"; bp.frequency.value = 700; bp.Q.value = 0.6;
    const wg = ctx.createGain(); wg.gain.value = 0.03;
    wind.connect(bp); bp.connect(wg); wg.connect(this.buses.amb);
    const wlfo = ctx.createOscillator(); wlfo.frequency.value = 0.05;
    const wlfoG = ctx.createGain(); wlfoG.gain.value = 0.022;
    wlfo.connect(wlfoG); wlfoG.connect(wg.gain);
    const wDrift = ctx.createOscillator(); wDrift.frequency.value = 0.021;
    const wDriftG = ctx.createGain(); wDriftG.gain.value = 320;
    wDrift.connect(wDriftG); wDriftG.connect(bp.frequency);
    wind.start(); wlfo.start(); wDrift.start();
    this.layers.wind = { g: wg, bp };

    this._applyScene();
    this._scheduleFire();
  }

  _applyScene() {
    if (!this.ctx) return;
    const { ambience, weather } = this.scene;
    const t = this.ctx.currentTime;
    const surf = this.layers.surf, wind = this.layers.wind;
    const inShore = ["tidegate", "camp", "seacave", "wreck"].includes(ambience) || ambience === "shore";
    const w = ["storm", "drizzle", "fogbank"].includes(weather) ? weather : "clear";

    surf.g.gain.setTargetAtTime(inShore ? (w === "storm" ? 0.30 : 0.16) : 0.03, t, 1.5);
    surf.lp.frequency.setTargetAtTime(w === "storm" ? 620 : 420, t, 1.5);
    wind.g.gain.setTargetAtTime(w === "storm" ? 0.10 : w === "drizzle" ? 0.05 : 0.03, t, 1.5);
    wind.bp.frequency.setTargetAtTime(w === "storm" ? 480 : 700, t, 1.0);
  }

  setScene(ambience, weather, tide) {
    this.scene = { ambience, weather, tide };
    this._applyScene();
  }

  _scheduleFire() {
    if (this.fireTimer) clearTimeout(this.fireTimer);
    const tick = () => {
      this.fireTimer = setTimeout(tick, 120 + Math.random() * 900);
      if (!this.ctx) return;
      const { ambience } = this.scene;
      const near = (ambience === "camp" || ambience === "tavern");
      if (!near || Math.random() > 0.75) return;
      const t = this.ctx.currentTime;
      const src = this._noiseSource(false);
      const bp = this.ctx.createBiquadFilter();
      bp.type = "bandpass"; bp.frequency.value = 1400 + Math.random() * 1800; bp.Q.value = 2.2;
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.05 + Math.random() * 0.08, t + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05 + Math.random() * 0.06);
      src.connect(bp); bp.connect(g); g.connect(this.buses.amb);
      src.start(t, Math.random() * 1.5, 0.14);
    };
    tick();
  }

  // ---- generative music ---------------------------------------------------
  _startMusic() {
    const chords = [
      [110.0, 164.81, 220.0],   // A2 E3 A3 (Am)
      [87.31, 130.81, 174.61],  // F2 C3 F3 (F)
      [98.0, 146.83, 196.0],    // G2 D3 G3 (G)
      [130.81, 164.81, 246.94], // C3 E3 B3 (Cmaj7-ish)
    ];
    const playChord = () => {
      if (!this.ctx) return;
      const chord = chords[this.chordIndex % chords.length];
      this.chordIndex++;
      const t = this.ctx.currentTime;
      for (const freq of chord) {
        for (const detune of [-3, 3]) {
          const o = this.ctx.createOscillator();
          o.type = "triangle";
          o.frequency.value = freq;
          o.detune.value = detune;
          const g = this.ctx.createGain();
          g.gain.setValueAtTime(0.0001, t);
          g.gain.linearRampToValueAtTime(0.028, t + 3.2);
          g.gain.setValueAtTime(0.028, t + 9);
          g.gain.linearRampToValueAtTime(0.0001, t + 15);
          o.connect(g); g.connect(this.buses.music);
          o.start(t); o.stop(t + 16);
        }
      }
    };
    playChord();
    this.musicTimer = setInterval(playChord, 14000);
  }

  // ---- sound effects ------------------------------------------------------
  _blip(freq, dur, type = "sine", vol = 0.12, slideTo = null) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const o = this.ctx.createOscillator();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(this.buses.sfx);
    o.start(t); o.stop(t + dur + 0.05);
  }

  ui() { this._blip(520, 0.07, "sine", 0.05); }
  dice() {
    this._blip(880, 0.04, "square", 0.045);
    setTimeout(() => this._blip(660, 0.05, "square", 0.04), 90);
    setTimeout(() => this._blip(990, 0.04, "square", 0.03), 190);
  }
  chime() {
    this._blip(880, 0.5, "sine", 0.09);
    setTimeout(() => this._blip(1320, 0.7, "sine", 0.07), 120);
  }
  harm() {
    this._blip(90, 0.3, "sine", 0.16, 55);
    if (this.ctx) {
      const t = this.ctx.currentTime;
      const src = this._noiseSource(false);
      const lp = this.ctx.createBiquadFilter();
      lp.type = "lowpass"; lp.frequency.value = 300;
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0.14, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
      src.connect(lp); lp.connect(g); g.connect(this.buses.sfx);
      src.start(t, 0, 0.3);
    }
  }
  portal() {
    if (!this.ctx) return;
    this._blip(180, 1.4, "sine", 0.12, 920);
    this._blip(240, 1.6, "triangle", 0.07, 1200);
    const t = this.ctx.currentTime;
    const src = this._noiseSource(false);
    const bp = this.ctx.createBiquadFilter();
    bp.type = "bandpass"; bp.Q.value = 6;
    bp.frequency.setValueAtTime(400, t);
    bp.frequency.exponentialRampToValueAtTime(3200, t + 1.4);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.10, t + 0.7);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.7);
    src.connect(bp); bp.connect(g); g.connect(this.buses.sfx);
    src.start(t, 0, 1.8);
    setTimeout(() => this.chime(), 1200);
  }
  steps() {
    if (!this.ctx) return;
    const tap = (delay) => {
      const t = this.ctx.currentTime + delay;
      const src = this._noiseSource(false);
      const lp = this.ctx.createBiquadFilter();
      lp.type = "lowpass"; lp.frequency.value = 380;
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.055, t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.09);
      src.connect(lp); lp.connect(g); g.connect(this.buses.sfx);
      src.start(t, Math.random() * 1.0, 0.1);
    };
    tap(0); tap(0.22); tap(0.46);
  }
}

export const audio = new AudioEngine();
