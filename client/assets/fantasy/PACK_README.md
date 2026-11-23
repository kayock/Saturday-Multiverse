# Multiverse Fantasy Asset Pack

**100 original AI-generated photorealistic fantasy images** for a multiverse game, with a full metadata manifest (location, weather, time of day, intended use) for every asset.

## Contents

| Category | Count | Asset IDs |
|---|---|---|
| World Environments | 20 | ENV-001 – ENV-020 |
| Towns and Interiors | 20 | TWN-001 – TWN-020 |
| NPC Portraits | 25 | NPC-001 – NPC-025 |
| Monsters and Creatures | 15 | MON-001 – MON-015 |
| Magical Events and Portals | 10 | MAG-001 – MAG-010 |
| Items and Discoveries | 10 | ITM-001 – ITM-010 |
| **Total** | **100** | 100 unique IDs |

## Folder structure

```
fantasy-asset-pack/
├── README.md                  ← this file
├── asset-manifest.json        ← machine-readable manifest (all metadata)
├── asset-manifest.xlsx        ← human-readable manifest spreadsheet
└── images/
│   ├── 01_world_environments/   (20 images)
│   ├── 02_towns_and_interiors/   (20 images)
│   ├── 03_npc_portraits/   (25 images)
│   ├── 04_monsters_and_creatures/   (15 images)
│   ├── 05_magical_events_and_portals/   (10 images)
│   ├── 06_items_and_discoveries/   (10 images)
```

## ID scheme

- `ENV-###` World Environments · `TWN-###` Towns & Interiors · `NPC-###` NPC Portraits
- `MON-###` Monsters & Creatures · `MAG-###` Magical Events & Portals · `ITM-###` Items & Discoveries
- File name = `{ID}_{title-slug}.png`, e.g. `ENV-001_ashfall-caldera.png`.

## Image formats

- World environments, towns/interiors, magical events/portals: **1344 × 768 landscape** (zone vistas, hubs, cutscenes)
- NPC portraits: **768 × 1344 portrait** (dialogue cards, character sheets)
- Monsters and items: **1024 × 1024 square** (bestiary entries, loot cards, inventory art)

## Metadata fields (per asset, in both manifests)

- **Asset ID** — unique stable identifier
- **Title** — asset name
- **Location** — in-world place where the scene/portrait/item lives
- **Weather** — atmospheric condition of the shot (interiors note their own ambience)
- **Time of day** — lighting period
- **Intended use** — how to deploy it in a multiverse game (biome backdrop, hub, dialogue card, bestiary entry, event cutscene, loot card…)
- **Generation prompt** — the exact prompt used, for reproducibility and style matching when extending the pack

## Notes

- All images are original AI-generated renders in a photorealistic cinematic style; no copyrighted characters or existing game assets are depicted.
- The pack is self-consistent: recurring places (e.g. Mirrorwood, Emberfall Ravine, Celestial Steppe, Deepdelve) appear across categories so biomes, vendors, monsters and quests can be combined into coherent realms.
