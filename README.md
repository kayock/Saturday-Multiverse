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

## What is implemented (Milestone 1)

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
- Agent-managed **Omen Deck** (24 original cards, drawn every third turn)
- Campaign persistence: SQLite + WAL, atomic-ish writes, append-only event log,
  FTS5 search over journal/transcript/facts, export/import, whole-DB backups + restore
- Procedural audio engine (surf, wind, campfire, generative music, SFX) with
  three independent volume buses — no audio files, nothing to license
- QR/scanner input with allowlist; rate limiting; optional host token
- 50 pytest tests including a full AI turn against a mock model server

See [docs/TESTING.md](docs/TESTING.md) for the honest list of what was tested,
what works, and what is deliberately not finished.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 1 — Playable solo foundation | this release | **done** |
| 2 — World system | pack installer, universe-specific mechanics, document imports, better companions | architecture ready (`docs/WORLDPACKS.md`) |
| 3 — Friends multiplayer | self-hosted sessions, invitations, sync, host-controlled AI | schema + API contract in place (`docs/MULTIPLAYER.md`) |
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
