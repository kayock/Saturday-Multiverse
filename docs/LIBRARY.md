# The Infinite Library & the Campaign Forge (Milestone 3.5)

Saturday Multiverse is now a universal, AI-powered tabletop platform: import
a book, forge it into an engine-valid world, and open a portal into it —
solo or with friends. The engine remains the only authority; the AI reads,
extracts and proposes, and you approve before anything plays.

## The Infinite Library

**Title screen → The Infinite Library.**

### Import
- Formats: **PDF** (via the optional `pypdf` package), **EPUB**, **DOCX**,
  **TXT**, **Markdown**, **HTML**, and existing **Saturday Multiverse world
  packs** (pack JSON keeps working through the original import endpoint).
- The original file is stored **verbatim** in `userdata/library/<id>.orig`
  and never modified. Only heading-aware passages (≈1,100 characters) are
  indexed into SQLite with full-text search.
- Fields: title, author, source URL, license, attribution, and a
  **private manuscript** flag (see Roanoke below).
- Hostile files are refused or parsed safely: size caps (40 MB upload,
  8 MB extracted), zip-entry caps, no XML entity expansion, and clean
  400 errors instead of crashes.

### Search & retrieval
- The stacks are searchable (FTS5, with a LIKE fallback): type words, get
  passages ranked across the whole library or inside one book.
- During play, adapted worlds retrieve **context-aware passages** for what
  the player is doing (keyword match, or a rotating window when nothing
  matches) and hand them to the Game Master as source context — so a whole
  novel informs play without ever fitting in one prompt. Retrieval never
  breaks a turn.

## The Campaign Forge

**Library → Forge a campaign** (or the Forge button).

The pipeline, in order:
1. **Slice** — the book is read in bounded windows (up to 6 × 12 passages).
2. **Extract** — one model call per window: cast, places, factions,
   events, items, plot beats, and secrets the GM should hold. Only what
   the excerpt supports; every call is visible in the draft's notes.
3. **Synthesize** — two model calls draft the world and the adventure in
   the exact pack schema (locations, NPCs, items, omens, scenes, choices
   with checks, endings, quests, hidden GM knowledge).
4. **Validate & repair** — deterministic validation of the draft: required
   keys, unique ids, scene gotos resolve, endings return to real places,
   effect keys legal. Common model slips are auto-repaired (ending-gotos
   become ending effects, NPCs re-homed to the hub, endings guaranteed).
5. **Edit** — inspect the cast, scenes and endings; regenerate the world
   or the adventure with editor guidance; read the validation report.
6. **Approve** — only a draft that validates can install. Approved packs
   appear immediately as doors on the shore and in creation.

Modes: **faithful** (the book's events stand; players may still fail or
deviate) and **alternate** (same world, marked [DIVERGENCE] points where
players change the story).

The Forge needs an AI model configured in Settings — it never fakes
content and says so plainly if no model is available.

## Roanoke (private manuscripts)

Eric Z. Fox's *Roanoke* (connected to the *Slipping into Darkness*
universe) is supported through the **private manuscript** flow: import the
actual manuscript with the private flag, forge it privately, play. Private
documents and packs never leave your data directory and carry no source
URL. **No Roanoke content ships with the game** — the manuscript is the
author's private work, and the importer stands ready for it.

## D&D-compatible ruleset (optional)

Campaign creation offers two rulesets:
- **Undertow 2d6** — the original system, untouched and still the default.
- **D&D-compatible (SRD)** — built from the System Reference Document 5.1
  (CC-BY-4.0): classes (fighter/rogue/cleric/wizard), species, backgrounds,
  ability checks with advantage, proficiency, AC/HP, a bounded deterministic
  combat resolver with an open bestiary, a small open spell list with
  slots, long/short rests, and levels 1–5.

The SRD outcomes map onto the engine's five narrative bands, so every
world pack — including forged ones — plays under either ruleset.
Licensing: see `docs/LICENSES.md`. Literature creatures (vampire spawn,
Morlocks, the great ape) use stat blocks derived from the public-domain
novels, deliberately kept separate from SRD content.

## Multiplayer

Everything works with the existing Shared Shore infrastructure: host a
library pack, invite friends, party travel by vote, per-player characters,
trades, chat, dice — including D&D campaigns. Hidden GM secrets ship with
forged packs and are stored as hidden facts; they are never broadcast.
