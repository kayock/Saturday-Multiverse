# Saturday Multiverse

**An AI-powered, self-hosted, multiplayer-capable roleplaying adventure platform.**

> *Which Portal on the Beam?*
> *Dada Chunk, Da Dachink — Open a Door Before You Sink!*

Saturday Multiverse is a cinematic point-and-click tabletop experience. A person sits
down on Saturday night, walks along **the Living Shore** — a persistent beach between
universes — chooses one of the glowing doors standing in the shallows, and disappears
into an adventure worth remembering. An AI Game Master narrates; the application
itself owns every rule, every die, and every consequence.

- **Solo first.** No account, no cloud, no third-party hosting. Everything runs on your machine.
- **Honest AI.** The Game Master is any OpenAI-compatible model endpoint (local or remote).
  The app never lets the model roll dice, edit your inventory, or invent state. If no model
  is configured, a clearly-labeled **Offline Storyteller** keeps the game playable — it is
  never passed off as AI.
- **Persistent.** SQLite-backed campaigns with characters, inventory, journal, quests,
  NPC relationships, memory facts, dice logs, session transcripts, and full-text search.
  Close the app mid-adventure; resume weeks later through a door that remembers you.
- **Modular.** World packs are pure data: locations, NPCs, items, archetypes, omen decks,
  adventures, lore. Ship original packs, import your own, keep them separate from code.
- **Extensible toward multiplayer.** The schema and API are already host-authoritative;
  Milestones 3–4 add invitations, synchronization, and cross-server guest portals.

### v0.3.6 — The Living Campaign (new in this build)

- **Player-controlled D&D combat.** Encounters are persistent, turn-based and
  engine-resolved: initiative, player-selected actions (attack, cast, defend,
  use an item, retreat, stabilize), enemy turns, conditions, concentration,
  death saving throws, and exactly-once rewards. HP carries across encounters;
  the dead stay dead — no accidental resurrection. Idle turns are auto-defended
  by a bounded server sweep.
- **Honest rules.** 10 SRD 5.1 classes, 8 species, 20 spells with slots,
  saving throws, encounter difficulty from XP thresholds, and a published
  coverage table of what is supported and what is deliberately not.
- **Multiplayer completion.** Party splitting and regrouping with
  location-scoped narration (private discoveries stay private), read-only
  spectators, per-character ownership in shared combat, and a server-side
  watchdog for stalled turns.
- **The whole book, not a sample.** Campaign conversions analyze the ENTIRE
  document in bounded windows (structure → full extraction → deterministic
  consolidation → world bible that records how the story ends), with coverage
  metrics, resumable jobs, retry/cancel, and manual draft editing with
  version history, comparison, rollback, duplication and an SVG flow editor.
- **The Living Campaign Director.** Quests, mysteries, threats and consequences
  tracked with event evidence; optional pacing suggestions that never force
  anything and can be turned off; deterministic continuity flags (dead
  characters speaking, duplicated artifacts, contradictory quest states).
- **Collaborative worldbuilding.** The Worldbuilding Workshop lets a creator
  and collaborators write one world together on the SAME universal Forge:
  proposed contributions, review-time conflict detection (nothing silently
  overwritten), AI suggestions that are never auto-applied, creator-only
  approval through the same engine validation, and strict spoiler boundaries —
  contributors see their own GM secrets, never anyone else's.
- **Checkpoints.** Save a campaign snapshot and restore it later as a NEW
  campaign (no automatic rollback of shared history).

---

## Quick start

You need **Python 3.10+** and **Flask** (`pip install flask`). Nothing else — no build
step, no Node, no database server.

### Linux / macOS

```bash
pip install flask
./run.sh
# open http://127.0.0.1:8788
```

### Windows

```bat
pip install flask
run.bat
rem open http://127.0.0.1:8788
```

The server binds to `127.0.0.1` by default. Useful environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SATURDAY_PORT` | `8788` | HTTP port |
| `SATURDAY_HOST` | `127.0.0.1` | Bind address (widen only if you understand the security notes) |
| `SATURDAY_TOKEN` | *(empty)* | Shared secret required from non-localhost clients |
| `SATURDAY_DATA_DIR` | `./userdata` | Where the database, backups and exports live |

### Connecting an AI Game Master

In the game: **Settings → Model**. Point it at any OpenAI-compatible `/v1` endpoint and
press **Test connection**. See [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md) for recipes
(Ollama, LM Studio, llama.cpp, OpenAI, OpenRouter, …) and the JSON contract the model
must follow. No key is ever sent anywhere except the endpoint you configure.

Without a model the game still runs — dice, tides, choices, saves all work — and every
turn is honestly labeled *offline storyteller*.

### Playing

1. **New Voyage** — name yourself, pick an archetype (Sensitive, Warden, Deepwright,
   Lanternist), choose a specialty, step through the foam.
2. Walk the shore: click the **campfire**, the **tavern**, the **lighthouse**, or one of
   the three **doors** on the Beam. Check the **Map** for discovered places.
3. Type anything into the composer — the Game Master narrates and may call for a check;
   the app rolls `2d6` and applies the outcome (Undertow / Riptide / Clean / Surge).
4. Through the **Door of Salt** lies the starter adventure,
   **The Salt-Grave Signal** — a drowned bay is broadcasting a name in lamplight.
   Light the beacon, answer the call, or sink the tower. Each ending is permanent
   and remembered.
5. **Journal / Pack / Quests / Dice** panels keep your story organized; **Map** shows
   the shore; tide and weather change what the shore reveals (the sea cave and the
   wreck only surface at low tide).

Optional: print QR cards (`python scripts/make_qr_cards.py`) and scan them with any
USB keyboard-wedge scanner to open panels, inspect artifacts, or trigger approved
events. Scans are data-only and strictly allowlisted.

---

## What is implemented (Milestones 1 + 1.5 + 2.0 + 2.5)

**Milestone 1 — playable solo foundation**
- Title screen, explorable animated Living Shore (canvas: sky, Beam, moon, sea, surf,
  doors, campfire, tavern, lighthouse with a beam that casts no shadow, weather, tides)
- Six shore locations + two portal destinations; discovery, tide gating, rumors
- Character creation (4 archetypes, portrait generator, kits), persistent characters
- The Salt-Grave Signal — scripted supernatural-horror adventure with 4 scenes,
  4 permanent endings, rewards, and resume-anywhere state
- AI Game Master over any OpenAI-compatible endpoint (config screen, test button,
  strict JSON contract, hidden-information separation, retry, honest fallback)
- Deterministic rules engine (the Undertow System: 2d6, bands, Vigor/Nerve harm,
  crypto RNG, full dice log) — the model never rolls
- Campaign persistence: SQLite + WAL, append-only event log, FTS5 search,
  export/import, whole-DB backups + restore
- Procedural audio engine (surf, wind, campfire, generative music, SFX) — nothing
  to license; QR/scanner input with allowlist; rate limiting; optional host token

**Milestone 1.5 — The Living Shore Awakens**
- Tide clock with predictable progression; wash-ashore finds (reproducible,
  tide-scheduled, picked up from the dock)
- Living NPC gossip: structured, scoped memories grounded in recorded events —
  Maren and Cardo know different things, and what they know actually happened
- Seven selectable **GM personalities** (Classic Fantasy, Grimdark, Cosmic Horror,
  Noir, Whimsical, Mythic, Custom) that persist per campaign — tone only, never
  rules authority
- Cinematic dice reactions: the engine resolves, the GM narrates the moment
- Storm/rain visuals, richer campfire and tavern atmosphere, calm mode
  (reduced-motion support) and full audio controls

**Milestone 2.0 — Worlds Beyond the Beam**
- **Seeded portal generation**: whisper a seed at the Unstable Door and a
  deterministic, versioned generator produces a named world — locations, NPCs,
  mysteries, a unique relic, and a playable signature scenario. Same seed → same
  world, forever; worlds persist between visits
- Two more handcrafted adventures: **The Umbral Market** (dark fantasy, the
  glassbead economy as currency of hours) and **The Skyless Light** (mystery at
  the lighthouse, with an upgrade-gated best ending)
- Tactical depth: **Risk** (pre-roll), **Push** (1 Vigor, raise the band),
  **Resist** (1 Nerve, halve harm) — engine-owned, AI can't touch costs
- Player-controlled **Omen hand**: draw (1 Nerve) and play held omens under
  strict caps
- **Shore improvements**: earn glassbeads from adventures and builds — six
  upgrades that visibly change the shore (kettle steam, teal lighthouse beam,
  map-wall glow) and mechanically change rest, rumors and endings

**Milestone 3.5 — The Infinite Library**
- Import **PDF, EPUB, DOCX, TXT, Markdown, HTML** and world packs into a
  searchable local library — sources stored verbatim, chunked with
  heading awareness, FTS-indexed, retrieved context-aware during play
- **Campaign Forge**: the model extracts cast, places, plot and secrets in
  bounded windows; the forge drafts an engine-valid world, validates and
  auto-repairs it; you inspect, regenerate sections, and approve — only
  validated drafts install
- **Optional D&D-compatible ruleset** from the CC-BY-4.0 SRD 5.1 alongside
  Undertow (which remains the default): d20 checks with advantage, combat,
  spells, rests, levels 1–5 — deterministic in the engine, never by AI whim
- **Starter adventures**, each a real playable door with recorded licensing:
  *Dracula: The White Ship* (Stoker), *The Rue Morgue Affair* (Poe),
  *The Time Machine* (Wells); private-manuscript flow ready for *Roanoke*
- Worlds adapted from books retrieve source passages for the GM and carry
  hidden GM secrets that never broadcast; multiplayer covers them all

**Milestones 3.0–3.2 — The Shared Shore (multiplayer)**
- **Host a Shared Voyage**: pick a campaign, invite friends with secure,
  revocable links (hashed tokens, expiring), approve or send-away travelers,
  pause/resume/end the session
- Independent characters per player with server-side ownership; reconnects
  restore your wanderer exactly, with event replay and no duplicates
- Real-time sync over Server-Sent Events (durable sequenced events, replay,
  presence, reconnect tickets) — WebSockets not required
- Party travel by unanimous vote; one shared AI Game Master (serialized,
  single authoritative narration; honest offline fallback); turn-order mode
  with timeouts; multiplayer dice with private push/resist windows
- Party chat drawer, consented item trades, glassbead gifts, clue sharing,
  shared shore improvements funded by pooled beads
- Visible party presence on the canvas (colored wanderers, name labels),
  party memories in the Ledger, and tavern gossip that remembers old companies
- Solo play is untouched; every M1/M2.5 save migrates automatically

**Milestone 2.5 — The Echo System**
- **Echoes**: eligible endings offer legacy (items, traits, achievements,
  reputations, portal knowledge); up to two weave into a *new* voyage at
  character creation; each echo weaves once, ever
- **Cross-world consequences**: defined triggers record durable consequences
  that surface in tavern gossip, other worlds' hooks, and the Ledger
- **Foreshadowing**: clue threads (*The Ninth Wave*, *The Wrong Gull*) gather
  clues from adventures, omens and wash-ashore finds — at threshold they pay
  off through the engine (a hidden shore location; a gull companion perk)
- **The Memory Ledger**: a visual journal — world cards, people, mystery
  threads, consequences, echo shelf, and the chronological log
- Evolving NPC relationships with reputation that precedes you across campaigns

Every save from Milestone 1 migrates automatically and losslessly — see
[docs/MIGRATION.md](docs/MIGRATION.md).

See [docs/VERIFICATION.md](docs/VERIFICATION.md) for exactly what was tested,
what passed, and what remains unfinished, and [docs/RULES.md](docs/RULES.md)
for the complete rules reference.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1 — Playable solo foundation | shore, adventures, AI GM, persistence | **done** |
| 1.5 — The Living Shore Awakens | tide clock, gossip, GM personas, cinematic dice | **done** |
| 2.0 — Worlds Beyond the Beam | seeded worlds, 3 adventures, tactics, omen hand, shore building | **done** |
| 2.5 — The Echo System | echoes, cross-world consequences, Memory Ledger, foreshadowing | **done** |
| 3 — Friends multiplayer | sessions, invitations, SSE sync, shared adventures, party legacy | **done** (`docs/MULTIPLAYER.md`, `docs/DEPLOYMENT.md`) |
| 3.5 — Infinite Library | import → forge → play, from any book; D&D-compatible SRD ruleset; starter adventures | **done** (`docs/LIBRARY.md`, `docs/LICENSES.md`) |
| 4 — Public worlds & guest portals | public hosting, moderation, cross-server visits | contract drafted (`docs/MULTIPLAYER.md`) |

## Repository layout

```
server/          Flask app: api, gm engine, rules, ai adapter, db, worldpacks, qr
client/          No-build front end: index.html + css + ES modules (scene, audio, ui…)
worldpacks/      Built-in packs (living_shore) — pure data
tests/           pytest suite (rules, packs, GM flow, AI adapter, HTTP API)
scripts/         mock_gm_server.py, make_qr_cards.py, smoke_test.py
docs/            architecture, providers, world packs, multiplayer, testing, QR
```

## License & content

Code: MIT (see [LICENSE](LICENSE)). All fiction, art and audio in this repository are
original to Saturday Multiverse. World packs are data — read
[docs/WORLDPACKS.md](docs/WORLDPACKS.md) before distributing packs that contain
someone else's worlds, and keep user-supplied material in the user pack area where
it belongs. The reference project that inspired several engineering patterns
(dice auditing, deck cadence, atomic state) is discussed in
[docs/FOXAI_EVALUATION.md](docs/FOXAI_EVALUATION.md); nothing from it was copied.
