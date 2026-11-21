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
  state_json TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  campaign_id TEXT UNIQUE NOT NULL,
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

CREATE TABLE IF NOT EXISTS inventory (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL,
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
-- Not used by solo play yet; the schema ships early so the contract is fixed.
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
"""

SEARCH_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
  body,
  campaign_id UNINDEXED,
  kind UNINDEXED,
  ref_id UNINDEXED
);
"""


def init_db() -> None:
    """Create/upgrade the schema. Migrations are additive and versioned."""
    conn = get_conn()
    with _LOCK:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SEARCH_SQL)
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (config.SCHEMA_VERSION,),
            )
        conn.commit()


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
