# Milestone verification report — The Infinite Library (3.5)

Build under verification: `0.3.5-infinite-library`, schema `saturday.core.v4`.
Previous milestones' verification (1.5–3.2) remains valid and its suites
are included in the totals below. This report distinguishes **executed**
verification from what could not be run here.

## 1. Automated tests — executed, all passing

`python -m pytest tests/ -q` → **131 tests, 0 failures**
(110 from Milestones 1–3.2 + 21 new for 3.5, including 3 parametrized
starter-pack playthroughs), plus the solo smoke walk passing.

| Area (all executed) | Tests |
|---|---|
| Import of every format — TXT/MD, HTML, DOCX (headings preserved), EPUB (metadata into the record), PDF (reportlab-generated fixture via pypdf) | 1 |
| Source verbatim storage + library delete removes the original | 1 |
| Long-document retrieval: 300-chapter book; the "chapter 217" needle surfaces; rotating-window fallback | 1 |
| Hostile inputs: fake DOCX (not a zip), XXE-entity DOCX, 41 MB upload, garbage base64 — refused or handled, never 500 | 1 |
| Hidden GM secrets from packs become hidden facts, absent from views/streams | 1 |
| Forge pipeline end-to-end with a mock model: extract → synthesize → validate CLEAN → approve → installed pack loads in the engine → the story plays headless to an ending | 1 |
| Forge alternate mode + section regeneration keeps packs valid | 1 |
| Forge refuses to approve a sabotaged draft (validation blocks) | 1 |
| Forge requires a configured model and says so honestly | 1 |
| Private-manuscript flow (Roanoke path): private flag, stored under userdata, host-only visibility | 1 |
| D&D character creation on a library pack; d20 checks; band mapping (nat20/nat1/DC bands) | 1 |
| D&D long rest restores slots + HP; XP → level 2 | 1 |
| Ruleset isolation: Undertow unchanged (omens, views, dnd=None) | 1 |
| Starter packs play to endings: Dracula (beacon), Rue Morgue (exoneration), Time Machine (home) | 3 |
| Starter-pack licensing: author, public-domain status, Gutenberg source URL embedded | 1 |
| Hidden-information boundary on a library pack: secrets absent from events and views | 1 |
| Multiplayer aboard an imported adventure: two clients, serialized actions, chat, party travel by vote | 1 |
| Multiplayer join into a D&D campaign: both sheets correct | 1 |
| v4 migration preserves campaigns and the library tables work | 1 |
| Prior-milestone suites (solo, multiplayer, migrations, security) | unchanged, all passing |

## 2. Live end-to-end gameplay — executed

- **Imported literary adventure, engine-only**: each starter pack was
  created as a campaign and walked choice-by-choice to a real ending
  (sunrise in Whitby, exoneration in Paris, home in 802,701) in the
  parameterized tests above — genuine mechanical playthroughs, not demos.
- **Multiplayer + library pack**: a hosted *Dracula* session with two
  independent clients acting, chatting, and traveling by vote.
- **D&D on a literary pack**: a cleric created directly on *Dracula*,
  d20 checks, long rest at the sanatorium restoring spell slots.
- **Forge with a live model**: NOT run here — the sandbox has no live
  LLM configured. The pipeline was verified with a deterministic mock
  model through every stage, including the honest no-model refusal.
  Live-model verification follows the same contract as the mock (JSON
  contracts, bounded calls) but is explicitly **not claimed**.

## 3. Browser verification — executed (Chromium)

- Title screen shows **The Infinite Library**; the Library screen lists
  installed adventures (starter packs) and the stacks.
- The adventure preview shows places, cast, story shape, and the
  licensing block with source URL.
- Campaign creation offers the **pack picker** (every installed adventure
  is a door) and the **ruleset toggle** (Undertow 2d6 / D&D-compatible)
  with class/species/background fields for D&D.

## 4. Not tested in this environment (stated honestly)

- **A live LLM in the Forge/GM**: mock-model verification only; no live
  model was available in the sandbox.
- **A real large PDF/EPUB** (actual Gutenberg downloads): exercised with
  format-accurate generated fixtures instead; Gutenberg URLs are recorded
  but the books were not downloaded in the sandbox.
- **Windows**: Linux only; launchers and waitress production mode written
  for both but not executed on Windows.
- **Roanoke**: no manuscript was supplied; per instructions nothing was
  fabricated — the private-import flow is built and documented.
- Cross-server federation remains out of scope (Milestone 4).

## 5. Acceptance self-check

| Criterion | Status |
|---|---|
| Ordinary user: import a book without editing code | ✅ (Library → Import) |
| Convert it into a playable campaign | ✅ (Forge → approve → door) |
| Open a portal and begin, solo or multiplayer | ✅ (preview → portal → creation; shared sessions verified) |
| Preserve every existing system (solo, multiplayer, Undertow, saves) | ✅ (131 tests incl. all prior suites) |
| Engine authoritative; AI narrates/proposes only | ✅ (forge drafts require human approval; GM never writes state) |
| Save compatibility | ✅ (additive v4 migration, full chain tested) |
| Licensing recorded and separated (SRD vs literature vs private) | ✅ (LICENSES.md + per-pack blocks) |
| Distribution | ✅ `saturday-multiverse-infinite-library-m3.5.zip` |


# v0.3.6 — Living Campaign verification (2026-11-21)

**159 tests green** (`python3 -m pytest tests/ -q`), including 28 new v0.3.6
tests. Two suites run everything from engine rules to full multiplayer
scenarios with real HTTP clients against a real server instance.

## What was verified

### Critical D&D repairs (Part 2 of the assignment)
- HP persistence: damage carries between encounters; the next encounter
  starts from current HP, never `hp_max` (dedicated test + manual runs).
- Player control: initiative order, own-turn-only actions, attack / cast
  (slot consumption) / defend / item / retreat / stabilize all exercised.
- Death without resurrection: death saves, stabilisation, death, and a dead
  character refused re-entry to combat. The old auto-resolver path is gone.
- Rewards exactly once (XP + level-up), including a direct double-finish probe.
- Timeout: an idle turn is auto-defended by the sweep and the turn passes.
- Restart survival: an active encounter is playable from a brand-new app
  instance (process restart), state intact.
- Coverage table served at `/api/rules/dnd/coverage`; unsupported options are
  never offered.

### Multiplayer (Part 3)
- Split party: per-character locations, location-scoped narration (a split
  character's discovery is invisible to the party focus and to spectators),
  regroup (self and host-forced), shared travel regroups by default.
- Spectators: observe only — action/choose/check/travel refused (400/403);
  reconnect works; secrets never appear in their event stream.
- Shared combat: turn-by-turn multi-player control, forged ownership refused
  (403), reinforcements round one.
- Watchdog: expired structured turns advance server-side; combat idle turns
  auto-defend; both survive restart.
- Duplicate actions: `once`-flagged effects re-applied do not double-grant.

### Infinite Library (Part 4)
- Full-novel coverage: a 300-chapter source processed 300/300 chunks across
  13 windows; early/middle/late material all extracted; the world bible
  records the source's ending; flow validation clean; installed and playable.
- Resumable jobs: a failed bible stage preserves the extraction; retry
  resumes with ≤3 model calls instead of re-reading the book.
- Duplicate characters (name/alias/case variants) merge deterministically.
- Manual editing: ops apply, every save is a revision, restore returns the
  earlier state, compare reports changes; broken flow graphs are detected
  (missing targets, unreachable scenes, no reachable ending).
- Safe retrieval: matching context returns the needle chapter; no-match
  context returns NOTHING (the rotating-window fallback is gone); a story
  horizon blocks future chapters.
- Private content: private imports stay in `userdata/library`, never in the
  redistributable packs.

### Director & continuity (Part 5)
- Threads seeded from quests/secrets move only on authoritative events, with
  evidence; suggestions are advisory and silenced in `off` mode; continuity
  catches dead-then-speaking and quest reversals.

### Collaborative worldbuilding (steering addition)
- Three participants (locations / NPCs / quests) on existing multiplayer
  identities; creator reviews and applies; a review-time conflict is refused
  until explicitly force-applied, and BOTH contributions survive (nothing
  silently overwritten); AI suggestions never auto-apply; a contributor sees
  their own GM secret while another contributor does not; approval is
  creator-only and gated; the installed world appears as a playable pack and
  hosts a multiplayer voyage; contributions persist across a restart; private
  sources stay private and no publishing path exists.

### The Dracula acceptance scenario (phases 1–8)
Four genuine independent API clients (plus a fifth spectator connection) run
the whole mandated scenario: arrival with four owned sheets → split party
with private discoveries → Director tracking → regroup → tactical D&D combat
with individual control and ownership enforcement → spectator observation
with secret filtering → disconnect/reconnect with watchdog recovery and no
duplicated characters → ending path, ledger, memories, checkpoint.

**Reported limitation:** the sandbox has no graphical desktop, so the four
clients are real HTTP/API clients through the production server rather than
four browser windows. Every engine path, permission boundary and persistence
effect they exercise is the same one the browser uses.

## Environment limitations, reported honestly
1. **No live AI model** in this environment. Model-dependent stages (GM
   narration, forge extraction/bible/adventure, suggestions) are verified
   against a deterministic mock bound to the same JSON contracts the real
   client uses; the offline storyteller keeps everything playable without a
   model.
2. **Project Gutenberg was down for maintenance** during the build (all
   mirrors tried: gutenberg.org, files, aleph, uwaterloo — maintenance page
   or 404). The real-book pipeline was therefore verified at novel scale with
   a generated 300-chapter source plus the user-supplied-file import path;
   the attempt is reproducible with `scripts/` once Gutenberg returns, or
   immediately with any local .txt/.md/.pdf/.epub via Library → Import.
3. The four-client acceptance uses API clients (see above), not four
   graphical sessions.


## Independent maintenance review — v0.3.6 startup / Workshop patch

This additional source-level review follows the original release report and does **not** replace its 159-test claim.

Two defects in the shipped code were corrected:

1. `server.app` previously called an undefined module-scope `app.run(host=HOST, port=PORT)` in `__main__`, bypassing `main()` and breaking both normal launch scripts. The patched entrypoint uses `main()` in both serving modes and starts the in-process watchdog before the server blocks.
2. `forge.collab_view()` previously redacted `ops_json` for secret-containing proposals but still exposed the original parsed `ops`. The patched view redacts the returned operations and note for other contributors; nested secret paths are covered and creator/author visibility is retained.

Regression tests added to `tests/test_release_fixes.py`. In the independent review environment, two Workshop privacy tests passed. Three Flask-dependent tests were skipped because Flask was not installed; an isolated startup/watchdog smoke test using stub server interfaces confirmed `main()` calls the watchdog in both development and production modes and the tick calls both timeout sweepers. Python source compilation also passed. This is **not** a substitute for a real Flask/Waitress launch and the full 159+ test suite in a proper runtime, which remain unverified in this environment.
