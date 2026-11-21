# Changelog

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
