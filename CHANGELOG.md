# Changelog

## 0.3.6 maintenance hotfix (2026-11-21)

- **Startup:** `python -m server.app`, `run.sh`, and `run.bat` now call the existing `main()` launcher; no undefined `app`, `HOST`, or `PORT` references. Both standard Flask and optional Waitress serving paths start the watchdog.
- **Watchdog:** multiplayer and combat timeout sweeps now resolve their modules correctly; exceptions are logged rather than silently swallowed. Forge queue scheduling remains in-process.
- **Workshop privacy:** a proposal touching GM secrets now redacts the actual returned `ops` and `note` for other collaborators, including nested secret paths and mixed public/private proposals. Unattributed GM secrets remain creator-only unless explicitly marked shared.
- **Regression coverage:** added `tests/test_release_fixes.py`. The full Flask-dependent suite must be rerun in a proper application environment before deployment; see `docs/VERIFICATION.md`.


## 0.3.6-living-campaign (2026-11-21)

### Critical D&D repairs
- Encounters are now persistent and player-controlled (new `server/combat.py`):
  initiative order, per-turn player actions, engine-resolved enemy turns,
  conditions with durations, concentration saves, death saving throws,
  stabilization and retreat. Pack `dnd_encounter` effects start a live
  encounter instead of an automatic multi-round roll.
- HP persists across encounters: an encounter starts from CURRENT sheet HP,
  not `hp_max`. The old auto-resolver's downed→resurrected logic is removed;
  death saves, stabilisation and death are engine-authoritative.
- Victory rewards (XP, levels) are granted exactly once per encounter.
- Rules expansion on SRD 5.1: barbarian, ranger, paladin, bard, monk, druid;
  gnome, half-orc (relentless endurance), tiefling, dragonborn (breath weapon);
  thunderwave, bless, shield of faith, hold person, fireball; class saving
  throws; `encounter_difficulty()` from SRD XP thresholds; a published
  coverage table (`/api/rules/dnd/coverage`) listing supported vs
  deliberately-unsupported material. Fixed: spell slots read from JSON
  storage (string keys) so casters restored from the database can cast again.

### Multiplayer completion
- Party splitting: per-character locations, location-scoped narration events,
  regrouping (individual or host-forced); shared travel still moves the whole
  party by default.
- Spectators: read-only observers via a dedicated invite; they can watch and
  reconnect but never act, roll, trade or travel.
- Shared D&D combat: initiative across participants, per-player turn actions
  with ownership enforcement, reinforcements in round one.
- Server-side watchdog (in-process daemon thread): expired structured-mode
  turns auto-advance; idle combat turns are auto-defended; both sweeps are
  idempotent and timestamp-driven, surviving restarts.
- Fixed: `/mp/reconnect` now honours the body token for clients that lost
  their session state.

### Infinite Library — full-book conversions
- Conversion jobs (`server/forge.py`): queued/running/failed states persisted
  in the database, resumable at stage granularity, retry/cancel, background
  worker thread, duplicate-job guard per document.
- Hierarchical pipeline: structure → extraction over the ENTIRE document
  (windows of 24 chunks, every chunk processed) → deterministic consolidation
  (alias merge, chronology, contradiction capture) → world bible (canonical
  facts, secrets, relationships, timeline, the source's ENDING) → campaign
  generation → validation → review → approval.
- Coverage metrics per job: chunks processed vs total, chapters, windows,
  model calls, errors — shown in the UI.
- Manual editing: deterministic path ops (set/add/update/remove) on drafts,
  every save recorded as a revision; history, compare, restore, duplicate,
  export; flow validator (unreachable scenes, broken ending paths, deadlocks,
  unknown items/effects) with an SVG flow graph in the editor.
- Faithful Adaptation vs Rewrite the Legend are first-class modes affecting
  generation prompts and gameplay narration.
- Safe retrieval: gameplay prompts no longer fall back to rotating windows;
  context-sensitive retrieval only, with a story-horizon guard against
  surfacing future revelations.

### The Living Campaign Director
- `server/director.py`: quests/mysteries/threats/consequences tracked from
  AUTHORITATIVE events with evidence; optional pacing suggestions (off /
  gentle / active, default gentle); suggestions are advisory lines to the GM —
  never forced, never auto-applied.
- `server/continuity.py`: deterministic checks — dead characters named in
  later narration, duplicated inventory rows, quest states reversed after
  completion, one-time encounters repeated, visibility conflicts — reported
  as advisory flags in the Director panel.

### Collaborative worldbuilding (steering addition)
- The Worldbuilding Workshop: original worlds on the same universal Forge
  (no separate homebrew system), created from scratch or seeded from an
  existing campaign.
- Contribution model: collaborators propose deterministic edits through their
  existing multiplayer identity; the creator reviews, applies or rejects.
- Conflict handling: conflicts are recomputed at review time; conflicting
  proposals are refused unless the creator explicitly forces them — nothing
  is silently overwritten.
- AI assistance: per-kind suggestions (npc/location/quest/dialogue/encounter/
  lore/branch) returned to the requester only, never applied automatically;
  offline template fallback clearly marked.
- Spoiler boundaries: GM secrets carry authoritative authorship; a
  contributor's view filters everyone else's hidden material, including
  proposal contents.
- Approval: creator-only, gated by the same `validate_pack` + flow checks as
  every literary adaptation; installation is local (userdata) — imported or
  private sources are never published automatically, and no publishing
  pipeline exists at all.

### Persistence & saves
- Schema v5 (`saturday.core.v5`): encounter, job, revision, contribution,
  director-thread and checkpoint tables; migration chain v1→v5 verified.
- Campaign checkpoints: snapshot + restore-as-new-campaign (no automatic
  rollback of shared state, no reward duplication).
- Fixed: retried `once`-flagged effects no longer double-grant rewards.

### Tests
- 159 tests green, including the mandatory v0.3.6 suite (persistent HP across
  encounters, death without resurrection, player-controlled turns, timeout
  sweeps, restart survival, split-party knowledge boundaries, spectator
  filtering, turn watchdog, full-novel coverage, resumable jobs, duplicate
  entity resolution, manual editing/versioning, flow validation, private
  content separation, safe retrieval, Director tracking, continuity flags,
  checkpoint restore, migration, restart persistence) and two acceptance
  scenarios: the eight-phase Dracula voyage (four genuine API clients +
  spectator + reconnect + ending + ledger) and the three-participant
  collaborative worldbuilding build (conflicts, secrets, install, play).


## 0.3.5-infinite-library (2026-11-21)

### The Infinite Library
- Document import for PDF (pypdf), EPUB, DOCX, TXT, Markdown, HTML and
  world packs; sources stored verbatim; heading-aware chunking; SQLite
  FTS5 index with LIKE fallback; hostile-file guards (size caps, zip
  caps, no entity expansion)
- Context-aware retrieval during play: adapted worlds feed the GM the
  most relevant passages for the current action
- Library browser with search, import screen with status/error reporting,
  adventure preview with cast, places, story shape and licensing

### The Campaign Forge
- Bounded extraction windows → profile → two synthesis calls → engine-valid
  pack draft; deterministic validation + auto-repair (ids, gotos, endings,
  hubs); editor with per-section regeneration and notes; approve installs
  the pack as a shore door instantly
- Faithful and alternate-story modes; hidden GM secrets carried into the
  hidden-facts store; library context available to the GM without
  exposing secrets to players

### D&D-compatible ruleset (optional, alongside Undertow)
- SRD 5.1 (CC-BY-4.0) derived: 4 classes, 4 species, 4 backgrounds, d20
  checks with advantage/lucky, proficiency, AC/HP, bounded deterministic
  combat with an open bestiary + literature-derived stat blocks, an open
  spell list with slots, long/short rests, XP levels 1–5
- Outcomes mapped onto the engine's five bands: every pack plays under
  either ruleset; Undertow untouched (omens/push/resist intact)

### Starter adventures (public-domain sources, licensed and attributed)
- Dracula: The White Ship — gothic horror, 6 locations, 6 scenes, 3 endings
- The Rue Morgue Affair — detective mystery, 5 locations, 4 scenes, 3 endings
- The Time Machine: Beyond the Seventh Day — sci-fi exploration, 6
  locations, 6 scenes, 3 endings
- Roanoke: private-manuscript import flow prepared; nothing fabricated or
  distributed

### Engine & platform
- Schema v4: library_docs/library_chunks(+FTS)/forge_drafts,
  campaigns.ruleset; additive migration v3→v4 (and the full v1→v4 chain)
- gm_secrets → hidden facts at campaign creation; library retrieval wired
  into the GM prompt; D&D routing for checks, rests, encounters, omens
  skipped under dnd5e
- 21 new tests (131 total): all import formats, long-document retrieval,
  forge pipeline incl. refusal of invalid packs, ruleset determinism and
  isolation, starter-pack playability to endings, hidden-info boundaries,
  multiplayer aboard imported adventures, hostile inputs, migration

## 0.3.2-shared-shore (2026-11-21)

### Milestone 3.0 — Multiplayer foundation
- Host a Shared Voyage: sessions, hashed invitation tokens (expiring,
  revocable, use-limited), player limits, approval mode, lobby with
  portraits/readiness/invite links, remove/ban.
- Player identity: independent characters per player (schema v3 rebuilds
  away the one-character-per-campaign constraint), server-side ownership
  on every endpoint, reconnect without duplication.
- Real-time sync: durable sequenced `mp_events`, SSE stream with one-time
  tickets, replay from `last_seq`, presence heartbeat + offline sweep,
  snapshot+replay reconciliation.

### Milestone 3.1 — Shared adventures
- Party travel by proposal and unanimous vote (host may move directly);
  declines cancel; executes exactly once.
- One shared AI Game Master: host's model serves all players; per-campaign
  action lock serializes actions and narration; honest offline fallback.
- Multiplayer dice: individual checks, risk/push/resist scoped to the
  roller; results announced to the party.
- Turn management: freeform (serialized) and structured turn order with
  timeouts, skipping and host pass-lantern.
- Shared/private information boundaries: hidden facts never broadcast;
  per-character purses, packs, omens and deaths.

### Milestone 3.2 — The living multiplayer shore
- Visible party presence on the Living Shore canvas (colored markers,
  name labels, idle motion; calm-mode aware).
- Party chat drawer: players, GM narration, dice, system events; rate
  limited, escaped, durable history.
- Player-to-player interactions: consented item trades (atomic, split/merge
  aware), glassbead gifts, clue sharing.
- Shared shore improvements: bead contributions with escrowed pot and
  exactly-once purchase.
- Party legacy: company moments recorded on shared endings; party section
  in the Memory Ledger; tavern gossip remembers former parties.
- Reconnection: session tokens persist per campaign; catch-up replay;
  pause/resume/end; process-restart recovery.

### Infrastructure
- Schema v3: mp_sessions/mp_players/mp_invites/mp_events; per-character
  state migration (beads, death, pending rolls, omen decks); inventory
  ownership; clue sharing flag.
- Production serving option (waitress; SATURDAY_PRODUCTION=1) and full
  deployment/security documentation.
- Tests: 81 → 110, including a multi-client harness (independent tokens,
  real HTTP concurrency), security isolation, replay, restart recovery and
  hostile-input handling.

## 0.2.5-living-multiverse (2026-11-21)
## 0.2.5-living-multiverse (2026-11-21)

### Milestone 1.5 — The Living Shore Awakens
- Tide clock (HUD dial + beats-to-change) with predictable 12-beat progression.
- Wash-ashore finds: reproducible, tide-scheduled, picked up from the dock;
  items, glassbeads and clue threads wash in.
- NPC structured memories + scoped gossip (Talk at the camp and tavern);
  grounded in recorded events; AI enrichment with honest offline voice.
- Seven GM personalities (Classic/Grimdark/Cosmic/Noir/Whimsical/Mythic/Custom),
  persistent per campaign — tone only, never rules authority.
- Cinematic dice reactions: engine resolves, GM narrates the moment only.
- Storm/rain presentation, richer campfire/tavern/lighthouse atmosphere,
  calm mode (reduced motion), three-bus audio controls.

### Milestone 2.0 — Worlds Beyond the Beam
- Seeded portal generation at the Unstable Door: deterministic, versioned
  (living-multiverse.gen.v1); six world archetypes; persistent worlds with
  visits, flags and signature scenarios that resume mid-beat.
- Two new handcrafted adventures: The Umbral Market (dark fantasy, glassbead
  economy) and The Skyless Light (lighthouse mystery, upgrade-gated ending).
- Tactical mechanics: Risk (pre-roll +2, failures hurt more), Push (1 Vigor,
  raise the band), Resist (1 Nerve, halve harm) — all engine-owned.
- Player omen hand: draw for 1 Nerve (2 per rest, 2 held), play edges/turns;
  complications play themselves.
- Shore improvements: glassbead economy + six builds with visible effects
  (kettle, guestbook, map wall, hammock, relamped teal beam, lens array).

### Milestone 2.5 — The Echo System
- Echoes: endings offer legacy (items/traits/achievements/reputations/portals);
  profile-level; up to two woven into a new voyage; single-use enforcement.
- Cross-world consequences registered on defined triggers, surfaced in
  tavern gossip and the Ledger.
- Foreshadowing clue threads with engine payoffs (The Ninth Wave unlocks a
  hidden shore location; The Wrong Gull becomes a companion perk).
- The Memory Ledger: visual journal — worlds, people, threads, consequences,
  echoes, tavern memories, chronological log.
- Death/retirement concludes a wanderer and leaves a Remembrance echo.

### Infrastructure
- Schema v2 additive migration (six new tables) — Milestone 1 saves migrate
  losslessly and stay playable; newer-schema databases are refused loudly.
- New HTTP endpoints: style, talk, washashore, push/resist, pending accept,
  omen hand draw/play, upgrades list/buy, worlds generate/list, seeds
  suggest, echoes list, ledger.
- Versioned asset URLs (?v=NN) to prevent stale client modules on upgrade.
- Tests: 50 → 81 (migrations, generator, tactics, omens, upgrades, echoes,
  consequences, gossip, ledger, HTTP).

## 0.1.0-milestone1 (2026-11-21)

- Playable solo foundation: Living Shore hub, six locations + two portal
  destinations, The Salt-Grave Signal adventure with four endings.
- AI Game Master over any OpenAI-compatible endpoint; honest Offline
  Storyteller fallback.
- The Undertow System dice (app-authoritative), Omen Deck, Vigor/Nerve.
- SQLite persistence: campaigns, journal, quests, facts (visible/hidden),
  transcripts, dice log, event log, FTS5 search, export/import, backups.
- Procedural WebAudio soundscape; QR/scanner input with strict allowlist.
- 50 pytest tests; browser-verified flows.
