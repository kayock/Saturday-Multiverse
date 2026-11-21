# Evaluation of the FOXAI_ reference (`FOXAI_NECROSCOPE_CAMPAIGN_ROOM_V1`)

Saturday Multiverse was built after studying
`https://github.com/kayock/FOXAI_` (folder `FOXAI_NECROSCOPE_CAMPAIGN_ROOM_V1`).
Nothing was copied from it — no code, no text, no data. This document records what
was learned, what was adapted, and what was deliberately redesigned or avoided.
The reference repo carries a placeholder personal license and ties into copyrighted
Necroscope/West End Games material; it must stay reference-only.

## Adapted (good ideas, reimplemented from scratch)

1. **Server-authoritative dice with a full audit trail.** The reference rolls 2d10 in
   Python with a crypto RNG and logs every roll; the LLM never rolls. Saturday
   Multiverse keeps the principle (crypto RNG, `dicelog` + `events` append-only log)
   with an original resolution system (see below).
2. **Localhost-first, dependency-light server.** One process, one port, browser
   client, graceful health-check gating of the model endpoint with readable errors.
3. **Agent-managed story deck.** A hidden deck drawn on a cadence, tag-matched edges,
   original cards only, every draw logged, with an off switch. Shipped here as the
   **Omen Deck** (24 original cards; edges grant a +1, complications a −1, turns are
   atmosphere) as world-pack data.
4. **State hygiene.** Schema/version fields, atomic file writes, append-only event
   sourcing, archive-before-delete. Adapted into SQLite WAL + the `events` table +
   versioned exports; JSONL files became tables.
5. **Quick-start characters as data** — here, archetype templates live in the pack,
   not in code.
6. **Structured GM prompt with player-agency rules and content boundaries**, and a
   strict separation between what the model proposes and what the app decides.

## Redesigned

1. **The resolution table.** The reference implements the West End Games MasterBook
   *Bonus Number chart* — recovered rulebook expression, which must not be
   redistributed. Saturday Multiverse uses an original design, the **Undertow
   System**: 2d6 + stat/skill modifiers, graded bands (Undertow ≤6, Riptide 7–9,
   Clean 10–11, Surge 12+, double-6 Kicker, double-1 Wipeout), "hard" checks shift a
   band. Same spirit (graded outcomes feed narration), entirely original numbers.
2. **Source search.** The reference loads every indexed page into memory and scores by
   substring counts — it does not use the FTS5 table its own indexer builds. Here,
   campaign history is searchable via SQLite **FTS5** (`bm25` ranked) with a LIKE
   fallback.
3. **Memory.** The reference keeps only the last 8 messages. Here, continuity adds a
   `facts` table (visible/hidden scopes, importance), quest and NPC-relationship
   tables, scene resumption ("the door remembers you"), and session transcripts.
4. **Polling.** The reference polls full state every 10 s. Milestone 1 refreshes views
   on demand; the event-stream design for Milestone 3 is in `docs/MULTIPLAYER.md`.

## Avoided (hard requirements)

- **No Lumley/Necroscope proper nouns or concepts** (Necroscope, E-Branch,
  Deadspeak/Deadspeaker, Wamphyri, and role concepts tied to that setting).
- **No rulebook text, no exported rules packets, no indexed page snippets** from the
  copyrighted PDF pipeline. The reference repo contains none of that text in git, and
  none of it belongs in a distributable game.
- **No personal data** (operator names, campaign names, private notes, transcripts).
- **No reuse of the reference license** (a personal placeholder). Saturday Multiverse
  ships under MIT with fully original content.

## What the reference got right that this project honors

The strongest engineering lesson was the honesty boundary: dice, state and outcomes in
application code; the model confined to narration and *proposals*; every mechanical
change logged. Saturday Multiverse generalizes it into an effects choke-point
(`gm.apply_effects`) used by the AI path, scripted choices, items and QR events alike,
so campaign continuity stays deterministic no matter where a change comes from.
