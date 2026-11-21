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
