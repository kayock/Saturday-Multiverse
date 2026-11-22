# Save migration & backup guide

## What changed in the database (v1 → v2)

Milestone 1 saved with schema **`saturday.core.v1`**. The Living Multiverse
expansion opens the same SQLite file and upgrades it to
**`saturday.core.v2`** — automatically, on first launch. The migration is
**additive only**: six new tables are created and every existing row of
every existing table is left untouched.

| New table | Milestone | Purpose |
|---|---|---|
| `worlds` | 2.0 | seeded generated worlds and their persistent state |
| `npc_memories` | 1.5 | structured events NPCs gossip about (scoped) |
| `clues` | 2.5 | foreshadowing clue threads |
| `echoes` | 2.5 | cross-campaign legacy items |
| `upgrades` | 2.0 | purchased shore improvements |
| `consequences` | 2.5 | cross-world consequence records |

The version marker lives in the `meta` table
(`key='schema_version'`). You can check yours:

```bash
sqlite3 userdata/saturday.db "SELECT value FROM meta WHERE key='schema_version';"
```

## What happens to a Milestone 1 save

- Campaigns, characters, inventory, journal, quests, transcripts, dice logs:
  **all preserved verbatim**.
- You can resume a M1 campaign immediately; nothing needs re-creating.
- Verified by `tests/test_migrations.py::test_v1_save_migrates_and_preserves_everything`,
  which builds a real v1-era save, migrates it, and continues playing it.

## Recovery procedures

**Back up before upgrading** (always a good habit):

- In-game: **Settings → Saves & data → Back up database** (a copy is written
  to `userdata/backups/` and restorable from the same panel).
- Or copy the file while the server is stopped:
  `cp userdata/saturday.db userdata/saturday.db.bak`
  (also copy `saturday.db-wal` / `saturday.db-shm` if present).

**Restore a backup**: Settings → Saves & data → the backup list → Restore.
The server swaps the file and reloads.

**Wrong/newer schema refused**: if the database carries a schema marker
*newer* than the running build, the server refuses to touch it (loud error,
no silent downgrade). Restore a matching backup instead.

**Exports**: each campaign can be exported to JSON
(Settings → Export this campaign) and re-imported on any machine — exports
include the full campaign record set.

## Rollback to Milestone 1

A v2 database opened by a Milestone 1 build will simply not find the new
tables' data (it ignores them; M1 code never touches the new tables, and the
`schema_version` marker will read v2, which M1 does not check). Your M1
campaigns remain playable. For a strictly-clean rollback, restore a pre-upgrade
backup.


## v3 → v4 (Milestone 3.5, The Infinite Library)

Adds `campaigns.ruleset` (default `undertow`) and the library/forge tables
(`library_docs`, `library_chunks` + FTS5 index, `forge_drafts`). Purely
additive: every v3 campaign keeps its id, state, party and multiplayer
session. v1 and v2 saves walk the whole chain (v1→v2→v3→v4) in one open —
verified by `tests/test_migrations.py`. New runtime data lives beside the
database: `userdata/library/` (verbatim sources) and
`userdata/worldpacks/` (approved forge packs).


## v5 (0.3.6 — living campaign)

Additive migration from v4 (and from v1/v2/v3 through the existing chain):
- `characters.location_id` (split-party state; NULL = follows the party)
- `mp_players.role` (`player` | `spectator`)
- `dnd_encounters` — persistent player-controlled combat
- `forge_jobs`, `forge_revisions`, `forge_contrib` — conversion jobs, draft
  versioning, collaborative contributions
- `forge_drafts.owner` / `forge_drafts.collab_json` — workshop ownership
- `director_threads` — the Living Campaign Director
- `campaign_checkpoints` — snapshot/restore-as-new

Old saves migrate in place; tests cover v2.5 → v5 with content preserved.

## v8 stays v8 (0.4.0-hotfix3 — explicit campfire sharing)

Schema `saturday.core.v8` is NOT bumped. One new table,
`knowledge_shares` (the auditable campfire-sharing ledger: what was shared,
by whom, when, from which story; `UNIQUE(campaign_id, ref)` so retries are
idempotent), is created by the standard idempotent `CREATE TABLE IF NOT
EXISTS` pass that runs on every open — the same mechanism hotfix2 used for
`recap_seen`. Any save from v1 through hotfix2's v8 opens under this build
with every row intact and gains the table automatically; nothing is
rewritten, no version marker moves, and a rollback to the hotfix2 build
keeps working (the extra table is simply unused there).

**Behavioral migration policy (documented, conservative):** the blanket
party-wide `shared` rows written by the hotfix2 campfire are NOT deleted or
rewritten — no knowledge a party already received is erased, and no
historical sharing event is fabricated. Because those rows carry no evidence
of exactly which facts were communicated, they now authorize only what was
already recorded at their grant timestamp: memories created afterwards stay
private until heard in person or explicitly shared. New sharing always
records a specific, auditable grant.

## v8 stays v8 (0.4.0-hotfix4 — verified character knowledge)

No schema change and no version marker move. Hotfix 4 records WHICH
specific npc_memories a character actually learned as new `kind='memory'`
rows in the existing `char_knowledge` table — a new VALUE, not a new table
or column, so every save from v1 through hotfix3 opens unchanged. Nothing
is deleted or rewritten.

**What old saves get, honestly:** places, discoveries and hearing scopes
are preserved exactly; memories whose delivery was never recorded are NOT
offered as individually verified shareable knowledge — on old saves the
picker offers places, public `all`-scoped news, and any specific
acquisitions the save itself carries (including hotfix3-era party-wide
memory grants, which still count as delivery to the whole party). This is
narrower than hotfix3's scope-based offer by design: the engine no longer
claims a character knows every rumor in a scope they once visited. New
acquisition points (conversations, arrivals, rest-fire tales, campfire
shares) accumulate normally going forward.

## v8 stays v8 (0.4.0-hotfix5 — unified disclosure rules)

Again no schema change and no version marker move. Hotfix 5 changes POLICY,
not structure: recaps and NPC conversations now follow the same
specific-memory entitlement as campfire sharing, and only information an
NPC actually speaks is recorded as learned (`char_knowledge` kind='memory'
rows, written idempotently). Every save from v1 through hotfix4 opens
unchanged; nothing is deleted or rewritten.

**About hotfix-4-era saves (honest limitation):** the hotfix-4 conversation
code recorded every internally-retrieved candidate as learned, so an old
save may hold acquisition rows for memories the character never actually
heard. These cannot be reliably distinguished from legitimate records
(no provenance was stored), so they are left in place rather than risking
legitimate progress. They are largely inert: rows for restricted kinds
(gm/secret/hidden/host) and out-of-whitelist scopes (deep) never surface —
the static rules dominate in the recap, the picker and the sharing engine.
Rows for ordinary rumors may remain re-shareable; treat them as folklore
your party has heard around the fire. Going forward, acquisitions are exact
and disclosure-tracked, and `reveal_memory` is the only sanctioned way
internal knowledge becomes player-facing.
