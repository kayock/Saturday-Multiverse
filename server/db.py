"""Saturday Multiverse — SQLite persistence layer.

Design rules carried over from the FOXAI reference evaluation:
- every state file/table carries a schema version;
- writes are atomic (temp file + rename for file artifacts);
- an append-only event log records every mechanical change;
- full-text search (FTS5) over journal, transcript and memory facts.

The AI Game Master never writes to this database directly — game code does,
after validating and resolving mechanical outcomes (dice, inventory, flags).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

_CONN: sqlite3.Connection | None = None
_LOCK = threading.RLock()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    global _CONN
    with _LOCK:
        if _CONN is None:
            _CONN = _connect()
        return _CONN


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  character_id TEXT,
  scene_id TEXT,
  location_id TEXT,
  turn INTEGER NOT NULL DEFAULT 0,
  drift INTEGER NOT NULL DEFAULT 0,
  ruleset TEXT NOT NULL DEFAULT 'undertow',   -- undertow | dnd5e (SRD)
  state_json TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  name TEXT NOT NULL,
  archetype TEXT NOT NULL,
  location_id TEXT,
  portrait_json TEXT NOT NULL DEFAULT '{}',
  attributes_json TEXT NOT NULL DEFAULT '{}',
  skills_json TEXT NOT NULL DEFAULT '{}',
  vigor INTEGER NOT NULL DEFAULT 10,
  vigor_max INTEGER NOT NULL DEFAULT 10,
  nerve INTEGER NOT NULL DEFAULT 10,
  nerve_max INTEGER NOT NULL DEFAULT 10,
  data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS inventory (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  character_id TEXT,
  item_id TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'trinket',
  qty INTEGER NOT NULL DEFAULT 1,
  equipped INTEGER NOT NULL DEFAULT 0,
  data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS journal (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'auto',
  text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quests (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  quest_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  notes_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE (campaign_id, quest_id)
);

CREATE TABLE IF NOT EXISTS npcs (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  npc_id TEXT NOT NULL,
  name TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (campaign_id, npc_id)
);

CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  text TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'visible',
  importance INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'gm'
);

CREATE TABLE IF NOT EXISTS transcript (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS dicelog (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'check',
  skill TEXT,
  stat_mod INTEGER NOT NULL DEFAULT 0,
  dice_json TEXT NOT NULL,
  total INTEGER NOT NULL,
  difficulty INTEGER,
  outcome TEXT,
  effect INTEGER NOT NULL DEFAULT 0,
  note TEXT
);

CREATE TABLE IF NOT EXISTS locations_state (
  campaign_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  discovered INTEGER NOT NULL DEFAULT 0,
  data_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (campaign_id, location_id)
);

CREATE TABLE IF NOT EXISTS decks (
  campaign_id TEXT NOT NULL,
  deck_id TEXT NOT NULL,
  draw_json TEXT NOT NULL DEFAULT '[]',
  discard_json TEXT NOT NULL DEFAULT '[]',
  held_json TEXT NOT NULL DEFAULT '[]',
  draws INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (campaign_id, deck_id)
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}'
);

-- Milestone 3 groundwork: multiplayer sessions and invitations.
-- Superseded in Milestone 3.0 by the mp_* tables below (hashed tokens);
-- these legacy tables are kept untouched so old databases open cleanly.
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  player_name TEXT NOT NULL,
  token TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'host',
  permissions_json TEXT NOT NULL DEFAULT '{}',
  joined_at TEXT NOT NULL,
  last_seen TEXT
);

CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  uses_left INTEGER NOT NULL DEFAULT 1,
  permissions_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS backups (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  campaign_id TEXT,
  path TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0
);

-- ==========================================================================
-- Milestones 1.5 / 2.0 / 2.5 (all additive — a Milestone 1 database gains
-- these tables on open and every existing row is preserved untouched).
-- ==========================================================================

-- M2.0: seeded, persistent generated worlds.
CREATE TABLE IF NOT EXISTS worlds (
  id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  seed TEXT NOT NULL,
  seed_hash TEXT NOT NULL,
  generator_version TEXT NOT NULL,
  name TEXT NOT NULL,
  identity_json TEXT NOT NULL DEFAULT '{}',
  state_json TEXT NOT NULL DEFAULT '{}',
  discovered_at TEXT NOT NULL,
  visits INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (campaign_id, id)
);

-- M1.5: structured NPC memories — the ground truth gossip is built from.
CREATE TABLE IF NOT EXISTS npc_memories (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  npc_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'event',
  scope TEXT NOT NULL DEFAULT 'all',
  text TEXT NOT NULL
);

-- M2.5: foreshadowing clue threads.
CREATE TABLE IF NOT EXISTS clues (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'event'
);

-- M2.5: echoes — a profile-level legacy that crosses campaigns.
CREATE TABLE IF NOT EXISTS echoes (
  id TEXT PRIMARY KEY,
  campaign_id TEXT,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  data_json TEXT NOT NULL DEFAULT '{}',
  used_in TEXT
);

-- M2.0: shore improvements (base building, persistent and visible).
CREATE TABLE IF NOT EXISTS upgrades (
  campaign_id TEXT NOT NULL,
  upgrade_id TEXT NOT NULL,
  purchased_at TEXT NOT NULL,
  PRIMARY KEY (campaign_id, upgrade_id)
);

-- M2.5: cross-world consequences, grounded in recorded triggers.
CREATE TABLE IF NOT EXISTS char_knowledge (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  character_id TEXT NOT NULL,                -- character id, or '*party*' for shared
  kind TEXT NOT NULL,                        -- visited|discovery|heard|shared
  ref TEXT NOT NULL,                         -- location id or place scope tag
  ts TEXT NOT NULL,
  UNIQUE (campaign_id, character_id, kind, ref)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_campaign ON char_knowledge (campaign_id, character_id);

-- Hotfix 3: auditable campfire sharing — exactly what was shared with the
-- party, by whom, and when (one row per granted ref; retries are idempotent).
CREATE TABLE IF NOT EXISTS knowledge_shares (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ref TEXT NOT NULL,                         -- place ref, or the shared memory's id
  ref_kind TEXT NOT NULL,                    -- place | memory
  source_kind TEXT NOT NULL,                 -- visited | discovery | memory
  shared_by_player_id TEXT NOT NULL DEFAULT 'local',
  shared_by_character_id TEXT,
  story_id TEXT,                             -- the campfire story that carried it
  ts TEXT NOT NULL,
  UNIQUE (campaign_id, ref)
);
CREATE INDEX IF NOT EXISTS idx_kshares_campaign ON knowledge_shares (campaign_id, ref);

-- Per-player recap last-seen markers: one player's dismissal must never mark
-- another player's unseen events as read. player_id 'local' is the solo /
-- local-console viewer; mp players key their own row. Legacy campaign-wide
-- markers stay in campaigns.state_json and are lazily seeded per player.
CREATE TABLE IF NOT EXISTS recap_seen (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  seen_rowids_json TEXT NOT NULL DEFAULT '{}',
  seen_turn INTEGER NOT NULL DEFAULT 0,
  seen_ts TEXT,
  dismissed_at TEXT,
  UNIQUE (campaign_id, player_id)
);

CREATE TABLE IF NOT EXISTS consequences (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  trigger TEXT NOT NULL,
  summary TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',
  surfaced INTEGER NOT NULL DEFAULT 0
);

-- ==========================================================================
-- Milestone 3: The Shared Shore. Tokens are stored as SHA-256 hashes only —
-- raw tokens exist once, in the join response, and never at rest.
-- ==========================================================================

CREATE TABLE IF NOT EXISTS mp_sessions (
  campaign_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'lobby',      -- lobby | active | paused | ended
  mode TEXT NOT NULL DEFAULT 'freeform',     -- freeform | turns
  player_limit INTEGER NOT NULL DEFAULT 6,
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mp_players (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  character_id TEXT,
  is_host INTEGER NOT NULL DEFAULT 0,
  ready INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'connected',  -- connected | offline | banned | removed
  joined_at TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  data_json TEXT NOT NULL DEFAULT '{}',      -- color, private notes, contributions
  UNIQUE (campaign_id, display_name COLLATE NOCASE)
);

CREATE TABLE IF NOT EXISTS mp_invites (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL DEFAULT '',
  uses_left INTEGER NOT NULL DEFAULT 0,      -- 0 = unlimited until revoked/expired
  expires_at TEXT,
  revoked INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mp_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  actor TEXT,                                 -- player id, or 'gm' / 'system'
  visibility TEXT NOT NULL DEFAULT 'party',   -- party | player:<id> | host
  data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_mp_events_campaign ON mp_events (campaign_id, seq);

-- ==========================================================================
-- Milestone 3.5: The Infinite Library. Source documents stay verbatim on
-- disk (userdata/library/<id>.orig); the database holds metadata + chunks.
-- ==========================================================================

CREATE TABLE IF NOT EXISTS library_docs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT '',
  doc_type TEXT NOT NULL DEFAULT 'txt',       -- txt|md|html|docx|epub|pdf|worldpack
  source_url TEXT NOT NULL DEFAULT '',
  license TEXT NOT NULL DEFAULT 'Private',
  attribution TEXT NOT NULL DEFAULT '',
  file_hash TEXT NOT NULL DEFAULT '',
  original_path TEXT NOT NULL DEFAULT '',
  n_chunks INTEGER NOT NULL DEFAULT 0,
  n_words INTEGER NOT NULL DEFAULT 0,
  private INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS library_chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  heading TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  word_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_library_chunks_doc ON library_chunks (doc_id, seq);

CREATE TABLE IF NOT EXISTS forge_drafts (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,                        -- '' for from-scratch homebrew
  mode TEXT NOT NULL DEFAULT 'faithful',      -- faithful | rewrite | homebrew
  status TEXT NOT NULL DEFAULT 'drafting',    -- drafting | draft | approved
  pack_json TEXT NOT NULL DEFAULT '{}',
  profile_json TEXT NOT NULL DEFAULT '{}',    -- extracted raw material
  notes_json TEXT NOT NULL DEFAULT '[]',
  owner TEXT,                                  -- collaborative worldbuilding creator
  collab_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Milestone 3.6: player-controlled encounters, forge jobs, revisions,
-- the Living Campaign Director, and campaign checkpoints.
CREATE TABLE IF NOT EXISTS dnd_encounters (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',      -- active | complete
  round INTEGER NOT NULL DEFAULT 1,
  turn_index INTEGER NOT NULL DEFAULT 0,
  state_json TEXT NOT NULL DEFAULT '{}',
  rewards_granted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dnd_enc_campaign ON dnd_encounters (campaign_id, status);

CREATE TABLE IF NOT EXISTS forge_jobs (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'faithful',      -- faithful | rewrite
  scope TEXT NOT NULL DEFAULT 'short',        -- short | multi_session | extended
  status TEXT NOT NULL DEFAULT 'queued',      -- queued|running|review|approved|failed|cancelled
  stage TEXT NOT NULL DEFAULT '',             -- human-readable stage line
  progress REAL NOT NULL DEFAULT 0,           -- 0..1
  coverage_json TEXT NOT NULL DEFAULT '{}',
  profile_json TEXT NOT NULL DEFAULT '{}',
  bible_json TEXT NOT NULL DEFAULT '{}',
  pack_json TEXT NOT NULL DEFAULT '{}',
  notes_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  cancel INTEGER NOT NULL DEFAULT 0,
  draft_id TEXT,
  owner TEXT,                                 -- worker lease holder
  heartbeat TEXT,                             -- lease heartbeat (UTC)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_doc ON forge_jobs (doc_id, status);

CREATE TABLE IF NOT EXISTS forge_contrib (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  author_id TEXT NOT NULL,                    -- mp player id or 'local'
  author_name TEXT NOT NULL,
  ops_json TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  base_rev INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'proposed',    -- proposed|applied|rejected
  applied_rev INTEGER,
  conflicts_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forge_contrib_draft ON forge_contrib (draft_id, status);

CREATE TABLE IF NOT EXISTS forge_revisions (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  pack_json TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forge_rev_draft ON forge_revisions (draft_id, seq);

CREATE TABLE IF NOT EXISTS director_threads (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'quest',         -- quest|mystery|threat|arc|faction|consequence
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'introduced',  -- introduced|active|dormant|resolved|failed|abandoned
  detail_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_director_campaign ON director_threads (campaign_id, status);

CREATE TABLE IF NOT EXISTS party_goals (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  target INTEGER NOT NULL DEFAULT 3,
  progress INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',      -- active|complete|abandoned
  scope TEXT NOT NULL DEFAULT 'party',        -- party|personal
  owner_player_id TEXT,
  verified_progress INTEGER NOT NULL DEFAULT 0,  -- engine-credited only
  last_source TEXT NOT NULL DEFAULT 'player',    -- engine|player (last change)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goals_campaign ON party_goals (campaign_id, status);

CREATE TABLE IF NOT EXISTS campfire_stories (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  author_player_id TEXT NOT NULL DEFAULT 'local',
  author_name TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'story',         -- story|memory|memorial|record|goal_idea
  text TEXT NOT NULL,
  related_event_seq INTEGER,                  -- optional link to a VERIFIED event
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campfire_campaign ON campfire_stories (campaign_id, created_at);

CREATE TABLE IF NOT EXISTS campaign_checkpoints (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  name TEXT NOT NULL,
  export_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

_FTS_STATE = {"available": True, "warning": None}


def fts_available() -> bool:
    """True when SQLite full-text search is in use; False when the LIKE
    fallback is active (optional module missing in this build)."""
    return bool(_FTS_STATE["available"])


def fts_warning() -> str | None:
    return _FTS_STATE["warning"]


def _try_fts(conn, script: str, label: str) -> bool:
    """Create an optional FTS5 virtual table; degrade to LIKE search instead
    of failing startup when the build lacks the module."""
    try:
        conn.executescript(script)
        return True
    except Exception as exc:  # noqa: BLE001 — any fts5/lifecycle failure degrades
        _FTS_STATE["available"] = False
        _FTS_STATE["warning"] = (
            f"full-text search unavailable ({str(exc)[:120]}) — {label} uses the LIKE fallback")
        print("[Saturday] " + _FTS_STATE["warning"], flush=True)
        return False


SEARCH_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
  body,
  campaign_id UNINDEXED,
  kind UNINDEXED,
  ref_id UNINDEXED
);
"""


def init_db() -> None:
    """Create/upgrade the schema. Migrations are additive and versioned.

    A Milestone 1 database (schema v1) opens here, gains the new tables, and
    keeps every existing row — verified by tests/test_migrations.py.
    """
    conn = get_conn()
    with _LOCK:
        conn.executescript(SCHEMA_SQL)
        _try_fts(conn, SEARCH_SQL, "campaign search")
        # Infinite Library full-text index (FTS5 when the build supports it)
        _try_fts(conn, """
CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(
  doc_id UNINDEXED, seq UNINDEXED, heading, text
);
""", "library search")
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (config.SCHEMA_VERSION,),
            )
        elif row["value"] != config.SCHEMA_VERSION:
            _migrate(conn, row["value"])
        conn.commit()


def _migrate(conn: sqlite3.Connection, from_version: str) -> None:
    """Forward-only, additive migrations. Never deletes or rewrites rows.

    v1 -> v2: the Milestone 1.5/2.0/2.5 tables (worlds, npc_memories, clues,
    echoes, upgrades, consequences). Every statement is CREATE TABLE IF NOT
    EXISTS, so an untouched v1 save migrates with zero data loss.
    v2 -> v3: The Shared Shore. Characters may now belong to a whole party
    (the one-character-per-campaign UNIQUE is rebuilt away), inventory rows
    gain a character owner, and per-character state (beads, death, pending
    rolls, omen bonuses) moves into the character record so two players never
    share a purse.
    """
    if from_version in ("saturday.core.v1",):
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SEARCH_SQL)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            ("saturday.core.v2",),
        )
        conn.commit()
        from_version = "saturday.core.v2"
    if from_version in ("saturday.core.v2",):
        _migrate_v2_to_v3(conn)
        _migrate_v3_to_v4(conn)
        _migrate_v4_to_v5(conn)
        _migrate_v5_to_v6(conn)
        _migrate_v6_to_v7(conn)
        _migrate_v7_to_v8(conn)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (config.SCHEMA_VERSION,),
        )
        conn.commit()
        return
    if from_version in ("saturday.core.v3",):
        _migrate_v3_to_v4(conn)
        _migrate_v4_to_v5(conn)
        _migrate_v5_to_v6(conn)
        _migrate_v6_to_v7(conn)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (config.SCHEMA_VERSION,),
        )
        conn.commit()
        return
    if from_version in ("saturday.core.v4",):
        _migrate_v4_to_v5(conn)
        _migrate_v5_to_v6(conn)
        _migrate_v6_to_v7(conn)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (config.SCHEMA_VERSION,),
        )
        conn.commit()
        return
    if from_version in ("saturday.core.v5",):
        _migrate_v5_to_v6(conn)
        _migrate_v6_to_v7(conn)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (config.SCHEMA_VERSION,),
        )
        conn.commit()
        return
    if from_version in ("saturday.core.v6",):
        _migrate_v6_to_v7(conn)
        _migrate_v7_to_v8(conn)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (config.SCHEMA_VERSION,),
        )
        conn.commit()
        return
    if from_version in ("saturday.core.v7",):
        _migrate_v7_to_v8(conn)
        conn.execute(
            "UPDATE meta SET value=? WHERE key='schema_version'",
            (config.SCHEMA_VERSION,),
        )
        conn.commit()
        return
    # Unknown or *newer* version: refuse to touch it rather than downgrade.
    raise RuntimeError(
        f"database schema {from_version} is newer than this build "
        f"({config.SCHEMA_VERSION}); restore a matching backup instead"
    )


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Infinite Library migration: ruleset column + library/forge tables."""
    camp_cols = {r[1] for r in conn.execute("PRAGMA table_info(campaigns)")}
    if "ruleset" not in camp_cols:
        conn.execute("ALTER TABLE campaigns ADD COLUMN ruleset TEXT NOT NULL DEFAULT 'undertow'")
    conn.executescript("""
CREATE TABLE IF NOT EXISTS library_docs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT '',
  doc_type TEXT NOT NULL DEFAULT 'txt',
  source_url TEXT NOT NULL DEFAULT '',
  license TEXT NOT NULL DEFAULT 'Private',
  attribution TEXT NOT NULL DEFAULT '',
  file_hash TEXT NOT NULL DEFAULT '',
  original_path TEXT NOT NULL DEFAULT '',
  n_chunks INTEGER NOT NULL DEFAULT 0,
  n_words INTEGER NOT NULL DEFAULT 0,
  private INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  heading TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  word_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_library_chunks_doc ON library_chunks (doc_id, seq);
CREATE TABLE IF NOT EXISTS forge_drafts (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'faithful',
  status TEXT NOT NULL DEFAULT 'drafting',
  pack_json TEXT NOT NULL DEFAULT '{}',
  profile_json TEXT NOT NULL DEFAULT '{}',
  notes_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
""")


def _migrate_v7_to_v8(conn: sqlite3.Connection) -> None:
    """Player-specific recap privacy: per-character knowledge tracking and
    per-player recap last-seen markers. Additive tables only — no rows are
    rewritten, and the legacy campaign-wide markers in campaigns.state_json
    are left in place (they seed each player's marker lazily and conservatively)."""
    conn.execute("""CREATE TABLE IF NOT EXISTS char_knowledge (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  character_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  ref TEXT NOT NULL,
  ts TEXT NOT NULL,
  UNIQUE (campaign_id, character_id, kind, ref)
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_campaign ON char_knowledge (campaign_id, character_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_shares (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  ref TEXT NOT NULL,
  ref_kind TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  shared_by_player_id TEXT NOT NULL DEFAULT 'local',
  shared_by_character_id TEXT,
  story_id TEXT,
  ts TEXT NOT NULL,
  UNIQUE (campaign_id, ref)
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kshares_campaign ON knowledge_shares (campaign_id, ref)")
    conn.execute("""CREATE TABLE IF NOT EXISTS recap_seen (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  player_id TEXT NOT NULL,
  seen_rowids_json TEXT NOT NULL DEFAULT '{}',
  seen_turn INTEGER NOT NULL DEFAULT 0,
  seen_ts TEXT,
  dismissed_at TEXT,
  UNIQUE (campaign_id, player_id)
)""")


def _migrate_v6_to_v7(conn: sqlite3.Connection) -> None:
    """Goal-progress integrity: engine-verified progress is separated from
    player-authored progress so a manual request can never fabricate a
    mechanically validated achievement. Additive columns only."""
    cols = set()
    if "party_goals" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(party_goals)")}
    if "verified_progress" not in cols:
        conn.execute("ALTER TABLE party_goals ADD COLUMN verified_progress INTEGER NOT NULL DEFAULT 0")
    if "last_source" not in cols:
        conn.execute("ALTER TABLE party_goals ADD COLUMN last_source TEXT NOT NULL DEFAULT 'player'")


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Living Worlds lease columns: durable worker ownership + heartbeat for
    conversion jobs, so interrupted jobs are detectable and resumable."""
    cols = set()
    if "forge_jobs" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(forge_jobs)")}
    if "owner" not in cols:
        conn.execute("ALTER TABLE forge_jobs ADD COLUMN owner TEXT")
    if "heartbeat" not in cols:
        conn.execute("ALTER TABLE forge_jobs ADD COLUMN heartbeat TEXT")
    # legacy active states become owned-running rows with a stale heartbeat so
    # the recovery sweep can pick them up deterministically
    conn.execute(
        "UPDATE forge_jobs SET status='running', heartbeat=NULL"
        " WHERE status IN ('analyzing','bible','generating','validating')")


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    """Living Campaign migration: split-party locations, spectator roles,
    encounter/jobs/revisions/director/checkpoint tables."""
    char_cols = {r[1] for r in conn.execute("PRAGMA table_info(characters)")}
    if "location_id" not in char_cols:
        conn.execute("ALTER TABLE characters ADD COLUMN location_id TEXT")
    if "mp_players" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        mp_cols = {r[1] for r in conn.execute("PRAGMA table_info(mp_players)")}
        if "role" not in mp_cols:
            conn.execute("ALTER TABLE mp_players ADD COLUMN role TEXT NOT NULL DEFAULT 'player'")
    draft_cols = set()
    if "forge_drafts" in {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        draft_cols = {r[1] for r in conn.execute("PRAGMA table_info(forge_drafts)")}
        if "owner" not in draft_cols:
            conn.execute("ALTER TABLE forge_drafts ADD COLUMN owner TEXT")
        if "collab_json" not in draft_cols:
            conn.execute("ALTER TABLE forge_drafts ADD COLUMN collab_json TEXT NOT NULL DEFAULT '{}'")
    conn.executescript("""
CREATE TABLE IF NOT EXISTS party_goals (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  target INTEGER NOT NULL DEFAULT 3,
  progress INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  scope TEXT NOT NULL DEFAULT 'party',
  owner_player_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campfire_stories (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  author_player_id TEXT NOT NULL DEFAULT 'local',
  author_name TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'story',
  text TEXT NOT NULL,
  related_event_seq INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forge_contrib (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  author_id TEXT NOT NULL,
  author_name TEXT NOT NULL,
  ops_json TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  base_rev INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'proposed',
  applied_rev INTEGER,
  conflicts_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forge_contrib_draft ON forge_contrib (draft_id, status);
CREATE TABLE IF NOT EXISTS dnd_encounters (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  round INTEGER NOT NULL DEFAULT 1,
  turn_index INTEGER NOT NULL DEFAULT 0,
  state_json TEXT NOT NULL DEFAULT '{}',
  rewards_granted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dnd_enc_campaign ON dnd_encounters (campaign_id, status);
CREATE TABLE IF NOT EXISTS forge_jobs (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'faithful',
  scope TEXT NOT NULL DEFAULT 'short',
  status TEXT NOT NULL DEFAULT 'queued',
  stage TEXT NOT NULL DEFAULT '',
  progress REAL NOT NULL DEFAULT 0,
  coverage_json TEXT NOT NULL DEFAULT '{}',
  profile_json TEXT NOT NULL DEFAULT '{}',
  bible_json TEXT NOT NULL DEFAULT '{}',
  pack_json TEXT NOT NULL DEFAULT '{}',
  notes_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  cancel INTEGER NOT NULL DEFAULT 0,
  draft_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forge_jobs_doc ON forge_jobs (doc_id, status);
CREATE TABLE IF NOT EXISTS forge_revisions (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  pack_json TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forge_rev_draft ON forge_revisions (draft_id, seq);
CREATE TABLE IF NOT EXISTS director_threads (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'quest',
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'introduced',
  detail_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_director_campaign ON director_threads (campaign_id, status);
CREATE TABLE IF NOT EXISTS campaign_checkpoints (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  name TEXT NOT NULL,
  export_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
""")


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Shared Shore migration. Idempotent; additive except the characters
    table rebuild, which preserves every column and row verbatim."""
    # 1. characters: drop the one-character-per-campaign UNIQUE constraint.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='characters'"
    ).fetchone()
    if row and "UNIQUE" in (row["sql"] or ""):
        conn.executescript("""
CREATE TABLE characters_v3 (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
  name TEXT NOT NULL,
  archetype TEXT NOT NULL,
  portrait_json TEXT NOT NULL DEFAULT '{}',
  attributes_json TEXT NOT NULL DEFAULT '{}',
  skills_json TEXT NOT NULL DEFAULT '{}',
  vigor INTEGER NOT NULL DEFAULT 10,
  vigor_max INTEGER NOT NULL DEFAULT 10,
  nerve INTEGER NOT NULL DEFAULT 10,
  nerve_max INTEGER NOT NULL DEFAULT 10,
  data_json TEXT NOT NULL DEFAULT '{}'
);
INSERT INTO characters_v3 SELECT id, campaign_id, name, archetype, portrait_json,
  attributes_json, skills_json, vigor, vigor_max, nerve, nerve_max, data_json
  FROM characters;
DROP TABLE characters;
ALTER TABLE characters_v3 RENAME TO characters;
""")
    # 2. inventory rows belong to a character (legacy rows adopt the campaign's
    #    original wanderer).
    inv_cols = {r[1] for r in conn.execute("PRAGMA table_info(inventory)")}
    if "character_id" not in inv_cols:
        conn.execute("ALTER TABLE inventory ADD COLUMN character_id TEXT")
        conn.execute(
            "UPDATE inventory SET character_id = "
            "  (SELECT id FROM characters WHERE characters.campaign_id = inventory.campaign_id)"
            " WHERE character_id IS NULL"
        )
    # 3. clue sharing flag (multiplayer share-a-clue).
    clue_cols = {r[1] for r in conn.execute("PRAGMA table_info(clues)")}
    if "shared" not in clue_cols:
        conn.execute("ALTER TABLE clues ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
    # 4. move per-character state out of the campaign blob. In solo play all
    #    of it belonged to the single wanderer; in multiplayer a shared purse
    #    or a shared death would be nonsense.
    PER_CHARACTER = ("beads", "dead", "pending_roll", "omen_bonus", "omen_draws_used")
    for camp in conn.execute("SELECT id, state_json FROM campaigns").fetchall():
        try:
            state = json.loads(camp["state_json"] or "{}")
        except json.JSONDecodeError:
            continue
        moved = {k: state.pop(k) for k in PER_CHARACTER if k in state}
        if not moved:
            continue
        chars = conn.execute(
            "SELECT id, data_json FROM characters WHERE campaign_id=?", (camp["id"],)
        ).fetchall()
        for c in chars:
            try:
                data = json.loads(c["data_json"] or "{}")
            except json.JSONDecodeError:
                data = {}
            data.update(moved)
            conn.execute(
                "UPDATE characters SET data_json=? WHERE id=?",
                (json.dumps(data), c["id"]),
            )
            # 5. the omen deck follows its owner
            conn.execute(
                "UPDATE decks SET deck_id=? WHERE campaign_id=? AND deck_id='omens'",
                ("omens:" + c["id"], camp["id"]),
            )
        conn.execute(
            "UPDATE campaigns SET state_json=? WHERE id=?",
            (json.dumps(state), camp["id"]),
        )


# --------------------------------------------------------------------------
# Small helpers used across the server modules
# --------------------------------------------------------------------------

def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _LOCK:
        return get_conn().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _LOCK:
        return get_conn().execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> None:
    with _LOCK:
        conn = get_conn()
        conn.execute(sql, params)
        conn.commit()


def execute_rc(sql: str, params: tuple = ()) -> int:
    """Execute and return the affected rowcount — for atomic conditional
    updates such as single-winner worker leases."""
    with _LOCK:
        conn = get_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def get_setting(key: str, default: str | None = None) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_json_setting(key: str, default):
    raw = get_setting(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def set_json_setting(key: str, value) -> None:
    set_setting(key, json.dumps(value, ensure_ascii=False))


def jloads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def jdumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# --------------------------------------------------------------------------
# Event log + search index maintenance
# --------------------------------------------------------------------------

def log_event(campaign_id: str, event_type: str, data: dict) -> None:
    execute(
        "INSERT INTO events (id, campaign_id, ts, type, data_json) VALUES (?,?,?,?,?)",
        (new_id("ev"), campaign_id, utcnow(), event_type, jdumps(data)),
    )


def search_add(campaign_id: str, kind: str, ref_id: str, title: str, body: str) -> None:
    """Insert a document into the FTS index (old rows for ref_id replaced)."""
    with _LOCK:
        conn = get_conn()
        conn.execute("DELETE FROM search_index WHERE ref_id=?", (ref_id,))
        conn.execute(
            "INSERT INTO search_index (body, campaign_id, kind, ref_id) VALUES (?,?,?,?)",
            (f"{title}\n{body}".strip(), campaign_id, kind, ref_id),
        )
        conn.commit()


def search_remove(ref_id: str) -> None:
    execute("DELETE FROM search_index WHERE ref_id=?", (ref_id,))


def search_campaign(campaign_id: str, q: str, limit: int = 20) -> list[dict]:
    """Full-text search inside one campaign. Falls back to LIKE if FTS fails."""
    try:
        rows = query(
            "SELECT ref_id, kind, body, bm25(search_index) AS rank "
            "FROM search_index WHERE search_index MATCH ? AND campaign_id=? "
            "ORDER BY rank LIMIT ?",
            (q, campaign_id, limit),
        )
        return [
            {"ref_id": r["ref_id"], "kind": r["kind"], "snippet": r["body"][:240]}
            for r in rows
        ]
    except sqlite3.OperationalError:
        like = f"%{q}%"
        rows = query(
            "SELECT id AS ref_id, kind AS kind, text AS body FROM ("
            "  SELECT id, 'journal' AS kind, text FROM journal WHERE campaign_id=? AND text LIKE ?"
            "  UNION ALL SELECT id, 'transcript', content FROM transcript WHERE campaign_id=? AND content LIKE ?"
            ") LIMIT ?",
            (campaign_id, like, campaign_id, like, limit),
        )
        return [{"ref_id": r["ref_id"], "kind": r["kind"], "snippet": r["body"][:240]} for r in rows]


def add_transcript(campaign_id: str, role: str, content: str, data: dict | None = None) -> str:
    tid = new_id("tr")
    ts = utcnow()
    execute(
        "INSERT INTO transcript (id, campaign_id, ts, role, content, data_json) VALUES (?,?,?,?,?,?)",
        (tid, campaign_id, ts, role, content, jdumps(data or {})),
    )
    search_add(campaign_id, "transcript", tid, role, content)
    return tid


def add_journal(campaign_id: str, text: str, kind: str = "auto") -> str:
    jid = new_id("jr")
    ts = utcnow()
    execute(
        "INSERT INTO journal (id, campaign_id, ts, kind, text) VALUES (?,?,?,?,?)",
        (jid, campaign_id, ts, kind, text),
    )
    search_add(campaign_id, "journal", jid, kind, text)
    return jid
