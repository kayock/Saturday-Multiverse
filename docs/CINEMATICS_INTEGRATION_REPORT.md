# Cinematic Integration v1 — Verification Report

**Date:** 2026-11-22  
**Branch:** `cinematic-integration-v1`  
**Baseline (pre-integration HEAD):** `84f5a75` (`cinematic-integration-v1-baseline` tag intent)  
**Game version lineage:** 0.5.0-forge-ai → changelog entry **0.5.1-cinematics**

## Baseline checkpoint

- Started from `station-lan-gm-routing` @ `84f5a75`
- New branch: `cinematic-integration-v1`
- Recoverable: `git checkout 84f5a75` or merge-base with `main`

## Imported inventory

17 MP4s + 5 stills + metadata under `client/assets/cinematics/`  
Catalog: `client/assets/cinematics/meta/game-catalog.json`  
Upstream pack manifest: `client/assets/cinematics/meta/pack-manifest.json`

| Asset | Mapping |
|---|---|
| Beam loop / establishing | `tidegate` |
| Living shore / mist / storm | shore exterior + lighthouse |
| Tavern / storm / supernatural | `tavern` |
| Campfire | `camp` |
| Portal violet / salt / ash / unstable | portal travel / seed door |
| Salt-Grave intro | `saltgrave_gate` / `salt_grave_signal` |

## Implementation

| Piece | Path |
|---|---|
| Library + player | `client/js/cinematics.js` |
| Hooks | `client/js/main.js` (`renderGame`, `doTravel`, seed door) |
| Portal id on door click | `client/js/scene.js` |
| Settings controls | `client/js/ui.js` |
| Styles | `client/css/style.css` |
| Docs | `docs/CINEMATICS.md`, this report, LICENSE notes, CHANGELOG |

### Playback controls

Enable, volume, ambient audio, one-shot audio, skip, replay; on-screen Skip during one-shots; mute toggle on chrome.

### Multiplayer

Client-local presentation only. Travel API is not awaited on video. Skip does not POST game state.

### Performance

No OpenFilm / Juggernaut / model jobs. Videos lazy-loaded via `<video preload="none">`. Ambient replaced on location change; one-shots cleared on end/skip.

### Save compatibility

No schema or save format changes. Seen-enter flags use `localStorage` only (`sm_cinematics_seen_v1`).

### Distribution

- **Git LFS** for `client/assets/cinematics/videos/*.mp4` (`.gitattributes`)
- Installer note: `git lfs install && git lfs pull`
- Game remains playable if LFS objects are missing (canvas fallback)

### Verification performed

- Catalog lists 17 assets; all video files present on disk
- Live server `GET /assets/cinematics/meta/game-catalog.json` → 200
- Live server serves campfire MP4 → 200 (~16 MB)
- `pytest tests/test_m40.py` → 16 passed
- Saturday Multiverse `/api/health` → ok

### Remaining limitations / future ideas

1. Door of Roots has no dedicated sealed cinematic (deferred in pack).
2. Umbral Reach / Ninth Wave / wreck / cave lack dedicated plates.
3. NPC portrait cinematics not integrated (pack deferred).
4. Ambient cinematic audio defaults off to avoid doubling `audio.js` beds.
5. Establishing shots are once-per-campaign in localStorage (not server-side).
6. Literary destination plates not mapped.

### Not implemented (by design)

- No OpenFilm sidecar, no generation queues, no rule changes, no auth changes.
