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

### v0.4.0-hotfix5 — Final Release Hotfix (newest)

- **Recaps remember only what a character genuinely knows.** The recap now
  uses the same specific-memory entitlement as the campfire sharing engine:
  visiting a place once no longer discloses rumors recorded there later —
  return and hear them (or receive them at the fire) and they appear.
- **NPCs keep their secrets.** What an NPC knows internally is now
  separated from what they may say: GM-only, hidden and deep records never
  enter dialogue, AI prompts, conversation responses, transcripts or game
  events, and are never recorded as learned. Only information the
  conversation actually speaks is disclosed, acquired and shown.
- **AI dialogue stays grounded and safe:** the model sees only permitted
  candidates and may only declare disclosure of those; forged or restricted
  ids are dropped. Scripted revelations remain possible through an explicit
  engine-authorized story event (`experience.reveal_memory`).
- **310 tests pass** (285 + 25 new regressions), all four browser flows
  pass, and 91 live LAN checks pass over real HTTP/HTTPS — see
  [docs/VERIFICATION.md](docs/VERIFICATION.md).

### v0.4.0-hotfix4 — Final Release Hotfix

- **The campfire picker is properly authorized.** A missing, invalid,
  banned or wrong-campaign multiplayer token can no longer read another
  character's shareable knowledge: failed authorization is answered with
  403 and never falls back to the campaign's main character. Solo play
  needs no token — access is decided by the campaign's actual session
  state. No new accounts, tokens or login screens.
- **You can only share what you actually heard.** Sharing a rumor now
  requires a specific record that YOUR character learned that exact memory
  (recorded by the engine when a conversation delivers it, when you arrive
  on the shore, when a visitor tale is told at your rest, or when a party
  member shares it at the fire). Having once been at the tavern no longer
  makes every future tavern rumor yours to tell — leave, and the newer
  rumors stay private until you return and hear them.
- The picker and the sharing engine enforce the same rule; forged or
  cross-campaign memory ids are refused and write nothing; GM secrets stay
  unshareable; every grant keeps its auditable ledger record.
- **285 tests pass** (260 + 25 new regressions), all four browser flows
  pass, and 62 live LAN checks pass over real HTTP/HTTPS — see
  [docs/VERIFICATION.md](docs/VERIFICATION.md).

### v0.4.0-hotfix3 — Final Release Hotfix

- **Campfire stories share nothing by default.** Telling a tale no longer
  blanket-shares the teller's whole knowledge scope with the party. When
  you WANT to share, pick specific discoveries, places or individual
  rumors in the campfire form (the engine validates every selection — you
  can only share what your character genuinely knows, and GM-only secrets
  can never be shared). Sharing one tavern rumor does not unlock future
  tavern rumors; what was already recorded at share time stays readable;
  anything newer waits until it is heard in person or shared too.
- **Recaps survive crowds of secrets.** Hidden and unauthorized NPC
  memories can no longer crowd an authorized rumor out of the recap: the
  eligibility filter now runs before the 8-item display window, with a
  bounded retrieval walk. Per-player dismissal markers are unchanged.
- **HTTPS demands real identities.** Strict validation now uses the actual
  Subject Alternative Name extension only — a Common Name is never a
  substitute; an IP address must be covered by a real `IPAddress` SAN; and
  certificates whose validity has not begun yet (or has expired, is
  unreadable, or mismatches the key) are refused at startup, compared
  exactly in UTC.
- **The CI matrix can actually run the suite on Windows.** The TLS test
  helper no longer imports Unix-only `fcntl` (portable background output
  collection instead), `requirements-dev.txt` installs the TLS test
  dependency (`cryptography` — still optional for players), and the browser
  job runs its four real flows. 260 tests pass (228 + 32 new regressions);
  see [docs/VERIFICATION.md](docs/VERIFICATION.md).

### v0.4.0-hotfix2 — Final Release Hotfix

- **Recaps are player-aware.** Your recap reflects what YOUR character has
  seen, visited and been told: place-scoped shore gossip reaches only the
  characters who were there, discoveries belong to their discoverer, and the
  campfire story you tell shares your knowledge with the whole party.
  Spectators see public events and shared tales only.
- **Per-player recap dismissal.** Each player's "seen" markers are their own
  (SQLite): dismissing your recap never clears another player's unseen
  events, and your markers survive disconnects and restarts. Old saves
  migrate safely and conservatively.
- **Production HTTPS tells the truth.** With `SATURDAY_PRODUCTION=1
  SATURDAY_TLS=1`, the banner and `/api/health` state plainly that the port
  serves plain HTTP with TLS at your reverse proxy (set
  `SATURDAY_TLS_PROXY_URL` to display the external HTTPS address), or serve
  real TLS from this process with `SATURDAY_TLS_DEVSERVER=1`.
- **Invalid certificates are rejected, not served.** Expired, missing,
  mismatched or non-covering certificates stop startup with an actionable
  message; coverage is checked against real client-facing names (never the
  0.0.0.0 bind address).

### v0.4.0-hotfix1 — LAN HTTPS & Reliability

- **Recap privacy.** Deep-scoped NPC secrets can no longer appear in a
  returning-player recap; achievements/discoveries are filtered by reliable
  per-table last-seen markers (old saves migrate safely); ongoing objectives
  are distinguished from genuinely new developments.
- **Goal integrity.** Goal mutations are scoped to the supplied campaign
  (cross-campaign mutations rejected); engine-verified progress is separated
  from player-authored progress; personal-goal ownership is enforced for
  multiplayer guests.
- **LAN verified.** Solo and multiplayer play from other devices over
  `SATURDAY_HOST=0.0.0.0` — no lobby needed for solo; SSE reconnection and
  save/resume covered by automated integration tests.
- **Optional LAN HTTPS.** `python scripts/cert_setup.py generate` creates a
  local CA + certificates covering your LAN addresses; `SATURDAY_TLS=1`
  enables encrypted connections; client trust is a manual per-device step
  (Windows/Linux/Android/iOS instructions in docs/DEPLOYMENT.md). HTTP
  behavior is unchanged when HTTPS is off.

### v0.4.0 — The Living Worlds

- **Defect audit & repairs.** Every reported problem from three independent
  reviews was reproduced and verified; six confirmed defects (solo combat
  rejection, spell-slot loss on invalid targets, event-replay starvation,
  stuck Forge jobs, rejected actions advancing the clock, FTS5-less startup
  failure) plus two integrity gaps (spoiler horizon, honest extraction
  coverage) are repaired with failing-first regression tests.
- **The Shore remembers.** Returning players get a recap built from real
  engine events — achievements, open threads, discoveries, NPC memory
  movement — dismissible until something new happens.
- **Expedition goals & Campfire Stories.** Shared and personal goals progress
  through engine-validated events; stories around the fire are explicitly
  player-authored and never mistaken for verified records.
- **Engine Trace.** An optional panel that shows exactly how one turn was
  resolved: the rule, the dice, the difficulty, the validated effects, and the
  narration source.
- **What-If Timelines.** Branch any checkpoint into a new campaign; compare
  endings, fates and inventory across timelines; the original stays untouched.
- **Workshop playtesting.** Launch a draft world into an isolated portal, get
  an actionable report, then return to the editor.
- **Onboarding & accessibility.** A first-night tutorial (with D&D-specific
  notes), reduced-motion and high-contrast modes, visible focus, aria-live
  narration.
- **Reliability.** GitHub Actions CI (Linux/Windows, browser job included),
  `scripts/preflight.py` diagnostics, real startup smoke test, honest
  dependency split, and lease-based job recovery that survives crashes.

### v0.3.6 — The Living Campaign

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
