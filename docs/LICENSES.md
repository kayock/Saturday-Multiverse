# Licensing & attribution

## Starter adventures (public-domain literature)

| Pack | Source | Author | License | Source text |
|---|---|---|---|---|
| Dracula: The White Ship | *Dracula* (1897) | Bram Stoker | Public domain | https://www.gutenberg.org/ebooks/345 |
| The Rue Morgue Affair | "The Murders in the Rue Morgue" (1841) | Edgar Allan Poe | Public domain | https://www.gutenberg.org/ebooks/2148 |
| The Time Machine | *The Time Machine* (1895) | H. G. Wells | Public domain | https://www.gutenberg.org/ebooks/35 |

Original adaptation text, choices, engine content and pack assembly for
these packs: Saturday Multiverse (its own project license applies). Each
pack embeds this attribution in its `license` block, shown in the
adventure preview.

## D&D-compatible ruleset

Derived exclusively from the **System Reference Document 5.1** ("SRD 5.1"),
released by Wizards of the Coast under the **Creative Commons Attribution
4.0 International license (CC-BY-4.0)**.

- This product is not affiliated with, endorsed by, or sponsored by
  Wizards of the Coast. No product identity is used.
- Files: `server/rules_dnd.py` (rules), the `dnd` blocks of the starter
  packs, and the D&D selection in the client.
- Attribution (required by CC-BY-4.0): *"D&D-compatible rules derived from
  the System Reference Document 5.1 by Wizards of the Coast, licensed
  under Creative Commons Attribution 4.0 International."*

## Literature-derived stat blocks

Vampire Spawn (Dracula), Morlock (The Time Machine) and the Great Ape
(Rue Morgue) use stat blocks authored by Saturday Multiverse from the
public-domain novels' descriptions. They are **not** SRD content and carry
`"source": "literature"` in the bestiary.

## Cinematic asset pack v1

Pre-rendered MP4s and stills under `client/assets/cinematics/`:

- **Gameplay code and integration:** Saturday Multiverse project license.
- **Juggernaut XL stills** (tavern, living shore, portal, campfire, Salt-Grave
  drowned bay): generated for this project’s asset pack; keep with the game for
  offline play. Generation parameters are recorded in the pack metadata.
- **Audio beds** in the videos: synthesized locally (ffmpeg noise/tones); see
  `client/assets/cinematics/meta/AUDIO_LICENSING.md`.
- Upstream production notes: `docs/CINEMATICS_PRODUCTION.md`.

Cinematics are optional presentation media. The game never requires OpenFilm or
Image Hub at runtime.

## Private manuscripts

Documents imported with the private flag (e.g., Eric Z. Fox's *Roanoke*)
remain the property of their authors: stored locally, never distributed,
never shipped with any package, and never fabricated by this project.

## Fantasy Asset Pack (0.5.2)

100 AI-generated fantasy stills under `client/assets/fantasy/` with preserved
asset IDs (`ENV-` / `TWN-` / `NPC-` / `MON-` / `MAG-` / `ITM-`). Attribution:
`client/assets/fantasy/ATTRIBUTION.md`. OpenFilm loops derived from four stills
use Ken Burns + canvas overlays (not generative video).
