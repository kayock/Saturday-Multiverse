# Cinematics (v1)

Saturday Multiverse can play **pre-rendered** atmospheric videos from the
OpenFilm Saturday Multiverse Cinematic Asset Pack v1.

These videos are **presentation only**. They never change game rules, dice,
inventory, multiplayer turns, or save data. Skipping or disabling them is
always safe.

## Where files live

```text
client/assets/cinematics/
  videos/          # 17 MP4s (Git LFS)
  stills/          # Juggernaut / reused source stills
  thumbnails/      # optional previews
  meta/
    pack-manifest.json   # upstream pack inventory
    game-catalog.json    # deterministic location/event → file map
    INVENTORY.md
    AUDIO_LICENSING.md
```

Paths are relative to the client. The game does **not** depend on OpenFilm,
Juggernaut, or Portable’s 1 TB mount.

## Player controls

Settings → **Sound & motion / Cinematics**:

- Enable / disable location cinematics
- Cinematic volume
- Ambient loop audio (off by default — the game already synthesizes ambience)
- Portal / intro clip audio
- Skip current clip / replay last clip

Also:

- On-screen **Skip** during one-shot clips
- **Calm mode** and **`prefers-reduced-motion`** disable cinematic playback
  and keep the canvas / SVG vignettes

## Placement (deterministic)

| Game context | Video |
|---|---|
| Tide Gate / Beam | Beam loop; establishing once per campaign visit |
| Shore weather mist/fog/storm | Shore mist / storm loops |
| Driftwood Camp | Campfire loop |
| Salt & Lantern | Tavern loop; storm/supernatural variants by weather / scene |
| Skyless Light | Shore loop / storm emphasis |
| Door of Salt / Ash / Unstable | Matching portal activations (non-blocking) |
| Drowned Bay / Salt-Grave Signal | Intro clip once per campaign |

Missing files fall back to the existing canvas or SVG vignette with no error dialogs.

## Multiplayer

Each browser plays its own videos. Skipping does not sync. Travel and GM
actions are never awaited on video completion.

## Git / install

MP4s are tracked with **Git LFS**. After cloning:

```bash
git lfs install
git lfs pull
```

Without LFS objects, the game still runs; cinematics simply stay unavailable.

## Upstream production

See [CINEMATICS_PRODUCTION.md](CINEMATICS_PRODUCTION.md) for the OpenFilm pack
report (artwork generation, renders, QC). Artwork attribution: Juggernaut XL
stills produced for this pack; synthesized AAC beds documented in
`client/assets/cinematics/meta/AUDIO_LICENSING.md`.
