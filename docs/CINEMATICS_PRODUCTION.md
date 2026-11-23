# Saturday Multiverse Cinematic Asset Pack v1 — Production Report

**Date:** 2026-11-22  
**OpenFilm:** 0.4.1 on kayock-Ubuntu-Portable  
**Pack path:** `/run/media/kayock/KAYOCK-1TB/openfilm/cinematic-packs/saturday-multiverse-v1/`  
**Station gateway:** http://10.0.0.202:4750/ (unchanged architecture)

**Scope note:** OpenFilm asset production only. Saturday Multiverse was inspected **read-only**. No game code, data, or services were modified.

---

## 1. Game content inspected

| Source | Finding |
|--------|---------|
| `/home/kayock/Applications/Saturday-Multiverse` v0.5.0-forge-ai | Live on Station `:8788` |
| `worldpacks/living_shore/` | Hub world: Tide Gate, Driftwood Camp, Salt & Lantern, Skyless Light, sea cave, Marrow Bell, Drowned Bay, Umbral Reach, Ninth Wave |
| NPCs | Old Cardo, Maren, Drowned Lampkeeper, Vess |
| Portals | door_salt, door_ash, door_roots (sealed), door_unstable |
| Adventures | Salt-Grave Signal, Umbral Market, Skyless Light |
| Weather keys | mist, clear, drizzle, storm, fogbank |
| Tide | high/low (cave & wreck gated) |
| Literary packs | Dracula, Rue Morgue, Time Machine (destination context only) |

Full planning table: `reports/CONTENT_AUDIT.md`.

---

## 2. Assets created / catalogued

**17 MP4s** in pack `exports/` (6 prior photoreal + 11 new), all 1920×1080 @ 30fps h264+aac.

See `manifests/INVENTORY.md` and `manifests/pack-manifest.json`.

### New Juggernaut generations (2)

| Still | Seed | Wall time | Path |
|-------|------|-----------|------|
| Driftwood campfire | 77112233 | ~394 s | `artwork/juggernaut-campfire/campfire-primary.png` |
| Drowned Bay (Salt-Grave) | 66114455 | ~392 s | `artwork/juggernaut-saltgrave/saltgrave-primary.png` |

Image Hub stopped after generation. Existing tavern/shore/portal stills **reused** (copied into `artwork/reused/`).

### New OpenFilm projects

Under `projects/`: `sm-beam-tidegate`, `sm-campfire-driftwood`, `sm-tavern-storm`, `sm-tavern-supernatural`, `sm-shore-mist`, `sm-shore-storm`, `sm-portal-salt`, `sm-portal-ash`, `sm-portal-unstable`, `sm-saltgrave-intro`.

Each has `scene.html`, `film.html`, `params.json`, assets, and README.

### Reused existing projects (not moved)

`saturday-tavern-photoreal`, `saturday-living-shore-photoreal`, `saturday-portal-photoreal` remain in the main OpenFilm projects tree.

---

## 3. Template parameters

Schema: `templates/scene-params.schema.json`  
Per-project defaults: `projects/*/params.json` baked into `scene.html` as `window.film.params` (override via `window.filmParams`).

Examples: `weather`, `fire_intensity`, `fog_density`, `beam_intensity`, `portal_color`, `intensity`, `particle_density`, `supernatural`, `camera_motion`, `duration_seconds`.

**Not** a Saturday Multiverse API.

---

## 4. Rendering performance (representative)

| Export | Frames | Wall (render) |
|--------|--------|---------------|
| Campfire 16s | 480 | ~17.6 s |
| Beam loop 18s | 540 | ~21.2 s |
| Beam establishing 40s | 1200 | ~33.4 s |
| Tavern storm/supernatural 16s | 480 | ~17–19 s |
| Shore mist/storm 18s | 540 | ~21 s |
| Portal salt/ash 8s | 240 | ~10 s |
| Portal unstable 16s | 480 | ~17.8 s |
| Salt-Grave intro 12s | 360 | ~13.7 s |

Encoder: h264_nvenc · 4 workers · ~380 MB RSS typical.

---

## 5. Quality control

- `reports/qc-probe.json`: all pack MP4s probed; **A/V duration sync OK** on every file.
- Deterministic look checks passed on campfire (and prior Phase 2/3 assets).
- Station download of completed MP4s via gateway **without re-render**: campfire + beam loop HTTP 200, correct durations.
- Gateway healthz: studio/film/plugins true (4747–4749).
- Existing photoreal tavern/shore/portal projects & exports **preserved**.
- Ollama OK; Image Hub inactive after gens.
- Saturday Multiverse health endpoint still OK (untouched).

### Honest limitations

1. Motion is **Ken Burns + canvas overlays** on still plates — not full 3D or generative video.
2. Door glows on the Beam are **composited markers**, not modeled 3D portals standing in surf.
3. NPC portrait cinematics **deferred** (game uses procedural SVG portraits; no facial performance claimed).
4. Umbral Market, Ninth Wave, sea cave, Marrow Bell plates **deferred**.
5. Door of Roots sealed variant **deferred**.
6. Beam establishing labeled **40s** (audio bed length), not 30s.
7. Loops use seamless sin/cos camera; labeled loopable where that applies.
8. SwiftShader WebGL on Portable for look/render.

---

## 6. Station access

Unchanged Phase 3 stack:

- `openfilm-tunnel.service` → 4747–4749  
- `openfilm-station-gateway.service` → `:4750`  
- Fleet Monitor Studio Tools + Family Hub OpenFilm entry  
- New `sm-*.mp4` also copied into `/run/media/kayock/KAYOCK-1TB/openfilm/exports/` for `/exports/` listing  

---

## 7. Ready for future integration vs refine

**Ready (hub / adventure core):** Beam, Campfire, Tavern (+storm/supernatural), Shore (+mist/storm), Portal violet/salt/ash/unstable, Salt-Grave intro, prior photoreal baselines.

**Needs further refinement before integration:** NPC portraits; Umbral/Ninth Wave/wreck/cave locations; literary destination plates; optional low-tide specific plates.

**Integration recommendations (not implemented):** map `location.id` / `portal_id` / `weather` / adventure id to manifest asset ids; prefer gateway-served MP4 URLs or local pack mount; keep OpenFilm as authoring tool of record.

---

## 8. Restrictions honored

- Saturday Multiverse: **read-only**  
- LocalForge / Cline / model configs: untouched  
- No new auth, no large model installs, no GitHub publish  
- Existing OpenFilm projects/exports/reports preserved  
- Juggernaut: exactly two new primary stills  
