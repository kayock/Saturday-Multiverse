"""Saturday Multiverse — the Living Worlds experience layer.

Returning-player recaps, shared expedition goals, Campfire Stories, and
What-If Timelines. Every feature reads ONLY authoritative engine state and
event records; player-authored stories are stored separately and never
treated as proof that something happened.
"""
from __future__ import annotations

import json

from . import db, director, legacy, mp
from .db import jdumps, jloads, new_id, utcnow


# ==========================================================================
# 7.1 — The Shore Remembers: returning-player recap
# ==========================================================================

# Shore-gossip scopes a player-facing recap may quote. `deep` (and any scope
# not listed here) is NPC-internal or GM-only knowledge and stays out of the
# recap; the same whitelist the shore NPCs themselves hear through.
# ---------------------------------------------------------------------------
# Per-character knowledge tracking (schema v8) — the authoritative record of
# what each character has actually seen, visited or been told in person.
# Rows: kind visited|discovery|heard (character-scoped) and shared ('*party*',
# granted to the whole party when someone tells the tale at the campfire).
# ---------------------------------------------------------------------------
def note_knowledge(cid: str, character_id: str | None, kind: str, ref: str) -> None:
    """Record that a character (or '*party*' via sharing) holds knowledge `ref`.
    Failure-isolated: knowledge bookkeeping must never break gameplay."""
    try:
        if not cid or not ref:
            return
        db.execute(
            "INSERT INTO char_knowledge (id, campaign_id, character_id, kind, ref, ts)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(campaign_id, character_id, kind, ref)"
            " DO NOTHING",
            (new_id("kn"), cid, character_id or "*party*", kind[:12], str(ref)[:80],
             utcnow()))
    except Exception:  # noqa: BLE001
        pass


def note_visit(cid: str, character_id: str | None, loc_id: str) -> None:
    note_knowledge(cid, character_id, "visited", loc_id)


def note_discovery(cid: str, character_id: str | None, loc_id: str) -> None:
    note_knowledge(cid, character_id, "discovery", loc_id)


def note_heard(cid: str, character_id: str | None, scope: str) -> None:
    note_knowledge(cid, character_id, "heard", scope)


def note_memory(cid: str, character_id: str | None, mem_id: str) -> None:
    """Record that a character actually LEARNED one specific npc_memory
    (hotfix 4). Written only at authoritative delivery points — an NPC
    conversation that delivered the memory, the character's own arrival tale,
    a visitor tale told while they rested, or a party member sharing it at
    the campfire. A hearing scope ('heard') stays evidence of presence; it is
    never proof of knowing every present and future rumor in that scope."""
    note_knowledge(cid, character_id, "memory", mem_id)


def reveal_memory(cid: str, character_id: str | None, mem_id: str,
                  scope: str | None = None) -> None:
    """An explicit, ENGINE-AUTHORIZED story event that reveals one specific
    memory (hotfix 5). This is the only sanctioned way internal NPC knowledge
    — including deep-scoped material — becomes player-facing: a scripted
    investigation payoff or GM action calls this after the gameplay event
    that justifies the revelation. Optionally relabels the memory's scope
    into a player-facing one so the static recap/share rules can carry it;
    kind restrictions (gm/secret/hidden/host) always dominate and such
    records stay restricted whatever the event does. Ordinary conversations
    must never reach this function."""
    row = db.query_one("SELECT id FROM npc_memories WHERE campaign_id=? AND id=?",
                       (cid, mem_id))
    if not row:
        raise ValueError("no such memory on this shore")
    if scope:
        db.execute("UPDATE npc_memories SET scope=? WHERE campaign_id=? AND id=?",
                   (scope[:20], cid, mem_id))
    note_memory(cid, character_id, mem_id)


def _memory_entitlement(cid: str, character_id: str | None, mem_id: str) -> bool:
    """Can the engine establish that THIS character learned THIS exact memory?

    True when the character holds the specific acquisition record, or when a
    party-wide grant of that memory already exists (a legitimate campfire
    share delivered it to the party — including grants recorded before
    hotfix 4). Presence at a place, a visit, or a hearing scope alone never
    counts: a scope is evidence of a past interaction, not of knowing every
    present and future memory in it."""
    if not character_id or not mem_id:
        return False
    row = db.query_one(
        "SELECT id FROM char_knowledge WHERE campaign_id=? AND character_id=?"
        " AND kind='memory' AND ref=?", (cid, character_id, mem_id))
    if row:
        return True
    row = db.query_one(
        "SELECT id FROM char_knowledge WHERE campaign_id=? AND character_id='*party*'"
        " AND kind='shared' AND ref=?", (cid, mem_id))
    return row is not None


# --------------------------------------------------------------------------
# Hotfix 3 — explicit, bounded, event-specific campfire sharing.
#
# Telling a campfire story shares NOTHING by itself. When a teller WANTS to
# share, they select individual items (a discovery, a visited place, one
# specific memory) and the engine validates every selection server-side:
# only what the character legitimately holds may be shared, GM-only and
# hidden knowledge can never be shared, and a bare hearing scope ('tavern')
# is never granted — that would authorize every past and FUTURE rumor there.
# Each grant writes a '*party*' shared row (schema v8, unchanged format) plus
# an auditable ledger row in knowledge_shares recording exactly what was
# shared, by whom, and when. Grants are idempotent: a retry never duplicates
# a party grant or a ledger row.
# --------------------------------------------------------------------------
MAX_SHARE_ITEMS = 20


def _is_shareable_memory(m) -> bool:
    """The same static rules the recap applies: GM-only, hidden and deep
    knowledge can never be shared or surfaced, whatever a player selects."""
    return (m["scope"] in RECAP_MEMORY_SCOPES
            and m["kind"] not in RECAP_MEMORY_KINDS_BLOCKED
            and m["kind"] != "ending")


def teller_character(cid: str, author_player_id: str | None) -> str | None:
    """The character behind a campfire author. A multiplayer player resolves
    through their OWN player row (campaign-scoped) — spectators carry no
    character and hold nothing to share. The campaign-character fallback
    exists ONLY for legitimate session-less solo requests: callers must
    resolve multiplayer authorization BEFORE reaching this function
    (see campfire_shareable in api.py, hotfix 4)."""
    try:
        prow = db.query_one(
            "SELECT character_id FROM mp_players WHERE id=? AND campaign_id=?",
            (author_player_id or "", cid))
        if prow is not None:
            return prow["character_id"]
    except Exception:  # noqa: BLE001
        pass
    crow = db.query_one("SELECT character_id FROM campaigns WHERE id=?", (cid,))
    return crow["character_id"] if crow else None


def share_knowledge(cid: str, character_id: str | None, refs,
                    shared_by_player_id: str | None = None,
                    story_id: str | None = None) -> dict:
    """Share EXPLICITLY selected knowledge with the party.

    `refs` are individual item identifiers: place refs the character visited
    or discovered, or the exact id of one npc_memory they heard. Every ref is
    validated against what THIS character already legitimately knows; rejected
    selections are reported with a reason and nothing is granted for them.
    Future memories at a shared place stay private: a party-wide grant covers
    only what was recorded up to the moment of the grant (enforced by the
    recap entitlement gate via the grant timestamp)."""
    shared: list[str] = []
    rejected: list[dict] = []
    try:
        if isinstance(refs, str):
            refs = [refs]
        if refs is None:
            refs = []
        if not isinstance(refs, list):
            raise ValueError("share must be a list of knowledge refs")
        refs = [str(r).strip()[:80] for r in refs if str(r or "").strip()][:MAX_SHARE_ITEMS]
        if not refs:
            return {"shared": shared, "rejected": rejected, "granted": 0}
        if not character_id:
            return {"shared": [], "rejected": [
                {"ref": r, "reason": "this traveler holds no shareable knowledge"}
                for r in refs], "granted": 0}
        own = {r["ref"]: r["kind"] for r in db.query(
            "SELECT ref, kind FROM char_knowledge WHERE campaign_id=? AND character_id=?"
            " AND kind IN ('visited','discovery')", (cid, character_id))}
        heard = {r["ref"] for r in db.query(
            "SELECT ref FROM char_knowledge WHERE campaign_id=? AND character_id=?"
            " AND kind='heard'", (cid, character_id))}
        for ref in refs:
            mem = db.query_one("SELECT id, kind, scope FROM npc_memories"
                               " WHERE campaign_id=? AND id=?", (cid, ref))
            if mem is not None:
                if not _is_shareable_memory(mem):
                    rejected.append({"ref": ref, "reason":
                                     "GM-only and hidden knowledge can never be shared"})
                    continue
                # hotfix 4: entitlement is per specific memory, established by
                # an authoritative delivery point (never by a hearing scope).
                # Memories scoped 'all' are public world news the engine
                # already delivers to every player's recap.
                if mem["scope"] != "all" and not _memory_entitlement(cid, character_id, ref):
                    rejected.append({"ref": ref, "reason":
                                     "you have not actually heard this — rumors must be "
                                     "heard in person, or shared to you at the fire"})
                    continue
                ref_kind, source_kind = "memory", "memory"
            elif ref in own:
                ref_kind, source_kind = "place", own[ref]
            elif ref in heard:
                rejected.append({"ref": ref, "reason":
                                 "a hearing scope is not shareable — select the specific memory instead"})
                continue
            else:
                rejected.append({"ref": ref, "reason": "you do not hold this knowledge"})
                continue
            existing = db.query_one(
                "SELECT id FROM knowledge_shares WHERE campaign_id=? AND ref=?", (cid, ref))
            if existing:
                shared.append(ref)  # idempotent retry: no duplicate grant or event
                continue
            note_knowledge(cid, "*party*", "shared", ref)
            if ref_kind == "memory":
                # the whole party hears the tale at the fire: every character
                # learns exactly this memory (idempotent; spectators carry no
                # character row and follow the shared feed instead)
                for crow in db.query("SELECT id FROM characters WHERE campaign_id=?", (cid,)):
                    note_memory(cid, crow["id"], ref)
            db.execute(
                "INSERT INTO knowledge_shares (id, campaign_id, ref, ref_kind, source_kind,"
                " shared_by_player_id, shared_by_character_id, story_id, ts)"
                " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id, ref) DO NOTHING",
                (new_id("ksh"), cid, ref, ref_kind, source_kind,
                 (shared_by_player_id or "local")[:40], character_id, story_id, utcnow()))
            db.log_event(cid, "knowledge_shared", {
                "ref": ref, "ref_kind": ref_kind, "source": source_kind,
                "by_player": shared_by_player_id or "local",
                "by_character": character_id, "story_id": story_id})
            shared.append(ref)
        return {"shared": shared, "rejected": rejected, "granted": len(shared)}
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 — sharing must never break the story carrying it
        return {"shared": shared, "granted": len(shared), "rejected": rejected + [
            {"ref": "*", "reason": f"knowledge sharing failed: {type(exc).__name__}"}]}


def shareable_knowledge(cid: str, character_id: str | None, limit: int = 40) -> dict:
    """What THIS character may select to share at the fire: the places they
    know and the specific eligible memories they actually heard. This is the
    teller's own knowledge — never another character's, and never a bare
    hearing scope."""
    out = {"character_id": character_id, "places": [], "memories": []}
    if not cid or not character_id:
        return out
    try:
        loc_names = {}
        try:
            from . import worldpacks as _wp
            pack_data = _wp.load_pack(db.query_one(
                "SELECT pack_id FROM campaigns WHERE id=?", (cid,))["pack_id"]) or {}
            loc_names = {l.get("id"): l.get("name", l.get("id"))
                         for l in pack_data.get("locations", [])}
        except Exception:  # noqa: BLE001
            pass
        places: list = []
        seen: set = set()
        for r in db.query(
                "SELECT ref, kind FROM char_knowledge WHERE campaign_id=? AND character_id=?"
                " AND kind IN ('visited','discovery') ORDER BY rowid DESC", (cid, character_id)):
            if r["ref"] in seen:
                continue
            seen.add(r["ref"])
            places.append(r)
        out["places"] = [{"ref": r["ref"], "kind": r["kind"],
                          "label": loc_names.get(r["ref"], r["ref"].replace("_", " ").title())}
                         for r in places]
        picked = 0
        for m in db.query("SELECT id, scope, kind, text FROM npc_memories"
                          " WHERE campaign_id=? ORDER BY rowid DESC LIMIT 200", (cid,)):
            if picked >= limit:
                break
            if not _is_shareable_memory(m):
                continue
            # hotfix 4: the picker offers exactly what the sharing engine
            # would accept — specific acquired memories (or public 'all'
            # news), never everything under a hearing scope
            if m["scope"] != "all" and not _memory_entitlement(cid, character_id, m["id"]):
                continue
            out["memories"].append({"ref": m["id"], "scope": m["scope"],
                                    "text": m["text"][:120]})
            picked += 1
        return out
    except Exception:  # noqa: BLE001
        return out


def campaign_has_knowledge_rows(cid: str) -> bool:
    row = db.query_one("SELECT id FROM char_knowledge WHERE campaign_id=? LIMIT 1", (cid,))
    return row is not None


def _viewer_context(cid: str, player: dict | None) -> dict:
    """Resolve the viewer for player-aware recap filtering.

    Returns {char_id, is_solo, is_spectator, knowledge, legacy}:
    - knowledge: the set of place refs this viewer is entitled to;
    - legacy: True when the campaign predates knowledge tracking (no
      char_knowledge rows at all) — a documented conservative fallback:
      solo viewers keep the old campaign-wide behavior, multiplayer viewers
      see only global news until someone shares at the campfire."""
    session = None
    try:
        session = mp._session(cid)
    except Exception:  # noqa: BLE001
        session = None
    is_solo = not session
    char_id = None
    spectator = False
    if player:
        char_id = player.get("character_id")
        pdata = player.get("data_json")
        if isinstance(pdata, str):
            try:
                pdata = jloads(pdata, {})
            except Exception:
                pdata = {}
        if isinstance(pdata, dict):
            # spectators join via spectator invitations and carry
            # role:"spectator" in their player record
            spectator = bool(pdata.get("spectator")) or pdata.get("role") == "spectator"
    if not char_id and is_solo:
        row = db.query_one("SELECT character_id FROM campaigns WHERE id=?", (cid,))
        char_id = row["character_id"] if row else None
    own = set()
    own_memory_ids: set = set()
    if char_id:
        for r in db.query(
                "SELECT kind, ref FROM char_knowledge WHERE campaign_id=? AND character_id=?",
                (cid, char_id)):
            own.add(r["ref"])
            if r["kind"] == "memory":
                own_memory_ids.add(r["ref"])
    shared_rows = db.query(
        "SELECT ref, ts FROM char_knowledge WHERE campaign_id=? AND character_id='*party*'"
        " AND kind='shared'", (cid,))
    shared = {r["ref"] for r in shared_rows}
    # when each party-wide grant happened — a shared scope covers only what
    # was already recorded at grant time (earliest grant wins, the most
    # conservative reading of pre-hotfix3 blanket rows)
    shared_ts: dict = {}
    for r in shared_rows:
        prev = shared_ts.get(r["ref"])
        ts = r["ts"] or ""
        if prev is None or (ts and ts < prev):
            shared_ts[r["ref"]] = ts or prev or ""
    legacy = not campaign_has_knowledge_rows(cid)
    if legacy:
        if is_solo:
            # pre-tracking solo saves: the one character saw everything the
            # campaign recorded — keep the old recap behavior intact
            knowledge = None  # None = unrestricted (solo legacy)
        else:
            knowledge = set(shared)  # conservative: shared only
    else:
        knowledge = (own | shared) if not spectator else set(shared)
    return {"char_id": char_id, "is_solo": is_solo, "spectator": spectator,
            "knowledge": knowledge, "legacy": legacy, "own": own,
            "own_memory_ids": own_memory_ids, "shared_ts": shared_ts}


def _max_rowid(table: str, cid: str) -> int:
    """Highest rowid this campaign has produced in one event table — the
    exact, monotonic last-seen identifier for that table."""
    row = db.query_one(f"SELECT MAX(rowid) AS m FROM {table} WHERE campaign_id=?",
                       (cid,))
    return int(row["m"] or 0)


RECAP_MEMORY_SCOPES = ("all", "camp", "doors", "tavern")
RECAP_MEMORY_KINDS_BLOCKED = ("secret", "hidden", "gm", "host")
RECAP_MEMORY_LIMIT = 8        # the display budget for NPC memories (unchanged)
RECAP_MEMORY_BATCH = 64       # candidate page size for the backward walk
RECAP_MEMORY_SCAN_CAP = 2000  # absolute bound on candidate rows scanned per recap


def _recap_marker_for(cid: str, player_id: str) -> dict:
    """The viewer's OWN last-seen marker, from the per-player recap_seen table
    (schema v8). One player's dismissal never marks another player's unseen
    events as read; rows survive disconnects and application restarts.

    Legacy seeding (documented conservative policy): a viewer with no row yet
    on a campaign that carries old campaign-wide markers starts from that
    shared marker — per-player history was never recorded before this
    migration, so it cannot be reconstructed; the shared marker is the
    truthful upper bound that avoids replaying dismissed history. Campaigns
    that never dismissed a recap get a zero marker (recent activity is new)."""
    row = db.query_one("SELECT * FROM recap_seen WHERE campaign_id=? AND player_id=?",
                       (cid, player_id))
    if row:
        try:
            marks = jloads(row["seen_rowids_json"], {})
            if isinstance(marks, dict) and marks:
                return {k: int(v) for k, v in marks.items()}
        except Exception:
            pass
        return {"events": 0, "npc_memories": 0, "journal": 0, "char_knowledge": 0,
                "upgrades": 0, "consequences": 0, "mp_events": 0}
    # no per-player row yet: seed once from the legacy campaign-wide marker
    camp = db.query_one("SELECT turn, state_json FROM campaigns WHERE id=?", (cid,))
    state = jloads(camp["state_json"], {}) if camp else {}
    has_legacy = (state.get("recap_seen_rowids") or state.get("recap_seen_ts")
                  or state.get("recap_seen_turn") is not None)
    if has_legacy:
        # a real legacy marker exists: tables it could not track are frozen
        # at the current high-water mark so dismissed history never replays
        marker = _legacy_marker(cid, state)
        for table, key in (("npc_memories", "npc_memories"), ("journal", "journal"),
                           ("upgrades", "upgrades"), ("consequences", "consequences"),
                           ("events", "events"), ("char_knowledge", "char_knowledge")):
            if not marker.get(key):
                marker[key] = _max_rowid(table, cid)
        marker.setdefault("mp_events", int(mp.latest_seq(cid)))
    else:
        # never dismissed: recent activity legitimately shows as new
        marker = {"events": 0, "npc_memories": 0, "journal": 0, "char_knowledge": 0,
                  "upgrades": 0, "consequences": 0, "mp_events": 0}
    db.execute(
        "INSERT INTO recap_seen (id, campaign_id, player_id, seen_rowids_json,"
        " seen_turn, seen_ts, dismissed_at) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(campaign_id, player_id) DO NOTHING",
        (new_id("rcs"), cid, player_id, jdumps(marker),
         int(camp["turn"] or 0) if camp else 0, utcnow(), utcnow()))
    return marker


def _legacy_marker(cid: str, state: dict) -> dict:
    """Derive the legacy campaign-wide rowid marker (hotfix1 format), or a
    zero marker for campaigns that never dismissed a recap."""
    marks = state.get("recap_seen_rowids")
    if isinstance(marks, dict) and marks:
        return {k: int(v) for k, v in marks.items()}
    if state.get("recap_seen_ts"):
        row = db.query_one(
            "SELECT MAX(rowid) AS m FROM events WHERE campaign_id=? AND ts <= ?",
            (cid, str(state["recap_seen_ts"])))
        return {"events": int(row["m"] or 0), "npc_memories": 0, "journal": 0,
                "upgrades": 0, "consequences": 0, "mp_events": 0}
    seen_turn = state.get("recap_seen_turn")
    if seen_turn is not None:
        try:
            row = db.query_one(
                "SELECT MAX(rowid) AS m FROM events WHERE campaign_id=? AND type='turn'"
                " AND CAST(json_extract(data_json, '$.turn') AS INTEGER) <= ?",
                (cid, int(seen_turn)))
            if row and row["m"]:
                return {"events": int(row["m"]), "npc_memories": 0, "journal": 0,
                        "upgrades": 0, "consequences": 0, "mp_events": 0}
        except Exception:
            pass
    return {"events": 0, "npc_memories": 0, "journal": 0, "char_knowledge": 0,
            "upgrades": 0, "consequences": 0, "mp_events": 0}


def _recap_marker(cid: str, state: dict) -> dict:
    """The last-seen marker as per-table rowids — reliable, monotonic
    identifiers (never a wall-clock second that two events may share, and
    never a comparison between unrelated identifier spaces).

    New dismissals store `recap_seen_rowids` = {events, npc_memories, journal,
    upgrades, consequences, mp_events}. Older saves (before this marker
    format) store only `recap_seen_turn`; that migrates safely by reading the
    rowid of the last engine `turn` event at or below that turn (engine events
    carry their turn in data_json). If nothing can be derived, every marker is
    0 — meaning "nothing new", never the opposite: a returning player sees
    ongoing context but no replayed history."""
    marks = state.get("recap_seen_rowids")
    if isinstance(marks, dict) and marks:
        return {k: int(v) for k, v in marks.items()}
    if state.get("recap_seen_ts"):
        # dismissals from the timestamp-marker era: rowids were not stored, so
        # derive the engine-events rowid from the dismissal instant (events at
        # or before it count as seen); other tables have no derivable marker —
        # treat as fully seen (0) to avoid replaying dismissed history
        row = db.query_one(
            "SELECT MAX(rowid) AS m FROM events WHERE campaign_id=? AND ts <= ?",
            (cid, str(state["recap_seen_ts"])))
        return {"events": int(row["m"] or 0), "npc_memories": 0, "journal": 0,
                "upgrades": 0, "consequences": 0, "mp_events": 0}
    seen_turn = state.get("recap_seen_turn")
    if seen_turn is not None:
        try:
            row = db.query_one(
                "SELECT MAX(rowid) AS m FROM events WHERE campaign_id=? AND type='turn'"
                " AND CAST(json_extract(data_json, '$.turn') AS INTEGER) <= ?",
                (cid, int(seen_turn)))
            if row and row["m"]:
                return {"events": int(row["m"]), "npc_memories": 0, "journal": 0,
                        "upgrades": 0, "consequences": 0, "mp_events": 0}
        except Exception:
            pass
    return {"events": 0, "npc_memories": 0, "journal": 0,
            "upgrades": 0, "consequences": 0, "mp_events": 0}


def recap(cid: str, player: dict | None = None) -> dict:
    """What changed since the traveler last stood on the Shore. Built ONLY
    from authoritative engine records; NPC memories are filtered by their
    hearing scope so deep/hidden knowledge never reaches a player-facing
    recap, and every "new" item is filtered against the last-seen marker."""
    campaign = db.query_one(
        "SELECT turn, state_json, updated_at FROM campaigns WHERE id=?", (cid,))
    if not campaign:
        raise ValueError("campaign not found")
    state = jloads(campaign["state_json"], {})
    viewer = _viewer_context(cid, player)
    player_id = (player or {}).get("id") or "local"
    marker = _recap_marker_for(cid, player_id)
    seed_row = db.query_one(
        "SELECT dismissed_at FROM recap_seen WHERE campaign_id=? AND player_id=?",
        (cid, player_id))
    turn = int(campaign["turn"])
    m_ev = marker.get("events", 0)
    m_mem = marker.get("npc_memories", 0)
    m_jrn = marker.get("journal", 0)
    m_up = marker.get("upgrades", 0)
    m_con = marker.get("consequences", 0)
    m_kn = marker.get("char_knowledge", 0)
    m_mp = marker.get("mp_events", 0)
    pack = {}
    try:
        from . import worldpacks
        pack = worldpacks.load_pack(db.query_one(
            "SELECT pack_id FROM campaigns WHERE id=?", (cid,))["pack_id"]) or {}
    except Exception:
        pack = {}

    items: list[dict] = []
    seen_keys: set = set()

    def add(kind: str, novelty: str, text: str, ref: str | None = None) -> None:
        key = (kind, " ".join(text.lower().split())[:110])
        if key in seen_keys:
            return  # no duplicate recap entries
        seen_keys.add(key)
        items.append({"kind": kind, "novelty": novelty, "text": text, "ref": ref})

    # --- genuinely NEW developments (strictly after the last-seen marker) ---
    victories = db.query(
        "SELECT rowid AS rid, ts, data_json FROM events WHERE campaign_id=?"
        " AND type='combat_victory' AND rowid > ? ORDER BY rowid", (cid, m_ev))
    for v in victories:
        d = jloads(v["data_json"], {})
        add("achievement", "new",
            f"The party won a fight against {d.get('monster', 'foes')}.", f"ev{v['rid']}")

    end_mem = db.query(
        "SELECT rowid AS rid, ts, text FROM npc_memories WHERE campaign_id=?"
        " AND kind='ending' AND scope='all' AND rowid > ? ORDER BY rowid", (cid, m_mem))
    if m_mp:  # the multiplayer stream marker also gates replayed endings
        pass
    for e in end_mem:
        add("achievement", "new",
            f"A story reached its ending — {e['text'][:110]}", f"mem{e['rid']}")

    if viewer["legacy"]:
        # pre-tracking saves: discoveries were campaign-wide records — keep
        # the established behavior (documented legacy policy)
        discoveries = db.query(
            "SELECT rowid AS rid, ts, text FROM journal WHERE campaign_id=?"
            " AND kind='discovery' AND rowid > ? ORDER BY rowid", (cid, m_jrn))
        for d in discoveries:
            add("discovery", "new", f"Discovered: {d['text'][:110]}", f"jr{d['rid']}")
    else:
        # knowledge-tracking era: a discovery belongs to its discoverer and to
        # whoever it was shared with at the campfire — never to a player who
        # has not seen the place and was not told
        kn = db.query(
            "SELECT rowid AS rid, character_id, kind, ref, ts FROM char_knowledge"
            " WHERE campaign_id=? AND (kind IN ('discovery','visited')"
            " OR character_id='*party*') AND rowid > ? ORDER BY rowid", (cid, m_kn))
        known_places = viewer["knowledge"] or set()
        loc_names = {}
        try:
            from . import worldpacks as _wp
            pack_data = _wp.load_pack(db.query_one(
                "SELECT pack_id FROM campaigns WHERE id=?", (cid,))["pack_id"]) or {}
            loc_names = {l.get("id"): l.get("name", l.get("id"))
                         for l in pack_data.get("locations", [])}
        except Exception:  # noqa: BLE001
            pass
        for k in kn:
            if k["kind"] == "shared" and db.query_one(
                    "SELECT 1 FROM npc_memories WHERE campaign_id=? AND id=?",
                    (cid, k["ref"])):
                continue  # a shared memory renders through the rumor feed itself
            own = bool(viewer["char_id"]) and k["character_id"] == viewer["char_id"]
            shared_to_party = k["character_id"] == "*party*"
            if viewer["spectator"] and not shared_to_party:
                continue
            if not own and not shared_to_party and k["ref"] not in known_places:
                continue  # another player's private discovery
            label = loc_names.get(k["ref"], k["ref"].replace("_", " ").title())
            if k["kind"] == "shared":
                verb, who = "Told at the fire", ""
            else:
                verb = "Visited" if k["kind"] == "visited" else "Discovered"
                who = ""
                if not own and not shared_to_party:
                    crow = db.query_one("SELECT name FROM characters WHERE id=?",
                                        (k["character_id"],))
                    who = f" by {crow['name']}" if crow else ""
            add("discovery", "new", f"{verb}{who}: {label}.", f"kn{k['rid']}")

    # --- NPC memories (hotfix 3): eligibility is applied BEFORE the display
    # limit. The old query fetched the newest 8 rows and filtered afterwards,
    # so hidden/unauthorized rows could consume the whole window and starve
    # an authorized rumor out of the recap entirely. Now: static rules (the
    # scope whitelist and blocked kinds — independent of the viewer) filter
    # in SQL, and viewer-dependent entitlements gate each candidate inside a
    # bounded backward walk that stops as soon as the display budget is met.
    shared_ts = viewer["shared_ts"]
    place_knowledge = viewer["knowledge"]  # None = unrestricted (solo legacy)

    def _mem_entitled(m) -> bool:
        """Hotfix 5: the recap uses the SAME specific-memory entitlement as
        the sharing engine. A character receives a memory they genuinely
        acquired, one that was exactly shared with them or the party, or
        truly public world news — and never something they merely COULD have
        heard because they once visited the place or hold an old hearing
        scope. (Past presence no longer discloses memories created later;
        static kind/scope restrictions have already filtered the candidates
        in SQL, so a public scope can never surface a restricted kind.)"""
        scope = m["scope"]
        if place_knowledge is None:
            return True                 # solo legacy: the one character heard everything
        if scope == "all":
            return True                 # public world information
        if m["id"] in viewer.get("own_memory_ids", ()):
            return True                 # learned at an authoritative delivery point
        if m["id"] in shared_ts:
            return True                 # explicitly shared memory: the exact item
        grant_ts = shared_ts.get(scope)
        # a historical broad scope grant covers only what existed at grant
        # time — never rumors created after it (documented legacy policy)
        return bool(grant_ts) and (m["ts"] or "") <= grant_ts

    mems: list = []
    scope_ph = ",".join("?" * len(RECAP_MEMORY_SCOPES))
    kind_ph = ",".join("?" * len(RECAP_MEMORY_KINDS_BLOCKED))
    base_sql = ("SELECT rowid AS rid, id, npc_id, ts, kind, scope, text FROM npc_memories"
                " WHERE campaign_id=? AND rowid > ? AND kind != 'ending'"
                f" AND scope IN ({scope_ph})"
                f" AND kind NOT IN ({kind_ph})")
    static_params = list(RECAP_MEMORY_SCOPES) + list(RECAP_MEMORY_KINDS_BLOCKED)
    upper = None
    scanned = 0
    while len(mems) < RECAP_MEMORY_LIMIT and scanned < RECAP_MEMORY_SCAN_CAP:
        sql, params = base_sql, [cid, m_mem, *static_params]
        if upper is not None:
            sql += " AND rowid < ?"
            params.append(upper)
        sql += " ORDER BY rowid DESC LIMIT ?"
        params.append(RECAP_MEMORY_BATCH)
        rows = db.query(sql, tuple(params))
        if not rows:
            break
        scanned += len(rows)
        for m in rows:
            if _mem_entitled(m):
                mems.append(m)
                if len(mems) >= RECAP_MEMORY_LIMIT:
                    break
        upper = rows[-1]["rid"]
    for m in mems:
        npc = db.query_one("SELECT name FROM npcs WHERE campaign_id=? AND npc_id=?",
                           (cid, m["npc_id"]))
        who = npc["name"] if npc else ("the shore" if m["npc_id"] == "*" else m["npc_id"])
        add("npc", "new", f"{who}: {m['text'][:100]}", f"mem{m['rid']}")

    ups = db.query(
        "SELECT rowid AS rid, upgrade_id, purchased_at FROM upgrades WHERE campaign_id=?"
        " AND rowid > ? ORDER BY rowid DESC LIMIT 2", (cid, m_up))
    up_catalog = {u.get("id"): u for u in (pack.get("upgrades") or [])}
    for u in ups:
        label = (up_catalog.get(u["upgrade_id"]) or {}).get("name", u["upgrade_id"])
        add("shore", "new", f"The shore gained: {label}.", f"up{u['rid']}")

    cons = db.query(
        "SELECT rowid AS rid, ts, summary FROM consequences WHERE campaign_id=?"
        " AND surfaced=1 AND rowid > ? ORDER BY rowid DESC LIMIT 2", (cid, m_con))
    for c in cons:
        add("consequence", "new", c["summary"][:120], f"con{c['rid']}")

    # --- ONGOING context (persistent, not presented as new) ---
    quests = state.get("quests") or {}
    if isinstance(quests, dict):
        for qid, qstate in list(quests.items())[:4]:
            if qstate in ("active", "introduced", None, True):
                title = next((q.get("title", qid) for q in pack.get("intro_quests", [])
                              if q.get("id") == qid), str(qid))
                add("unresolved", "ongoing", f"Still open: {title}.", None)
    try:
        for t in director._threads(cid)[:6]:
            if t["kind"] == "quest" and t["status"] in ("introduced", "active", "dormant"):
                add("unresolved", "ongoing", f"Still open: {t['title']}.", None)
                break
    except Exception:
        pass
    add("now", "ongoing",
        f"Right now: {(state.get('weather') or {}).get('desc', 'the mist holds')}.", None)

    order = {"achievement": 0, "discovery": 1, "consequence": 2, "npc": 3,
             "shore": 4, "unresolved": 5, "now": 6}
    def _ref_num(i):
        ref = i.get("ref") or ""
        digits = "".join(ch for ch in ref if ch.isdigit())
        return int(digits) if digits else 10**9
    items.sort(key=lambda i: (order.get(i["kind"], 9), _ref_num(i)))
    is_returning = turn > 0 and bool(seed_row and seed_row["dismissed_at"])
    return {
        "turn": turn,
        "viewer": {"solo": viewer["is_solo"], "spectator": viewer["spectator"],
                   "legacy_knowledge": viewer["legacy"]},
        "since_marker": marker,
        "is_returning": is_returning,
        "has_new": any(i["novelty"] == "new" for i in items),
        "items": items[:9],
        "dismissed_at": (seed_row["dismissed_at"] if seed_row else None),
    }


def dismiss_recap(cid: str, player: dict | None = None) -> dict:
    """Record THIS viewer's last-seen marker in their own per-player row
    (schema v8). Solo voyages use the 'local' viewer; multiplayer players key
    their own row, so one player's dismissal never marks another player's
    unseen events as read, and markers survive disconnects and restarts.
    The legacy campaign-wide markers in state_json are left untouched (frozen)
    — they only ever seed viewers who had no row, and rewriting them would
    re-contaminate that seed."""
    row = db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,))
    if not row:
        raise ValueError("campaign not found")
    player_id = (player or {}).get("id") or "local"
    seen_rowids = {
        "events": _max_rowid("events", cid),
        "npc_memories": _max_rowid("npc_memories", cid),
        "journal": _max_rowid("journal", cid),
        "char_knowledge": _max_rowid("char_knowledge", cid),
        "upgrades": _max_rowid("upgrades", cid),
        "consequences": _max_rowid("consequences", cid),
        "mp_events": int(mp.latest_seq(cid)),
    }
    now = utcnow()
    db.execute(
        "INSERT INTO recap_seen (id, campaign_id, player_id, seen_rowids_json,"
        " seen_turn, seen_ts, dismissed_at) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(campaign_id, player_id) DO UPDATE SET"
        " seen_rowids_json=excluded.seen_rowids_json, seen_turn=excluded.seen_turn,"
        " seen_ts=excluded.seen_ts, dismissed_at=excluded.dismissed_at",
        (new_id("rcs"), cid, player_id, jdumps(seen_rowids),
         int(row["turn"] or 0), now, now))
    return {"ok": True, "player_id": player_id, "seen_turn": int(row["turn"] or 0),
            "seen_ts": now, "seen_rowids": seen_rowids}



# ==========================================================================
# 9.1 — Shared expedition goals
# ==========================================================================

def create_goal(cid: str, title: str, target: int = 3, scope: str = "party",
                owner_player_id: str | None = None, detail: str = "") -> dict:
    if not (title or "").strip():
        raise ValueError("a goal needs a title")
    target = max(1, min(20, int(target)))
    gid = new_id("goal")
    db.execute(
        "INSERT INTO party_goals (id, campaign_id, title, detail, target, progress,"
        " status, scope, owner_player_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,'0','active',?,?,?,?)",
        (gid, cid, title.strip()[:120], (detail or "")[:300], target,
         scope if scope in ("party", "personal") else "party",
         owner_player_id, utcnow(), utcnow()),
    )
    db.log_event(cid, "goal_created", {"goal_id": gid, "title": title.strip()[:120]})
    return goal_view(gid)


def goal_view(goal_id: str) -> dict:
    row = db.query_one("SELECT * FROM party_goals WHERE id=?", (goal_id,))
    if not row:
        raise ValueError("no such goal")
    return dict(row)


def goal_view_scoped(cid: str, goal_id: str) -> dict:
    """A goal view that refuses cross-campaign reads (used by mutating
    endpoints before they act)."""
    row = db.query_one("SELECT * FROM party_goals WHERE id=? AND campaign_id=?",
                       (goal_id, cid))
    if not row:
        raise ValueError("no such goal in this campaign")
    return dict(row)


def list_goals(cid: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM party_goals WHERE campaign_id=? ORDER BY created_at", (cid,))]


def goal_progress(cid: str, goal_id: str, delta: int = 1, reason: str = "",
                  verified: bool = False, player: dict | None = None) -> dict:
    """Progress against a goal.

    `verified=True` is reserved for the ENGINE (victories, discoveries, quest
    resolutions via auto_credit): it increments both `progress` and
    `verified_progress` and is the only path that can produce a mechanically
    validated achievement. Any player-facing request uses verified=False: it
    may record voluntary player-authored progress, but can never fabricate an
    engine achievement. Mutations are scoped to the supplied campaign; a
    campaign/goal mismatch raises without touching data. Personal goals
    respect multiplayer ownership."""
    row = db.query_one("SELECT * FROM party_goals WHERE id=? AND campaign_id=?",
                       (goal_id, cid))
    if not row:
        raise ValueError("no such goal in this campaign")
    _check_goal_access(row, player)
    if row["status"] != "active":
        return goal_view(goal_id)
    new_progress = max(0, min(row["target"], row["progress"] + int(delta)))
    new_verified = (max(0, min(row["target"], row["verified_progress"] + int(delta)))
                    if verified else int(row["verified_progress"]))
    status = "complete" if new_progress >= row["target"] else "active"
    db.execute(
        "UPDATE party_goals SET progress=?, verified_progress=?, last_source=?,"
        " status=?, updated_at=? WHERE id=? AND campaign_id=?",
        (new_progress, new_verified, "engine" if verified else "player",
         status, utcnow(), goal_id, cid))
    db.log_event(cid, "goal_progress", {
        "goal_id": goal_id, "progress": new_progress, "target": row["target"],
        "verified": bool(verified), "reason": reason[:80]})
    return goal_view(goal_id)


def _check_goal_access(row, player: dict | None) -> None:
    """Personal goals belong to their owner; a multiplayer guest may not
    change another player's personal goal (the host and the local player
    may — the established ownership model)."""
    if (row["scope"] == "personal" and row["owner_player_id"]
            and player is not None
            and player.get("id") != row["owner_player_id"]
            and not player.get("is_host")):
        from .mp import MpDenied
        raise MpDenied("that vow belongs to another traveler")


def abandon_goal(cid: str, goal_id: str, player: dict | None = None) -> dict:
    """Abandon a goal. Scoped to the supplied campaign AND verified to belong
    to it first — a mismatched campaign/goal combination is rejected without
    modifying any data."""
    row = db.query_one("SELECT * FROM party_goals WHERE id=? AND campaign_id=?",
                       (goal_id, cid))
    if not row:
        raise ValueError("no such goal in this campaign")
    _check_goal_access(row, player)
    db.execute(
        "UPDATE party_goals SET status='abandoned', updated_at=? WHERE id=? AND campaign_id=?",
        (utcnow(), goal_id, cid))
    db.log_event(cid, "goal_abandoned", {"goal_id": goal_id})
    return goal_view(goal_id)


def auto_credit(cid: str, kind: str, reason: str) -> None:
    """Engine events credit matching open goals (deterministic, evidence-based)."""
    for g in list_goals(cid):
        if g["status"] != "active":
            continue
        title = g["title"].lower()
        credit = 0
        if kind == "combat_victory" and ("foe" in title or "enemy" in title
                                         or "defeat" in title or "hunt" in title):
            credit = 1
        elif kind == "discovery" and ("discover" in title or "find" in title
                                      or "hidden" in title or "secret" in title):
            credit = 1
        elif kind == "quest_resolved" and ("quest" in title or "task" in title
                                           or "relic" in title or "recover" in title):
            credit = 1
        if credit:
            goal_progress(cid, g["id"], credit, reason=reason or kind, verified=True)


# ==========================================================================
# 9.2 — Campfire Stories
# ==========================================================================

def add_story(cid: str, author_player_id: str, author_name: str, kind: str,
              text: str, related_event_seq: int | None = None,
              share_refs: list | None = None) -> dict:
    """A player's retelling around the fire. Stored as PLAYER-AUTHORED: it is
    never treated as engine proof of an event (that boundary is explicit in
    the Ledger, where mechanical records stay marked as verified).

    Since hotfix 3, telling a story shares NOTHING by itself. When the teller
    explicitly selects knowledge to share (`share_refs`: place refs and/or
    specific memory ids they hold), share_knowledge validates every selection
    server-side and grants exactly those items to the party, reporting what
    was shared and what was refused."""
    if kind not in ("story", "memory", "memorial", "record", "goal_idea"):
        raise ValueError("story kind must be story, memory, memorial, record or goal_idea")
    text = (text or "").strip()[:1200]
    if not text:
        raise ValueError("the fire is listening — say something")
    sid = new_id("fire")
    share_report = None
    if share_refs is not None:
        try:
            teller = teller_character(cid, author_player_id)
            share_report = share_knowledge(cid, teller, share_refs,
                                           shared_by_player_id=author_player_id,
                                           story_id=sid)
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 — a story must never fail because sharing did
            share_report = {"shared": [], "granted": 0, "rejected": [
                {"ref": "*", "reason": f"knowledge sharing failed: {type(exc).__name__}"}]}
    db.execute(
        "INSERT INTO campfire_stories (id, campaign_id, author_player_id, author_name,"
        " kind, text, related_event_seq, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (sid, cid, author_player_id or "local", (author_name or "a traveler")[:40],
         kind, text, related_event_seq, utcnow()),
    )
    db.log_event(cid, "campfire_story", {"story_id": sid, "kind": kind,
                                         "author": author_name,
                                         "shared": (share_report or {}).get("shared", [])})
    story = story_view(sid)
    if share_report is not None:
        story["share"] = share_report
    return story


def story_view(story_id: str) -> dict:
    row = db.query_one("SELECT * FROM campfire_stories WHERE id=?", (story_id,))
    if not row:
        raise ValueError("no such story")
    return dict(row)


def list_stories(cid: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM campfire_stories WHERE campaign_id=? ORDER BY created_at DESC"
        " LIMIT 60", (cid,))]


# ==========================================================================
# 10 — What-If Timelines
# ==========================================================================

def branch_campaign(cid: str, checkpoint_id: str | None, name: str,
                    player_id: str = "local") -> dict:
    """Create an alternate timeline from a checkpoint (or the campaign's
    current state). The original campaign is untouched; the branch is a NEW
    campaign with its own identity, ownership, and event stream."""
    from . import gm
    if checkpoint_id:
        row = db.query_one(
            "SELECT export_json FROM campaign_checkpoints WHERE id=? AND campaign_id=?",
            (checkpoint_id, cid))
        if not row:
            raise ValueError("no such checkpoint on this campaign")
        data = jloads(row["export_json"], {})
    else:
        data = gm.export_campaign(cid)
    new_cid = gm.import_campaign(data)
    row = db.query_one("SELECT state_json, name FROM campaigns WHERE id=?", (new_cid,))
    st = jloads(row["state_json"], {})
    st["branched_from"] = cid
    st["branch_name"] = (name or "Alternate Timeline")[:80]
    st["branched_at"] = utcnow()
    st["branched_by"] = player_id
    db.execute("UPDATE campaigns SET state_json=?, name=? WHERE id=?",
               (jdumps(st), (f"{row['name']} · {st['branch_name']}")[:80], new_cid))
    db.log_event(new_cid, "timeline_branched", {"from": cid, "checkpoint": checkpoint_id})
    db.log_event(cid, "timeline_branched_from", {"branch": new_cid,
                                                 "name": st["branch_name"]})
    return {"campaign_id": new_cid, "branched_from": cid,
            "branch_name": st["branch_name"]}


def _campaign_snapshot(cid: str) -> dict:
    row = db.query_one("SELECT turn, state_json, name FROM campaigns WHERE id=?", (cid,))
    if not row:
        raise ValueError("campaign not found")
    st = jloads(row["state_json"], {})
    chars = db.query("SELECT name, vigor, data_json FROM characters WHERE campaign_id=?",
                     (cid,))
    inv = db.query("SELECT item_id, SUM(qty) q FROM inventory WHERE campaign_id=?"
                   " GROUP BY item_id", (cid,))
    try:
        rels = db.query("SELECT npc_id, rel FROM npc_rel WHERE campaign_id=?", (cid,))
    except Exception:
        rels = []
    rels = [dict(r) for r in rels if "npc_id" in r.keys() and "rel" in r.keys()]
    return {
        "name": row["name"],
        "turn": row["turn"],
        "endings_seen": st.get("endings_seen", []),
        "quests_done": sorted(q for q, s in (st.get("quests") or {}).items()
                              if s in ("done", True)),
        "characters": [{"name": ch["name"], "vigor": ch["vigor"],
                        "dead": bool(jloads(ch["data_json"], {}).get("dead"))}
                       for ch in chars],
        "inventory": {r["item_id"]: r["q"] for r in inv},
        "relationships": {r["npc_id"]: r["rel"] for r in rels},
        "discoveries": [e for e in db.query(
            "SELECT data_json FROM mp_events WHERE campaign_id=? AND type='discovery'",
            (cid,))],
    }


def compare_timelines(cid_a: str, cid_b: str) -> dict:
    """Meaningful differences between two branches, from actual snapshots."""
    a, b = _campaign_snapshot(cid_a), _campaign_snapshot(cid_b)
    name_a = db.query_one("SELECT name FROM campaigns WHERE id=?", (cid_a,))["name"]
    name_b = db.query_one("SELECT name FROM campaigns WHERE id=?", (cid_b,))["name"]
    diffs: list[dict] = []
    for e in sorted(set(a["endings_seen"]) | set(b["endings_seen"])):
        diffs.append({"kind": "ending", "detail": e,
                      "a": e in a["endings_seen"], "b": e in b["endings_seen"]})
    for q in sorted(set(a["quests_done"]) | set(b["quests_done"])):
        if (q in a["quests_done"]) != (q in b["quests_done"]):
            diffs.append({"kind": "quest", "detail": q,
                          "a": q in a["quests_done"], "b": q in b["quests_done"]})
    for ch in a["characters"]:
        twin = next((x for x in b["characters"] if x["name"] == ch["name"]), None)
        if twin and (twin.get("dead") != ch.get("dead")
                     or twin.get("vigor") != ch.get("vigor")):
            diffs.append({"kind": "character", "detail":
                          f"{ch['name']}: vigor {ch['vigor']} vs {twin['vigor']}"
                          + (", fate differs" if twin.get("dead") != ch.get("dead") else ""),
                          "a": not ch.get("dead"), "b": not twin.get("dead")})
    for item in sorted(set(a["inventory"]) | set(b["inventory"])):
        qa, qb = a["inventory"].get(item, 0), b["inventory"].get(item, 0)
        if qa != qb:
            diffs.append({"kind": "inventory", "detail": f"{item}: {qa} → {qb}",
                          "a": qa > 0, "b": qb > 0})
    for npc in sorted(set(a["relationships"]) | set(b["relationships"])):
        ra, rb = a["relationships"].get(npc), b["relationships"].get(npc)
        if ra != rb:
            npc_name = _npc_name(cid_a, npc)
            diffs.append({"kind": "relationship",
                          "detail": f"{npc_name}: {ra} → {rb}", "a": None, "b": None})
    diffs.append({"kind": "turn", "detail": f"{a['turn']} vs {b['turn']} turns",
                  "a": a["turn"], "b": b["turn"]})
    return {"a": {"campaign_id": cid_a, "name": name_a},
            "b": {"campaign_id": cid_b, "name": name_b},
            "diffs": diffs}


def _npc_name(cid: str, npc_id: str) -> str:
    row = db.query_one("SELECT name FROM npcs WHERE campaign_id=? AND npc_id=?",
                       (cid, npc_id))
    return row["name"] if row else npc_id


def list_branches(cid: str) -> list[dict]:
    """All timelines branched from this campaign (and the root, if any)."""
    out = []
    for r in db.query("SELECT id, name, state_json FROM campaigns"):
        st = jloads(r["state_json"], {})
        if st.get("branched_from") == cid:
            out.append({"campaign_id": r["id"], "name": r["name"],
                        "branch_name": st.get("branch_name"),
                        "branched_at": st.get("branched_at")})
    return out
