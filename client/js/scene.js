// Saturday Multiverse — the Living Shore, rendered live on canvas.
// An explorable place, not a menu: sky, Beam, moon, sea, surf, doors,
// campfire, tavern, lighthouse, weather, tides. Clickable hotspots drive
// travel and discovery through the server API.

const T = {
  skyTop: "#0a0817", skyMid: "#1a1030", skyLow: "#241742",
  seaDark: "#120e24", seaMid: "#1c1440", seaGlow: "#2a1c5c",
  sand: "#171223", sandWet: "#221736",
  purple: "#7c5cff", glow: "#9b8cff", teal: "#43e8d8",
  gold: "#e8b46b", ember: "#ff9d5c", moon: "#e9e4f2",
};

// relative layout (x, y in 0..1 of canvas).
// Interactives sit in the upper 2/3: the narration dock owns the bottom.
const LAYOUT = {
  horizon: 0.50,
  shorelineHigh: 0.66,
  shorelineLow: 0.74,
  doors: [{ x: 0.41 }, { x: 0.505 }, { x: 0.60 }],
  doorBase: 0.50,
  camp: { x: 0.155, y: 0.72 },
  tavern: { x: 0.24, y: 0.70 },
  lighthouse: { x: 0.875, y: 0.58 },
  seacave: { x: 0.79, y: 0.62 },
  wreck: { x: 0.745, y: 0.72 },
  signpost: { x: 0.27, y: 0.70 },
  beam: { x: 0.5, y: 0.14 },
};

export class ShoreScene {
  constructor(canvas, handlers) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.handlers = handlers || {};
    this.view = null;
    this.t = 0;
    this.raf = null;
    this.pointer = { x: 0.5, y: 0.5, inside: false };
    this.hover = null;
    this.stars = [];
    this.motes = [];
    this.rain = [];
    for (let i = 0; i < 140; i++) {
      this.stars.push({ x: Math.random(), y: Math.random() * 0.5, r: Math.random() * 1.4 + 0.3, p: Math.random() * 6.28 });
    }
    for (let i = 0; i < 40; i++) {
      this.motes.push({ x: Math.random(), y: 0.5 + Math.random() * 0.45, p: Math.random() * 6.28, s: 0.4 + Math.random() * 0.8 });
    }
    canvas.addEventListener("mousemove", (e) => this._onMove(e));
    canvas.addEventListener("mouseleave", () => { this.pointer.inside = false; this._setHover(null); });
    canvas.addEventListener("click", (e) => this._onClick(e));
    window.addEventListener("resize", () => this._resize());
    this._resize();
  }

  _resize() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const r = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.max(1, r.width * dpr);
    this.canvas.height = Math.max(1, r.height * dpr);
    this.dpr = dpr;
    this.w = r.width; this.h = r.height;
  }

  setView(view) {
    this.view = view;
    const inHub = view && ["tidegate", "camp", "tavern", "lighthouse", "seacave", "wreck"].includes(view.location?.id);
    if (inHub) { this.start(); } else { this.stop(); }
    this._resize();
  }

  setCalm(calm) {
    this.calm = !!calm;
    if (this.canvas) this.canvas.dataset.calm = this.calm ? "1" : "0";
  }

  start() { if (!this.raf) { const loop = (ts) => { this.t = ts / 1000; this.draw(); this.raf = requestAnimationFrame(loop); }; this.raf = requestAnimationFrame(loop); } }
  stop() { if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; } }

  // ---- hit testing --------------------------------------------------------
  _hotspots() {
    const v = this.view;
    if (!v) return [];
    const disc = v.discovered || {};
    const tide = v.tide;
    const out = [];
    v.portals?.forEach((p, i) => {
      out.push({
        id: p.id, kind: p.sealed ? "sealed" : p.unstable ? "seed" : "travel", label: p.label,
        hint: p.sealed ? p.seal_note : (p.hint || "step through"),
        target: p.target_location, x: LAYOUT.doors[i] ? LAYOUT.doors[i].x : 0.665,
        y: LAYOUT.doorBase - 0.045, w: 0.058, h: 0.13,
      });
    });
    // something washed ashore?
    if (this.view?.washashore) {
      out.push({ id: "washashore", kind: "wash", label: this.view.washashore.label,
        hint: "the tide brought it — pick it up", x: 0.62, y: 0.66, w: 0.045, h: 0.045 });
    }
    out.push({ id: "camp", kind: "travel", label: "Driftwood Camp", hint: "fire, rest, Old Cardo", target: "camp", x: LAYOUT.camp.x, y: LAYOUT.camp.y - 0.05, w: 0.11, h: 0.12 });
    out.push({ id: "tavern", kind: "travel", label: "The Salt & Lantern", hint: "travelers' refuge — Maren pours", target: "tavern", x: LAYOUT.tavern.x, y: LAYOUT.tavern.y - 0.05, w: 0.10, h: 0.11 });
    if (disc.lighthouse) {
      out.push({ id: "lighthouse", kind: "travel", label: "The Skyless Light", hint: "the abandoned lighthouse on the point", target: "lighthouse", x: LAYOUT.lighthouse.x, y: LAYOUT.lighthouse.y - 0.13, w: 0.07, h: 0.22 });
    }
    if (disc.seacave && tide === "low") {
      out.push({ id: "seacave", kind: "travel", label: "The Cave West of the Point", hint: "low tide only — bring light, leave a nail", target: "seacave", x: LAYOUT.seacave.x, y: LAYOUT.seacave.y - 0.03, w: 0.075, h: 0.08 });
    }
    if (disc.wreck && tide === "low") {
      out.push({ id: "wreck", kind: "travel", label: "The Marrow Bell", hint: "salvage sloop aground at low tide", target: "wreck", x: LAYOUT.wreck.x, y: LAYOUT.wreck.y - 0.025, w: 0.11, h: 0.07 });
    }
    out.push({ id: "signpost", kind: "hotspot", label: "the leaning signpost", hint: "read it", hotspotId: "signpost", x: LAYOUT.signpost.x, y: LAYOUT.signpost.y - 0.03, w: 0.03, h: 0.08 });
    out.push({ id: "beam", kind: "hotspot", label: "the Beam overhead", hint: "look up", hotspotId: "beam", x: LAYOUT.beam.x, y: LAYOUT.beam.y, w: 0.5, h: 0.07 });
    return out;
  }

  _locate(e) {
    const r = this.canvas.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  }

  _hitAt(pos) {
    for (const h of this._hotspots()) {
      const hw = h.kind === "hotspot" && h.id === "beam" ? 0.25 : h.w;
      if (Math.abs(pos.x - h.x) < hw && pos.y > h.y - h.h / 2 && pos.y < h.y + h.h / 2) return h;
    }
    return null;
  }

  _onMove(e) {
    this.pointer = { ...this._locate(e), inside: true };
    this._setHover(this._hitAt(this.pointer));
  }

  _onClick(e) {
    const hit = this._hitAt(this._locate(e));
    if (!hit) return;
    if (hit.kind === "travel") this.handlers.onTravel?.(hit.target);
    else if (hit.kind === "seed") this.handlers.onSeed?.();
    else if (hit.kind === "wash") this.handlers.onWash?.();
    else if (hit.kind === "sealed") this.handlers.onSealed?.(hit);
    else if (hit.kind === "hotspot") this.handlers.onHotspot?.(hit.hotspotId);
  }

  _setHover(h) {
    if (h !== this.hover) {
      this.hover = h;
      this.canvas.style.cursor = h ? "pointer" : "default";
      this.handlers.onHover?.(h);
    }
  }

  // ---- painting -----------------------------------------------------------
  draw() {
    const c = this.ctx, W = this.canvas.width, H = this.canvas.height;
    const v = this.view;
    const weather = v?.weather?.key || "mist";
    const tide = v?.tide || "high";
    const t = this.t * (this.calm ? 0.45 : 1);
    const px = this.pointer.inside ? (this.pointer.x - 0.5) : 0;
    const py = this.pointer.inside ? (this.pointer.y - 0.5) : 0;

    // sky
    const sky = c.createLinearGradient(0, 0, 0, H * LAYOUT.horizon);
    sky.addColorStop(0, T.skyTop);
    sky.addColorStop(0.6, T.skyMid);
    sky.addColorStop(1, T.skyLow);
    c.fillStyle = sky;
    c.fillRect(0, 0, W, H * LAYOUT.horizon);

    // stars
    const starAlpha = weather === "clear" ? 0.9 : weather === "storm" ? 0.15 : 0.45;
    for (const s of this.stars) {
      const tw = 0.55 + 0.45 * Math.sin(t * 1.7 + s.p);
      c.globalAlpha = starAlpha * tw * (1 - s.y * 1.4);
      c.fillStyle = "#cfd6ff";
      c.beginPath();
      c.arc((s.x + px * 0.01) * W, s.y * H, s.r * this.dpr, 0, 6.283);
      c.fill();
    }
    c.globalAlpha = 1;

    // the Beam: a luminous band with drifting script
    const beamY = H * LAYOUT.beam.y;
    const beamGrad = c.createLinearGradient(0, beamY - H * 0.045, 0, beamY + H * 0.045);
    beamGrad.addColorStop(0, "rgba(155,140,255,0.02)");
    beamGrad.addColorStop(0.5, "rgba(155,140,255,0.20)");
    beamGrad.addColorStop(1, "rgba(67,232,216,0.03)");
    c.fillStyle = beamGrad;
    c.fillRect(0, beamY - H * 0.05, W, H * 0.10);
    for (let k = 0; k < 22; k++) {
      const gx = ((t * 0.03 + k * 0.048) % 1.1) * W - W * 0.05;
      c.globalAlpha = 0.35 + 0.3 * Math.sin(t * 2 + k);
      c.fillStyle = k % 3 === 0 ? T.teal : T.glow;
      c.font = `${Math.round(H * 0.02 + 6)}px serif`;
      c.fillText(["◈", "ᛝ", "✦", "᚛", "◉", "⟁"][k % 6], gx, beamY + Math.sin(t + k) * 4 * this.dpr);
    }
    c.globalAlpha = 1;

    // moon
    const mx = W * (0.78 + px * 0.012), my = H * 0.20;
    const mg = c.createRadialGradient(mx, my, 2, mx, my, H * 0.11);
    mg.addColorStop(0, "rgba(233,228,242,0.9)");
    mg.addColorStop(0.25, "rgba(233,228,242,0.18)");
    mg.addColorStop(1, "rgba(233,228,242,0)");
    c.fillStyle = mg;
    c.beginPath(); c.arc(mx, my, H * 0.11, 0, 6.283); c.fill();
    c.fillStyle = "#ded9ee";
    c.beginPath(); c.arc(mx, my, H * 0.032, 0, 6.283); c.fill();
    c.fillStyle = "rgba(20,16,38,0.35)";
    c.beginPath(); c.arc(mx - H * 0.012, my - H * 0.008, H * 0.008, 0, 6.283); c.fill();
    c.beginPath(); c.arc(mx + H * 0.01, my + H * 0.01, H * 0.006, 0, 6.283); c.fill();

    // sea
    const shore = tide === "low" ? LAYOUT.shorelineLow : LAYOUT.shorelineHigh;
    const seaH = H * (shore - LAYOUT.horizon);
    const sea = c.createLinearGradient(0, H * LAYOUT.horizon, 0, H * shore);
    sea.addColorStop(0, T.seaDark);
    sea.addColorStop(0.5, T.seaMid);
    sea.addColorStop(1, T.seaGlow);
    c.fillStyle = sea;
    c.fillRect(0, H * LAYOUT.horizon, W, seaH + 2);
    // moon path on water
    c.save();
    c.globalAlpha = 0.25;
    c.fillStyle = "#cfd0f0";
    for (let i = 0; i < 14; i++) {
      const wy = H * (LAYOUT.horizon + 0.015 + i * 0.012);
      const wob = Math.sin(t * 1.3 + i * 1.1) * (6 + i * 2.5) * this.dpr;
      c.fillRect(mx - (10 + i * 6) * this.dpr + wob, wy, (20 + i * 12) * this.dpr, 2 * this.dpr);
    }
    c.restore();

    // wave bands
    for (let b = 0; b < 4; b++) {
      const base = H * (LAYOUT.horizon + 0.05 + b * 0.045);
      c.beginPath();
      c.moveTo(0, base);
      for (let x = 0; x <= W; x += 14 * this.dpr) {
        const y = base + Math.sin(x / (90 * this.dpr) + t * (0.7 + b * 0.22) + b * 1.7) * (2.5 + b * 1.6) * this.dpr;
        c.lineTo(x, y);
      }
      c.lineTo(W, H * shore);
      c.lineTo(0, H * shore);
      c.closePath();
      c.fillStyle = b % 2 ? "rgba(28,20,64,0.55)" : "rgba(16,12,38,0.5)";
      c.fill();
    }

    // distant shore lights across the bay
    for (let i = 0; i < 7; i++) {
      const lx = W * (0.06 + i * 0.13), ly = H * (LAYOUT.horizon + 0.02);
      c.globalAlpha = 0.35 + 0.25 * Math.sin(t * 1.8 + i * 2.2);
      c.fillStyle = i === 3 ? T.gold : T.glow;
      c.beginPath(); c.arc(lx, ly, 1.6 * this.dpr, 0, 6.283); c.fill();
    }
    c.globalAlpha = 1;

    this._drawWetSand(c, W, H, shore, t, px);
    this._drawLighthouse(c, W, H, t, v);
    this._drawDoors(c, W, H, t, v);
    this._drawTavern(c, W, H, t);
    this._drawCampfire(c, W, H, t);
    this._drawSignpost(c, W, H);
    if (v?.washashore && !v.world) this._drawWashashore(c, W, H, t);
    if (v?.discovered?.seacave && tide === "low") this._drawSeacave(c, W, H, t);
    if (v?.discovered?.wreck && tide === "low") this._drawWreck(c, W, H, t);

    // foam at the waterline
    const foamY = H * shore;
    for (let i = 0; i < 3; i++) {
      c.beginPath();
      const fy = foamY + Math.sin(t * 1.1 + i * 2.1) * 4 * this.dpr - i * 6 * this.dpr;
      c.moveTo(0, fy);
      for (let x = 0; x <= W; x += 10 * this.dpr) {
        c.lineTo(x, fy + Math.sin(x / (40 * this.dpr) + t * 1.6 + i) * 2.4 * this.dpr);
      }
      c.strokeStyle = `rgba(233,228,242,${0.28 - i * 0.08})`;
      c.lineWidth = 1.4 * this.dpr;
      c.stroke();
    }

    this._drawBeach(c, W, H, shore, t);
    this._drawWeather(c, W, H, weather, t);
    this._drawHover(c);
  }

  _drawWetSand(c, W, H, shore, t, px) {
    const g = c.createLinearGradient(0, H * shore, 0, H * (shore + 0.10));
    g.addColorStop(0, T.sandWet);
    g.addColorStop(1, "rgba(23,18,35,0)");
    c.fillStyle = g;
    c.fillRect(0, H * shore, W, H * 0.10);
    // reflected door glow on wet sand
    const v = this.view;
    v?.portals?.forEach((p, i) => {
      if (p.sealed) return;
      const slot = LAYOUT.doors[i];
      if (!slot) return;
      const dx = slot.x * W + px * W * 0.004;
      const rg = c.createRadialGradient(dx, H * (shore + 0.03), 1, dx, H * (shore + 0.03), W * 0.03);
      rg.addColorStop(0, "rgba(124,92,255,0.35)");
      rg.addColorStop(1, "rgba(124,92,255,0)");
      c.fillStyle = rg;
      c.fillRect(dx - W * 0.03, H * shore, W * 0.06, H * 0.06);
    });
  }

  _drawBeach(c, W, H, shore, t) {
    const g = c.createLinearGradient(0, H * shore, 0, H);
    g.addColorStop(0, T.sandWet);
    g.addColorStop(0.4, T.sand);
    g.addColorStop(1, "#0d0a18");
    c.fillStyle = g;
    c.beginPath();
    c.moveTo(0, H * shore + 6 * this.dpr);
    for (let x = 0; x <= W; x += 16 * this.dpr) {
      c.lineTo(x, H * shore + 6 * this.dpr + Math.sin(x / (130 * this.dpr) + 1.2) * 5 * this.dpr);
    }
    c.lineTo(W, H); c.lineTo(0, H);
    c.closePath(); c.fill();
    // sand speckles + shell glints
    for (let i = 0; i < 60; i++) {
      const sx = ((i * 137.5) % 100) / 100 * W;
      const sy = H * (shore + 0.06 + ((i * 61.8) % 100) / 100 * (0.94 - shore));
      c.globalAlpha = 0.12 + 0.1 * Math.sin(t + i);
      c.fillStyle = i % 7 === 0 ? "#e8b46b" : "#8f86ad";
      c.fillRect(sx, sy, 2 * this.dpr, 1.2 * this.dpr);
    }
    c.globalAlpha = 1;
  }

  _drawDoors(c, W, H, t, v) {
    v?.portals?.forEach((p, i) => {
      const x = (LAYOUT.doors[i] ? LAYOUT.doors[i].x : 0.665) * W;
      const base = H * LAYOUT.doorBase;
      const dh = H * 0.125, dw = H * 0.075;
      const pulse = p.sealed ? 0 : (0.6 + 0.4 * Math.sin(t * 1.6 + i * 2.1));
      const col = i === 0 ? "124,92,255" : i === 1 ? "67,232,216"
        : p.unstable ? "255,92,200" : "90,80,110";
      // door frame
      c.save();
      c.shadowColor = `rgba(${col},${p.sealed ? 0.25 : 0.85})`;
      c.shadowBlur = (p.sealed ? 8 : p.unstable ? 34 : 26) * this.dpr;
      c.strokeStyle = `rgba(${col},${p.sealed ? 0.5 : 0.95})`;
      c.lineWidth = 2.6 * this.dpr;
      c.beginPath();
      c.moveTo(x - dw / 2, base);
      c.lineTo(x - dw / 2, base - dh * 0.62);
      c.quadraticCurveTo(x, base - dh * 1.25, x + dw / 2, base - dh * 0.62);
      c.lineTo(x + dw / 2, base);
      c.stroke();
      // portal interior
      if (p.unstable) {
        // iridescent shimmer: magenta field with teal interference bands
        const pg = c.createLinearGradient(x - dw / 2, base - dh, x + dw / 2, base);
        pg.addColorStop(0, `rgba(255,92,200,${0.4 * pulse + 0.12})`);
        pg.addColorStop(0.5, `rgba(124,92,255,${0.3 * pulse + 0.1})`);
        pg.addColorStop(1, `rgba(67,232,216,${0.22 * pulse + 0.06})`);
        c.fillStyle = pg;
        c.beginPath();
        c.moveTo(x - dw / 2 + 2 * this.dpr, base);
        c.lineTo(x - dw / 2 + 2 * this.dpr, base - dh * 0.62);
        c.quadraticCurveTo(x, base - dh * 1.18, x + dw / 2 - 2 * this.dpr, base - dh * 0.62);
        c.lineTo(x + dw / 2 - 2 * this.dpr, base);
        c.closePath(); c.fill();
        for (let m = 0; m < 6; m++) {
          const my2 = base - ((t * (0.05 + 0.014 * m) + m * 0.27) % 1) * dh;
          c.globalAlpha = 0.7 * pulse;
          c.fillStyle = m % 2 ? "#ffd0f0" : "#b0f0ff";
          c.beginPath();
          c.arc(x + Math.sin(t * 1.4 + m * 2.6) * dw * 0.26, my2, 1.4 * this.dpr, 0, 6.283);
          c.fill();
        }
        c.globalAlpha = 1;
      } else if (!p.sealed) {
        const pg = c.createLinearGradient(0, base - dh, 0, base);
        pg.addColorStop(0, `rgba(${col},${0.5 * pulse + 0.1})`);
        pg.addColorStop(1, `rgba(${col},0.08)`);
        c.fillStyle = pg;
        c.beginPath();
        c.moveTo(x - dw / 2 + 2 * this.dpr, base);
        c.lineTo(x - dw / 2 + 2 * this.dpr, base - dh * 0.62);
        c.quadraticCurveTo(x, base - dh * 1.18, x + dw / 2 - 2 * this.dpr, base - dh * 0.62);
        c.lineTo(x + dw / 2 - 2 * this.dpr, base);
        c.closePath(); c.fill();
        // drifting motes inside
        for (let m = 0; m < 5; m++) {
          const my2 = base - ((t * (0.04 + 0.012 * m) + m * 0.23) % 1) * dh;
          c.globalAlpha = 0.6 * pulse;
          c.fillStyle = "#cfd0ff";
          c.beginPath();
          c.arc(x + Math.sin(t + m * 2.2) * dw * 0.22, my2, 1.3 * this.dpr, 0, 6.283);
          c.fill();
        }
        c.globalAlpha = 1;
      } else {
        // chains on the sealed door
        c.strokeStyle = "rgba(120,112,140,0.8)";
        c.lineWidth = 2 * this.dpr;
        for (const yy of [0.35, 0.55, 0.72]) {
          c.beginPath();
          c.moveTo(x - dw / 2, base - dh * yy);
          c.lineTo(x + dw / 2, base - dh * (yy - 0.06));
          c.stroke();
        }
      }
      c.restore();
      // label
      c.fillStyle = `rgba(233,228,242,${p.sealed ? 0.45 : p.unstable ? 0.95 : 0.85})`;
      c.font = `${Math.max(11, Math.round(H * 0.014))}px Georgia, serif`;
      c.textAlign = "center";
      c.fillText(p.label, x, base + H * 0.026);
    });
    c.textAlign = "left";
  }

  _drawWashashore(c, W, H, t) {
    // a glinting find on the wet sand, west of the doors
    const wx = 0.62 * W, wy = 0.66 * H;
    const glint = 0.5 + 0.5 * Math.sin(t * 2.2);
    const rg = c.createRadialGradient(wx, wy, 1, wx, wy, 12 * this.dpr);
    rg.addColorStop(0, `rgba(255,236,190,${0.5 + 0.4 * glint})`);
    rg.addColorStop(1, "rgba(232,180,107,0)");
    c.fillStyle = rg;
    c.beginPath(); c.arc(wx, wy, 12 * this.dpr, 0, 6.283); c.fill();
    c.fillStyle = "#e8b46b";
    c.beginPath();
    c.ellipse(wx, wy, 3.4 * this.dpr, 2.2 * this.dpr, 0.4 + 0.1 * Math.sin(t), 0, 6.283);
    c.fill();
  }

  _drawCampfire(c, W, H, t) {
    const { x: fx0, y: fy0 } = LAYOUT.camp;
    const fx = fx0 * W, fy = fy0 * H;
    // fire glow
    const flick = 0.7 + 0.3 * Math.sin(t * 9.3) * Math.sin(t * 3.7);
    const rg = c.createRadialGradient(fx, fy, 2, fx, fy, H * 0.13);
    rg.addColorStop(0, `rgba(255,157,92,${0.5 * flick})`);
    rg.addColorStop(0.4, `rgba(232,180,107,${0.16 * flick})`);
    rg.addColorStop(1, "rgba(232,180,107,0)");
    c.fillStyle = rg;
    c.beginPath(); c.arc(fx, fy, H * 0.13, 0, 6.283); c.fill();
    // silhouette seat ring + a figure
    c.strokeStyle = "rgba(60,50,86,0.9)";
    c.lineWidth = 3 * this.dpr;
    c.beginPath(); c.ellipse(fx, fy + 6 * this.dpr, W * 0.045, H * 0.012, 0, 0, 6.283); c.stroke();
    c.fillStyle = "rgba(30,24,52,0.95)";
    c.beginPath();
    c.ellipse(fx + W * 0.02, fy - H * 0.012, W * 0.008, H * 0.02, 0, 0, 6.283); c.fill();
    c.beginPath(); c.arc(fx + W * 0.02, fy - H * 0.038, H * 0.008, 0, 6.283); c.fill();
    // flames
    for (let f = 0; f < 3; f++) {
      const fh = (10 + f * 5) * this.dpr * (0.8 + 0.35 * Math.sin(t * 11 + f * 2.4));
      c.beginPath();
      c.moveTo(fx - (6 - f * 2) * this.dpr, fy);
      c.quadraticCurveTo(fx + Math.sin(t * 7 + f) * 4 * this.dpr, fy - fh * 1.4, fx, fy - fh);
      c.quadraticCurveTo(fx + Math.cos(t * 8 + f) * 3 * this.dpr + (6 - f * 2) * this.dpr, fy - fh * 0.9, fx + (6 - f * 2) * this.dpr, fy);
      c.closePath();
      c.fillStyle = f === 0 ? "rgba(255,157,92,0.95)" : f === 1 ? "rgba(232,180,107,0.85)" : "rgba(255,236,190,0.9)";
      c.fill();
    }
    // smoke (kettle steam joins when the camp kettle is built)
    for (let s = 0; s < 4; s++) {
      const sp = ((t * 0.05 + s * 0.25) % 1);
      c.globalAlpha = 0.16 * (1 - sp);
      c.fillStyle = "#8f86ad";
      c.beginPath();
      c.arc(fx + Math.sin(t + s * 1.7 + sp * 5) * 10 * this.dpr, fy - 14 * this.dpr - sp * H * 0.08, (2.5 + sp * 5) * this.dpr, 0, 6.283);
      c.fill();
    }
    if (this.view?.upgrades_owned?.includes("camp_kettle")) {
      // a dented kettle on a flat stone, breathing steam
      c.fillStyle = "rgba(70,62,100,0.95)";
      c.beginPath();
      c.ellipse(fx - 16 * this.dpr, fy - 2 * this.dpr, 6 * this.dpr, 4.6 * this.dpr, 0, Math.PI, 0);
      c.fill();
      c.fillRect(fx - 22 * this.dpr, fy - 2 * this.dpr, 12 * this.dpr, 1.6 * this.dpr);
      for (let s = 0; s < 3; s++) {
        const sp = ((t * 0.07 + s * 0.33) % 1);
        c.globalAlpha = 0.2 * (1 - sp);
        c.fillStyle = "#cfd0ff";
        c.beginPath();
        c.arc(fx - 16 * this.dpr + Math.sin(t + s) * 3 * this.dpr, fy - 8 * this.dpr - sp * 22 * this.dpr, (1.6 + sp * 2.6) * this.dpr, 0, 6.283);
        c.fill();
      }
      c.globalAlpha = 1;
    }
    if (this.view?.upgrades_owned?.includes("camp_guestbook")) {
      c.fillStyle = "rgba(201,184,160,0.8)";
      c.fillRect(fx + 18 * this.dpr, fy - 4 * this.dpr, 7 * this.dpr, 2.4 * this.dpr);
      c.strokeStyle = "rgba(120,112,140,0.9)";
      c.lineWidth = 0.8 * this.dpr;
      c.beginPath(); c.moveTo(fx + 21.5 * this.dpr, fy - 4 * this.dpr); c.lineTo(fx + 21.5 * this.dpr, fy - 1.6 * this.dpr); c.stroke();
    }
    c.globalAlpha = 1;
  }

  _drawTavern(c, W, H, t) {
    const { x: tx0, y: ty0 } = LAYOUT.tavern;
    const tx = tx0 * W, ty = ty0 * H;
    const tw = W * 0.085, th = H * 0.085;
    // body
    c.fillStyle = "rgba(24,19,44,0.96)";
    c.fillRect(tx - tw / 2, ty - th, tw, th);
    c.beginPath();
    c.moveTo(tx - tw / 2 - 5 * this.dpr, ty - th);
    c.lineTo(tx, ty - th - 9 * this.dpr);
    c.lineTo(tx + tw / 2 + 5 * this.dpr, ty - th);
    c.closePath();
    c.fill();
    // chimney
    c.fillRect(tx + tw * 0.22, ty - th - 16 * this.dpr, 6 * this.dpr, 12 * this.dpr);
    // lit windows
    for (const wx of [-0.26, 0.06]) {
      const wxx = tx + tw * wx, wyy = ty - th * 0.62;
      const wg = c.createRadialGradient(wxx, wyy, 1, wxx, wyy, 9 * this.dpr);
      wg.addColorStop(0, "rgba(232,180,107,0.95)");
      wg.addColorStop(1, "rgba(232,180,107,0)");
      c.fillStyle = wg;
      c.beginPath(); c.arc(wxx, wyy, 9 * this.dpr, 0, 6.283); c.fill();
      c.fillStyle = "#e8b46b";
      c.fillRect(wxx - 3 * this.dpr, wyy - 3.5 * this.dpr, 6 * this.dpr, 7 * this.dpr);
    }
    // Maren's map wall glows warm through the right window once built
    if (this.view?.upgrades_owned?.includes("tavern_mapwall")) {
      const wxx = tx + tw * 0.3, wyy = ty - th * 0.35;
      const mg = c.createRadialGradient(wxx, wyy, 1, wxx, wyy, 12 * this.dpr);
      mg.addColorStop(0, "rgba(67,232,216,0.55)");
      mg.addColorStop(1, "rgba(67,232,216,0)");
      c.fillStyle = mg;
      c.beginPath(); c.arc(wxx, wyy, 12 * this.dpr, 0, 6.283); c.fill();
      c.strokeStyle = "rgba(67,232,216,0.7)";
      c.lineWidth = 1 * this.dpr;
      c.strokeRect(wxx - 5 * this.dpr, wyy - 4 * this.dpr, 10 * this.dpr, 8 * this.dpr);
    }
    // lantern by the door
    const lx = tx - tw / 2 - 6 * this.dpr, ly = ty - th * 0.35;
    c.strokeStyle = "rgba(120,112,140,0.9)";
    c.lineWidth = 1.2 * this.dpr;
    c.beginPath(); c.moveTo(lx, ly - 12 * this.dpr); c.lineTo(lx, ly); c.stroke();
    const sway = Math.sin(t * 1.4) * 1.5 * this.dpr;
    const lg = c.createRadialGradient(lx + sway, ly + 3 * this.dpr, 1, lx + sway, ly + 3 * this.dpr, 12 * this.dpr);
    lg.addColorStop(0, "rgba(255,236,190,0.95)");
    lg.addColorStop(1, "rgba(232,180,107,0)");
    c.fillStyle = lg;
    c.beginPath(); c.arc(lx + sway, ly + 3 * this.dpr, 12 * this.dpr, 0, 6.283); c.fill();
  }

  _drawLighthouse(c, W, H, t, v) {
    const { x: lx0, y: ly0 } = LAYOUT.lighthouse;
    const lx = lx0 * W, baseY = ly0 * H;
    const lh = H * 0.26, lw = W * 0.018;
    // rocks
    c.fillStyle = "rgba(16,12,30,0.95)";
    c.beginPath();
    c.moveTo(lx - lw * 3.2, baseY + 6 * this.dpr);
    c.quadraticCurveTo(lx - lw, baseY - 8 * this.dpr, lx + lw * 2.4, baseY);
    c.lineTo(lx + lw * 3.4, baseY + 8 * this.dpr);
    c.closePath(); c.fill();
    // tower (tapered)
    const grad = c.createLinearGradient(lx - lw, 0, lx + lw, 0);
    grad.addColorStop(0, "#1c1534");
    grad.addColorStop(0.5, "#2c2248");
    grad.addColorStop(1, "#171129");
    c.fillStyle = grad;
    c.beginPath();
    c.moveTo(lx - lw * 0.55, baseY);
    c.lineTo(lx - lw * 0.38, baseY - lh * 0.82);
    c.lineTo(lx + lw * 0.38, baseY - lh * 0.82);
    c.lineTo(lx + lw * 0.55, baseY);
    c.closePath(); c.fill();
    // gallery + lamp room
    c.fillStyle = "#120e24";
    c.fillRect(lx - lw * 0.52, baseY - lh * 0.92, lw * 1.04, lh * 0.09);
    c.strokeStyle = "rgba(155,140,255,0.6)";
    c.lineWidth = 1.2 * this.dpr;
    c.strokeRect(lx - lw * 0.4, baseY - lh * 1.06, lw * 0.8, lh * 0.13);
    // dome
    c.beginPath();
    c.moveTo(lx - lw * 0.45, baseY - lh * 1.06);
    c.quadraticCurveTo(lx, baseY - lh * 1.22, lx + lw * 0.45, baseY - lh * 1.06);
    c.closePath();
    c.fillStyle = "#1a1430"; c.fill();
    // window slits
    for (const wy of [0.2, 0.38, 0.56]) {
      c.fillStyle = "rgba(155,140,255,0.5)";
      c.fillRect(lx - lw * 0.14, baseY - lh * wy, lw * 0.28, lh * 0.035);
    }
    // sweeping beam (casts no shadow); teal once the light is relamped
    const relit = this.view?.upgrades_owned?.includes("light_relamp");
    const sweep = Math.sin(t * 0.5);
    const beamLen = W * 0.30;
    const bx = lx, by = baseY - lh;
    c.save();
    c.translate(bx, by);
    c.rotate(sweep * 0.55 - 0.35);
    const bg = c.createLinearGradient(0, 0, beamLen, 0);
    if (relit) {
      bg.addColorStop(0, "rgba(67,232,216,0.55)");
      bg.addColorStop(1, "rgba(67,232,216,0)");
    } else {
      bg.addColorStop(0, "rgba(233,228,242,0.5)");
      bg.addColorStop(1, "rgba(233,228,242,0)");
    }
    c.fillStyle = bg;
    c.beginPath();
    c.moveTo(0, -3 * this.dpr); c.lineTo(beamLen, -14 * this.dpr);
    c.lineTo(beamLen, 14 * this.dpr); c.lineTo(0, 3 * this.dpr);
    c.closePath(); c.fill();
    c.restore();
    // lamp core
    const lg = c.createRadialGradient(bx, by, 1, bx, by, 10 * this.dpr);
    lg.addColorStop(0, "rgba(233,228,242,0.9)");
    lg.addColorStop(1, "rgba(233,228,242,0)");
    c.fillStyle = lg;
    c.beginPath(); c.arc(bx, by, 10 * this.dpr, 0, 6.283); c.fill();
  }

  _drawSeacave(c, W, H, t) {
    const { x, y } = LAYOUT.seacave;
    const cx = x * W, cy = y * H;
    // bluff
    c.fillStyle = "rgba(18,14,34,0.98)";
    c.beginPath();
    c.moveTo(cx - W * 0.09, H * 0.86);
    c.lineTo(cx - W * 0.09, cy - H * 0.03);
    c.quadraticCurveTo(cx, cy - H * 0.075, cx + W * 0.09, cy - H * 0.02);
    c.lineTo(cx + W * 0.09, H * 0.86);
    c.closePath(); c.fill();
    // cave mouth + inner glow
    const gg = c.createRadialGradient(cx, cy + 2, 1, cx, cy + 2, H * 0.05);
    gg.addColorStop(0, "rgba(67,232,216,0.55)");
    gg.addColorStop(1, "rgba(67,232,216,0)");
    c.fillStyle = "#0d0a18";
    c.beginPath();
    c.moveTo(cx - W * 0.022, cy + H * 0.05);
    c.quadraticCurveTo(cx - W * 0.03, cy - H * 0.05, cx, cy - H * 0.055);
    c.quadraticCurveTo(cx + W * 0.03, cy - H * 0.05, cx + W * 0.022, cy + H * 0.05);
    c.closePath(); c.fill();
    c.fillStyle = gg;
    c.beginPath(); c.arc(cx, cy + H * 0.008, H * 0.036, 0, 6.283); c.fill();
  }

  _drawWreck(c, W, H, t) {
    const { x, y } = LAYOUT.wreck;
    const wx = x * W, wy = y * H;
    const wl = W * 0.075;
    c.save();
    c.translate(wx, wy);
    c.rotate(-0.08);
    c.fillStyle = "rgba(22,17,40,0.95)";
    c.beginPath();
    c.moveTo(-wl, 0);
    c.quadraticCurveTo(-wl * 0.9, H * 0.045, -wl * 0.5, H * 0.05);
    c.lineTo(wl * 0.8, H * 0.05);
    c.quadraticCurveTo(wl * 1.15, H * 0.02, wl, -H * 0.012);
    c.lineTo(-wl, 0);
    c.closePath(); c.fill();
    // mast
    c.strokeStyle = "rgba(30,24,52,0.95)";
    c.lineWidth = 2 * this.dpr;
    c.beginPath(); c.moveTo(-wl * 0.1, 0); c.lineTo(-wl * 0.02, -H * 0.075); c.stroke();
    // bell (brass glint)
    const bellGlow = 0.5 + 0.5 * Math.sin(t * 0.9);
    c.fillStyle = `rgba(232,180,107,${0.55 + 0.35 * bellGlow})`;
    c.beginPath();
    c.arc(wl * 0.55, -H * 0.008, 3.2 * this.dpr, Math.PI, 0);
    c.lineTo(wl * 0.55 + 3.2 * this.dpr, H * 0.006);
    c.lineTo(wl * 0.55 - 3.2 * this.dpr, H * 0.006);
    c.closePath(); c.fill();
    c.restore();
  }

  _drawSignpost(c, W, H) {
    const { x, y } = LAYOUT.signpost;
    const sx = x * W, sy = y * H;
    c.strokeStyle = "rgba(60,50,86,0.95)";
    c.lineWidth = 2.4 * this.dpr;
    c.beginPath(); c.moveTo(sx, sy + H * 0.03); c.lineTo(sx + 3 * this.dpr, sy - H * 0.05); c.stroke();
    c.fillStyle = "rgba(40,32,66,0.95)";
    c.save();
    c.translate(sx + 2 * this.dpr, sy - H * 0.045);
    c.rotate(-0.06);
    c.fillRect(-W * 0.021, -H * 0.012, W * 0.042, H * 0.024);
    c.restore();
  }

  _drawWeather(c, W, H, weather, t) {
    if (weather === "mist" || weather === "fogbank") {
      for (let i = 0; i < 5; i++) {
        const fy = H * (0.5 + 0.08 * ((i * 3.1) % 3));
        const drift = ((t * (8 + i * 3)) % (W * 1.6)) - W * 0.3;
        const fg = c.createRadialGradient(drift + W * i * 0.2, fy, 1, drift + W * i * 0.2, fy, W * 0.22);
        fg.addColorStop(0, `rgba(122,110,168,${weather === "fogbank" ? 0.13 : 0.08})`);
        fg.addColorStop(1, "rgba(122,110,168,0)");
        c.fillStyle = fg;
        c.fillRect(0, 0, W, H);
      }
    }
    if (weather === "drizzle" || weather === "storm") {
      if (this.calm) {  // reduced motion: no falling particles
        if (weather === "storm") {
          c.fillStyle = "rgba(180,190,230,0.06)";
          c.fillRect(0, 0, W, H);
        }
      } else {
        const n = weather === "storm" ? 130 : 60;
        if (this.rain.length !== n) {
          this.rain = Array.from({ length: n }, () => ({ x: Math.random(), y: Math.random(), v: 0.35 + Math.random() * 0.4 }));
        }
        c.strokeStyle = weather === "storm" ? "rgba(180,190,230,0.4)" : "rgba(160,170,210,0.28)";
        c.lineWidth = 1 * this.dpr;
        for (const r of this.rain) {
          r.y += r.v * 0.016; r.x -= r.v * 0.004;
          if (r.y > 1) { r.y = -0.05; r.x = Math.random(); }
          if (r.x < -0.05) r.x = 1.05;
          c.beginPath();
          c.moveTo(r.x * W, r.y * H);
          c.lineTo((r.x - 0.008) * W, (r.y - 0.02) * H);
          c.stroke();
        }
        if (weather === "storm" && Math.sin(t * 0.31) > 0.996) {
          c.fillStyle = "rgba(210,205,255,0.14)";
          c.fillRect(0, 0, W, H);
        }
      }
    }
    if (weather === "clear") {
      for (const m of this.motes) {
        const fy = H * (0.62 + 0.3 * m.y * 0.5);
        c.globalAlpha = 0.4 + 0.4 * Math.sin(t * 1.4 * m.s + m.p);
        c.fillStyle = "#b9f0c8";
        c.beginPath();
        c.arc((m.x + Math.sin(t * 0.2 + m.p) * 0.01) * W, fy + Math.sin(t * 0.35 * m.s + m.p) * 8 * this.dpr, 1.4 * this.dpr, 0, 6.283);
        c.fill();
      }
      c.globalAlpha = 1;
    }
    // vignette edges
    const vg = c.createRadialGradient(W / 2, H / 2, H * 0.45, W / 2, H / 2, H * 0.95);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(1, "rgba(4,3,10,0.55)");
    c.fillStyle = vg;
    c.fillRect(0, 0, W, H);
  }

  _drawHover(c) {
    if (!this.hover) return;
    const h = this.hover;
    const x = h.x * this.w * this.dpr, y = h.y * this.h * this.dpr;
    const hw = (h.kind === "hotspot" && h.id === "beam" ? 0.25 : h.w) * this.w * this.dpr;
    const hh = h.h * this.h * this.dpr;
    c.strokeStyle = "rgba(233,228,242,0.55)";
    c.lineWidth = 1.2 * this.dpr;
    c.setLineDash([4 * this.dpr, 4 * this.dpr]);
    c.strokeRect(x - hw, y - hh / 2, hw * 2, hh);
    c.setLineDash([]);
  }
}
