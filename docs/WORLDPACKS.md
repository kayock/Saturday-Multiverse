# World packs

A world pack is a directory with `pack.json` (+ optional `lore.md` and other sibling
files). Packs are **pure data** — the loader validates them and nothing in them is
executed, ever.

- Built-in (redistributable) packs live in `worldpacks/`.
- User-imported packs live in `<data dir>/worldpacks/` and are kept separate, so
  privately-licensed material can never be mistaken for public assets or shipped by
  accident.

Import via the API:

```
POST /api/packs/import   {"pack_json": "<the whole pack.json as a string>"}
```

Pack ids must be lowercase letters, digits, `-` and `_`.

## Minimal pack

```json
{
  "id": "my_universe",
  "name": "My Universe",
  "version": "0.1.0",
  "summary": "One paragraph shown in the pack list.",
  "genre_tags": ["space exploration", "diplomacy"],
  "theme": {"bg": "#0b0e14", "purple": "#7c5cff", "teal": "#43e8d8", "gold": "#e8b46b"},
  "gm_style": "How the Game Master should sound.",
  "lore": "Inline lore bible, or use lore_file below.",
  "lore_file": "lore.md",
  "hub_location": "hub",
  "locations": [
    {"id": "hub", "name": "Hub", "short": "one line", "desc": "Arrival text.",
     "known": true, "hotspots": [{"id": "s1", "label": "thing", "x": 50, "y": 40,
                                  "text": "What the player sees on click."}]}
  ],
  "archetypes": [
    {"id": "scout", "name": "Scout", "blurb": "…",
     "stats": {"wits": 2, "might": 0, "mettle": 0, "bind": -1},
     "palette": "tide", "kit": ["rope"]}
  ],
  "items": [
    {"id": "rope", "name": "Rope", "kind": "tool", "desc": "…",
     "use": {"text": "You tie it off.", "flag": "rope_tied", "consume": false}}
  ],
  "omens": [], "portals": [], "npcs": [], "adventures": []
}
```

## Field reference (the parts that do things)

- **locations** — `requires: {"tide": "low", "discovered": true}` gates entry;
  `known: false` hides it from the map until discovered; `on_enter` is a list of
  effect objects applied on first arrival; `rest: {"vigor": 3, "nerve": 2}` + `rest_text`
  makes it a resting place; `flavor` is a list of fallback/ambience lines;
  `adventure: "<adventure_id>"` marks it as a portal destination.
- **portals** — doors on the Beam: `{"id", "label", "target_location", "hint"}` or
  `{"id", "label", "sealed": true, "seal_note": "…"}`.
- **effects** (used by `on_enter`, choices, item `use`, QR events) — all optional:
  `journal`, `fact`, `hidden_fact`, `item_give: [{"item_id","qty"}]`,
  `item_take`, `quest_update: {quest_id, title?, status?, note?}`,
  `harm: {type: vigor|nerve, amount}`, `heal: {vigor?, nerve?}`, `flag`,
  `discover: "<location_id>"`, `npc_rel: {npc_id, delta}`, `ending`, `return_shore`.
- **choices** (inside adventure scenes) — `requires_item` / `requires_flag` /
  `forbid_flag` + `locked_hint` gate availability; `check: {skill, hard,
  riptide_counts_pass}` triggers a real roll with `on_pass` / `on_fail` branches
  (each `{goto, effects}`); without a check, `goto` + `effects` apply directly.
- **endings** — `{"<id>": {"text": "epilogue", "return_location": "hub"}}`.
- **omens** — `{id, kind: edge|complication|turn, title, text, boost}`.
  Edges grant `+1` on the boosted skill until consumed; complications impose `−1`
  on any one check; turns are pure atmosphere. Drawn every 3rd turn in
  `deck_mode: "agent"`.
- **qr_lore / qr_events** — optional extras for printed QR cards
  (`SM:LORE:<id>`, `SM:EVT:<id>`); see `docs/QR_CARDS.md`.

## Checking a pack

`worldpacks.list_packs()` validates on load; the test suite additionally asserts that
every choice `goto` target, archetype kit item, and reward item exists. When writing a
pack, run:

```bash
python -m pytest tests/test_worldpacks.py -q
python scripts/smoke_test.py
```

## Milestone 2 roadmap for packs

- Per-pack mechanics overlays (e.g. space packs use a Ship panel, horror packs use
  Nerve differently) declared as `mechanics: {}` and consumed by the rules engine.
- Map style variants and pack-specific vignette art directories.
- Document imports: drop plaintext/markdown lore into the pack folder; it is indexed
  into the FTS search and offered to the GM as grounding snippets (the FOXAI-style
  source search, modernized with SQLite FTS5).
- Companion memory upgrades: per-NPC fact lists with importance and decay.
