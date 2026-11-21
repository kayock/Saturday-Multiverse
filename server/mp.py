"""Saturday Multiverse — The Shared Shore (multiplayer engine).

Host-authoritative by construction:

- Every multiplayer request carries a session token; the server resolves it
  to a player row (SHA-256 hash at rest) and enforces ownership before any
  engine call. Raw tokens exist once, in the join response.
- The party shares ONE campaign: one location, one adventure beat, one
  history. Movement is a party decision (proposed, voted, executed once).
- Per-character state (vigor, nerve, beads, inventory, omen hand, pending
  rolls, death) belongs to each player's character and is validated here.
- The host's AI configuration serves everyone; guests never receive it.
- Every significant action is appended to `mp_events` with a durable
  sequence number; clients reconnect with `?last_seq=N` and replay exactly
  what they missed. Retries cannot duplicate rewards: the actions themselves
  are engine-guarded, and the event stream is append-only.
- A per-campaign re-entrant lock serializes actions and AI narration so
  concurrent intents resolve in a single, consistent order.

The AI Game Master may narrate any of this; it never decides any of it.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque, defaultdict
from contextlib import contextmanager

from . import db, gm, worldpacks
from .db import jdumps, jloads, new_id, utcnow

PRESENCE_TIMEOUT = 45          # seconds without contact -> offline
CHAT_LIMIT = 10                # messages per chat window
CHAT_WINDOW = 30.0             # seconds
TURN_TIMEOUT = 240             # default structured-turn timeout (seconds)
TRADE_TTL = 600                # unaccepted offers expire after this
TICKET_TTL = 60                # one-time SSE stream tickets
PLAYER_COLORS = ["#7c5cff", "#43e8d8", "#e8b46b", "#ff5cc8", "#8fdc74", "#6fa8ff"]

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_TICKETS: dict[str, tuple[str, str, float]] = {}
_TICKETS_GUARD = threading.Lock()
_CHAT_TIMES: dict[str, deque] = defaultdict(deque)
_CHAT_GUARD = threading.Lock()


class MpError(ValueError):
    """Raised for player-facing multiplayer failures (maps to HTTP 400)."""


class MpDenied(PermissionError):
    """Raised when a token is missing/invalid/forbidden (maps to HTTP 403)."""


@contextmanager
def session_lock(cid: str):
    """Serialize every authoritative action for one campaign."""
    with _LOCKS_GUARD:
        if cid not in _LOCKS:
            _LOCKS[cid] = threading.RLock()
    with _LOCKS[cid]:
        yield


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _session(cid: str):
    return db.query_one("SELECT * FROM mp_sessions WHERE campaign_id=?", (cid,))


def _player_by_token(cid: str, token: str):
    if not token:
        return None
    row = db.query_one(
        "SELECT * FROM mp_players WHERE campaign_id=? AND token_hash=?",
        (cid, hash_token(str(token))),
    )
    return row


def _connected_players(cid: str) -> list:
    return [dict(r) for r in db.query(
        "SELECT * FROM mp_players WHERE campaign_id=? AND status IN ('connected','pending')"
        " ORDER BY joined_at", (cid,)
    )]


def _active_players(cid: str) -> list:
    return [dict(r) for r in db.query(
        "SELECT * FROM mp_players WHERE campaign_id=? AND status IN ('connected','offline')",
        (cid,),
    )]


# ==========================================================================
# Events (durable, sequenced, permission-filtered)
# ==========================================================================

def emit(cid: str, etype: str, actor: str | None, data: dict | None = None,
         visibility: str = "party") -> int:
    db.execute(
        "INSERT INTO mp_events (campaign_id, ts, type, actor, visibility, data_json)"
        " VALUES (?,?,?,?,?,?)",
        (cid, utcnow(), etype[:40], actor, visibility[:30], jdumps(data or {})),
    )
    row = db.query_one("SELECT MAX(seq) AS s FROM mp_events WHERE campaign_id=?", (cid,))
    return int(row["s"]) if row else 0


def events_since(cid: str, last_seq: int, player: dict | None = None) -> list[dict]:
    """Replay events this player is permitted to see, in order."""
    rows = db.query(
        "SELECT seq, ts, type, actor, visibility, data_json FROM mp_events"
        " WHERE campaign_id=? AND seq>? ORDER BY seq LIMIT 500",
        (cid, max(0, int(last_seq))),
    )
    out = []
    for r in rows:
        vis = r["visibility"]
        allowed = (
            vis == "party"
            or (player and vis == f"player:{player['id']}")
            or (player and bool(player["is_host"]) and vis == "host")
        )
        if not allowed:
            continue
        out.append({
            "seq": r["seq"], "ts": r["ts"], "type": r["type"], "actor": r["actor"],
            "data": jloads(r["data_json"], {}),
        })
    return out


def latest_seq(cid: str) -> int:
    row = db.query_one("SELECT MAX(seq) AS s FROM mp_events WHERE campaign_id=?", (cid,))
    return int(row["s"] or 0)


# ==========================================================================
# Presence
# ==========================================================================

def _iso_to_ts(s: str) -> float:
    try:
        import datetime as _dt
        return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc).timestamp()
    except Exception:
        return 0.0


def touch(player: dict) -> None:
    db.execute("UPDATE mp_players SET last_seen=?, status=CASE WHEN status='offline'"
               " THEN 'connected' ELSE status END WHERE id=?",
               (utcnow(), player["id"]))


def sweep_presence(cid: str) -> list[str]:
    """Mark silent players offline; returns names that just left."""
    now = time.time()
    left = []
    for r in db.query("SELECT * FROM mp_players WHERE campaign_id=? AND status='connected'", (cid,)):
        if now - _iso_to_ts(r["last_seen"]) > PRESENCE_TIMEOUT:
            db.execute("UPDATE mp_players SET status='offline' WHERE id=?", (r["id"],))
            emit(cid, "presence", "system",
                 {"player_id": r["id"], "name": r["display_name"], "status": "offline"})
            left.append(r["display_name"])
    return left


# ==========================================================================
# Sessions, invitations, joining
# ==========================================================================

def host_session(cid: str, display_name: str, character_spec: dict | None = None) -> dict:
    """The host opens (or reopens) a shared session on a campaign and joins it
    as the first player. An existing solo character is adopted by the host."""
    campaign = gm.get_campaign(cid)
    if not campaign:
        raise MpError("campaign not found")
    display_name = _clean_name(display_name)
    with session_lock(cid):
        session = _session(cid)
        if session and session["status"] == "ended":
            raise MpError("this voyage has already ended — start a new one")
        if not session:
            db.execute(
                "INSERT INTO mp_sessions (campaign_id, status, mode, player_limit, settings_json,"
                " created_at, updated_at) VALUES (?, 'lobby', 'freeform', 6, '{}', ?, ?)",
                (cid, utcnow(), utcnow()),
            )
        token = _new_token()
        # the host hosting again simply gets a fresh token for their row
        prior = db.query_one(
            "SELECT * FROM mp_players WHERE campaign_id=? AND display_name=? COLLATE NOCASE",
            (cid, display_name),
        )
        if prior and prior["status"] not in ("banned", "removed"):
            db.execute(
                "UPDATE mp_players SET token_hash=?, is_host=1, status='connected',"
                " last_seen=? WHERE id=?",
                (hash_token(token), utcnow(), prior["id"]),
            )
            emit(cid, "presence", "system",
                 {"player_id": prior["id"], "name": display_name, "status": "connected"})
            return {"campaign_id": cid, "player_id": prior["id"], "token": token}
        pid = new_id("pmp")
        existing = db.query_one(
            "SELECT id FROM characters WHERE campaign_id=? ORDER BY rowid LIMIT 1", (cid,)
        )
        adopt = bool(existing) and (character_spec is None or not character_spec.get("create_new"))
        if adopt:
            chid = existing["id"]
            db.log_event(cid, "character_adopted", {"character_id": chid, "by": display_name})
        else:
            chid = gm.create_character(cid, character_spec or {})
        db.execute(
            "INSERT INTO mp_players (id, campaign_id, token_hash, display_name, character_id,"
            " is_host, ready, status, joined_at, last_seen, data_json)"
            " VALUES (?,?,?,?,?,1,0,'connected',?,?,?)",
            (pid, cid, hash_token(token), display_name, chid, utcnow(), utcnow(),
             jdumps({"color": PLAYER_COLORS[0]})),
        )
        emit(cid, "presence", "system",
             {"player_id": pid, "name": display_name, "status": "connected", "host": True})
        db.log_event(cid, "mp_hosted", {"player_id": pid, "name": display_name})
        return {"campaign_id": cid, "player_id": pid, "token": token}


def create_invite(cid: str, player: dict, label: str = "", uses: int = 0,
                  expires_sec: int | None = 86400 * 14) -> dict:
    require_host(player)
    token = _new_token()
    import datetime as _dt
    expires = None
    if expires_sec:
        expires = (_dt.datetime.now(_dt.timezone.utc)
                   + _dt.timedelta(seconds=int(expires_sec))).strftime("%Y-%m-%dT%H:%M:%SZ")
    iid = new_id("inv")
    stored_uses = max(1, int(uses)) if int(uses) > 0 else -1  # -1 = unlimited
    db.execute(
        "INSERT INTO mp_invites (id, campaign_id, token_hash, label, uses_left, expires_at, revoked,"
        " created_at) VALUES (?,?,?,?,?,?,0,?)",
        (iid, cid, hash_token(token), label[:60], stored_uses, expires, utcnow()),
    )
    db.log_event(cid, "mp_invite_created", {"invite_id": iid, "uses": uses})
    return {"invite_id": iid, "token": token, "expires_at": expires, "uses_left": int(uses)}


def _clean_name(name: str) -> str:
    cleaned = "".join(ch for ch in (name or "").strip() if ch.isprintable())[:24]
    if not cleaned:
        raise MpError("a display name is needed to step onto the shore")
    return cleaned


def join(cid: str, invite_token: str, display_name: str, character_spec: dict | None) -> dict:
    """A friend follows an invitation link: name, character, shore."""
    campaign = gm.get_campaign(cid)
    if not campaign:
        raise MpError("campaign not found")
    display_name = _clean_name(display_name)
    with session_lock(cid):
        session = _session(cid)
        if not session:
            raise MpError("no shared voyage is open on this shore")
        if session["status"] in ("ended",):
            raise MpError("this voyage has already ended")
        row = db.query_one(
            "SELECT * FROM mp_invites WHERE campaign_id=? AND token_hash=?",
            (cid, hash_token(str(invite_token))),
        )
        if not row:
            raise MpDenied("that invitation is not valid")
        if row["revoked"]:
            raise MpDenied("that invitation was revoked")
        if row["expires_at"] and row["expires_at"] < utcnow():
            raise MpDenied("that invitation has expired")
        if row["uses_left"] >= 0 and row["uses_left"] <= 0:
            raise MpDenied("that invitation has no uses left")
        if row["uses_left"] > 0:
            db.execute("UPDATE mp_invites SET uses_left=? WHERE id=?",
                       (row["uses_left"] - 1, row["id"]))
        if db.query_one(
            "SELECT 1 FROM mp_players WHERE campaign_id=? AND display_name=? COLLATE NOCASE"
            " AND status IN ('connected','offline','pending')", (cid, display_name),
        ):
            raise MpError("that name is already on the shore — pick another")
        taken = len(_active_players(cid))
        limit = int(session["player_limit"])
        if taken >= limit:
            raise MpError(f"the party is full ({limit} travelers)")
        settings = jloads(session["settings_json"], {})
        token = _new_token()
        pid = new_id("pmp")
        spec = character_spec or {}
        if not spec.get("name"):
            spec = {"name": display_name, "archetype": "warden", "specialty": "fight",
                    "portrait_seed": display_name}
        chid = gm.create_character(cid, spec)
        status = "pending" if settings.get("approve_join") else "connected"
        color = PLAYER_COLORS[taken % len(PLAYER_COLORS)]
        db.execute(
            "INSERT INTO mp_players (id, campaign_id, token_hash, display_name, character_id,"
            " is_host, ready, status, joined_at, last_seen, data_json)"
            " VALUES (?,?,?,?,?,0,0,?,?,?,?)",
            (pid, cid, hash_token(token), display_name, chid, status, utcnow(), utcnow(),
             jdumps({"color": color})),
        )
        emit(cid, "presence", "system",
             {"player_id": pid, "name": display_name, "status": status})
        if status == "connected":
            emit(cid, "system", "system", {"text": f"{display_name} steps out of the sea-foam."})
        db.log_event(cid, "mp_joined", {"player_id": pid, "name": display_name})
        return {"campaign_id": cid, "player_id": pid, "token": token, "status": status}


def auth(cid: str, token: str, allow_pending: bool = False) -> dict:
    """Resolve a session token to a player row; refresh presence."""
    player = _player_by_token(cid, token)
    if not player:
        raise MpDenied("you are not part of this voyage")
    if player["status"] == "banned":
        raise MpDenied("you can no longer join this shore")
    if player["status"] == "removed":
        raise MpDenied("you were asked to leave this voyage")
    if player["status"] == "pending" and not allow_pending:
        raise MpDenied("waiting for the host to welcome you")
    if player["status"] == "offline":
        db.execute("UPDATE mp_players SET status='connected' WHERE id=?", (player["id"],))
        emit(cid, "presence", "system",
             {"player_id": player["id"], "name": player["display_name"], "status": "connected"})
        player = dict(db.query_one("SELECT * FROM mp_players WHERE id=?", (player["id"],)))
    touch(player)
    return dict(player)


def require_host(player: dict) -> None:
    if not player or not player["is_host"]:
        raise MpDenied("only the host may do that")


# ==========================================================================
# Lobby / session control
# ==========================================================================

def party_members(cid: str) -> list[dict]:
    out = []
    for r in db.query(
        "SELECT * FROM mp_players WHERE campaign_id=? AND status IN"
        " ('connected','offline','pending') ORDER BY joined_at", (cid,),
    ):
        ch = db.query_one("SELECT * FROM characters WHERE id=?", (r["character_id"] or "",))
        data = jloads(r["data_json"], {})
        now = time.time()
        live = (r["status"] == "connected"
                and now - _iso_to_ts(r["last_seen"]) <= PRESENCE_TIMEOUT)
        out.append({
            "player_id": r["id"], "name": r["display_name"],
            "is_host": bool(r["is_host"]), "ready": bool(r["ready"]),
            "status": r["status"], "presence": "connected" if live else r["status"],
            "color": data.get("color", "#9b8cff"),
            "character": ({
                "id": ch["id"], "name": ch["name"], "archetype": ch["archetype"],
                "vigor": ch["vigor"], "vigor_max": ch["vigor_max"],
                "nerve": ch["nerve"], "nerve_max": ch["nerve_max"],
                "portrait": jloads(ch["portrait_json"], {}),
                "dead": bool(gm.ch_get(gm.get_character(cid, ch["id"]), "dead", False)),
            } if ch else None),
        })
    return out


def set_ready(cid: str, player: dict, ready: bool) -> None:
    db.execute("UPDATE mp_players SET ready=? WHERE id=?", (1 if ready else 0, player["id"]))
    emit(cid, "ready", "system", {"player_id": player["id"], "name": player["display_name"],
                                  "ready": bool(ready)})


def start_session(cid: str, player: dict) -> None:
    require_host(player)
    session = _session(cid)
    if not session:
        raise MpError("no session to start")
    db.execute("UPDATE mp_sessions SET status='active', updated_at=? WHERE campaign_id=?",
               (utcnow(), cid))
    emit(cid, "system", "system", {"text": "The shared voyage begins. Welcome to the shore, travelers."})
    db.log_event(cid, "mp_started", {})


def session_control(cid: str, player: dict, action: str) -> dict:
    require_host(player)
    session = _session(cid)
    if not session:
        raise MpError("no session")
    if action == "pause":
        db.execute("UPDATE mp_sessions SET status='paused', updated_at=? WHERE campaign_id=?", (utcnow(), cid))
        emit(cid, "system", "system", {"text": "The host stills the shore. The voyage pauses."})
    elif action == "resume":
        db.execute("UPDATE mp_sessions SET status='active', updated_at=? WHERE campaign_id=?", (utcnow(), cid))
        emit(cid, "system", "system", {"text": "The tide resumes. The voyage continues."})
    elif action == "end":
        db.execute("UPDATE mp_sessions SET status='ended', updated_at=? WHERE campaign_id=?", (utcnow(), cid))
        emit(cid, "system", "system", {"text": "The host closes the voyage. The shore remembers it."})
    else:
        raise MpError("unknown session action")
    db.log_event(cid, f"mp_{action}", {})
    return {"status": action}


def set_mode(cid: str, player: dict, mode: str, turn_timeout: int | None = None) -> dict:
    require_host(player)
    if mode not in ("freeform", "turns"):
        raise MpError("mode must be freeform or turns")
    session = _session(cid)
    settings = jloads(session["settings_json"], {})
    settings["mode"] = mode
    if turn_timeout:
        settings["turn_timeout"] = max(30, min(1800, int(turn_timeout)))
    db.execute("UPDATE mp_sessions SET mode=?, settings_json=?, updated_at=? WHERE campaign_id=?",
               (mode, jdumps(settings), utcnow(), cid))
    if mode == "turns":
        _start_turn(cid)
    emit(cid, "system", "system", {"text": f"The shore now follows {mode} order."})
    return {"mode": mode}


def remove_player(cid: str, player: dict, target_id: str, ban: bool = False) -> None:
    require_host(player)
    target = db.query_one("SELECT * FROM mp_players WHERE campaign_id=? AND id=?", (cid, target_id))
    if not target:
        raise MpError("no such traveler")
    if target["is_host"]:
        raise MpDenied("the host cannot be removed")
    db.execute("UPDATE mp_players SET status=? WHERE id=?",
               ("banned" if ban else "removed", target_id))
    emit(cid, "system", "system", {
        "text": f"{target['display_name']} departs the shore{' — and may not return' if ban else ''}.",
        "player_id": target_id,
    })
    db.log_event(cid, "mp_removed", {"target": target_id, "ban": bool(ban)})


def approve_player(cid: str, player: dict, target_id: str) -> None:
    require_host(player)
    target = db.query_one("SELECT * FROM mp_players WHERE campaign_id=? AND id=?", (cid, target_id))
    if not target or target["status"] != "pending":
        raise MpError("no pending traveler by that id")
    db.execute("UPDATE mp_players SET status='connected' WHERE id=?", (target_id,))
    emit(cid, "presence", "system",
         {"player_id": target_id, "name": target["display_name"], "status": "connected"})
    emit(cid, "system", "system", {"text": f"{target['display_name']} is welcomed to the shore."})


def revoke_invite(cid: str, player: dict, invite_id: str) -> None:
    require_host(player)
    db.execute("UPDATE mp_invites SET revoked=1 WHERE campaign_id=? AND id=?", (cid, invite_id))
    db.log_event(cid, "mp_invite_revoked", {"invite_id": invite_id})


def list_invites(cid: str, player: dict) -> list[dict]:
    require_host(player)
    rows = db.query(
        "SELECT id, label, uses_left, expires_at, revoked, created_at FROM mp_invites"
        " WHERE campaign_id=? ORDER BY created_at DESC", (cid,),
    )
    return [dict(r) for r in rows]


# ==========================================================================
# Turn order (structured mode)
# ==========================================================================

def _settings(cid: str) -> dict:
    session = _session(cid)
    return jloads(session["settings_json"], {}) if session else {}


def _save_settings(cid: str, settings: dict) -> None:
    db.execute("UPDATE mp_sessions SET settings_json=?, updated_at=? WHERE campaign_id=?",
               (jdumps(settings), utcnow(), cid))


def _order(cid: str) -> list[dict]:
    return [p for p in _connected_players(cid) if p["status"] == "connected"]


def _start_turn(cid: str) -> None:
    settings = _settings(cid)
    queue = _order(cid)
    if queue:
        settings["turn_player"] = queue[0]["id"]
        settings["turn_started_at"] = time.time()
    else:
        settings["turn_player"] = None
    _save_settings(cid, settings)
    if settings.get("turn_player"):
        p = db.query_one("SELECT display_name FROM mp_players WHERE id=?", (settings["turn_player"],))
        emit(cid, "turn", "system", {"player_id": settings["turn_player"], "name": p["display_name"]})


def enforce_turn(cid: str, player: dict) -> None:
    """In structured mode, only the current player acts. Timed-out turns
    auto-advance to the next connected traveler."""
    session = _session(cid)
    if not session or session["mode"] != "turns" or session["status"] != "active":
        return
    settings = _settings(cid)
    current = settings.get("turn_player")
    timeout = int(settings.get("turn_timeout", TURN_TIMEOUT))
    started = float(settings.get("turn_started_at", 0) or 0)
    expired = current and (time.time() - started) > timeout
    stale = current and not any(p["id"] == current for p in _order(cid))
    if current is None or expired or stale:
        _start_turn(cid)
        settings = _settings(cid)
        current = settings.get("turn_player")
    if current and current != player["id"] and not player["is_host"]:
        p = db.query_one("SELECT display_name FROM mp_players WHERE id=?", (current,))
        who = p["display_name"] if p else "another traveler"
        raise MpError(f"the shore listens to {who} right now — your turn will come")


def advance_turn(cid: str, player: dict) -> None:
    session = _session(cid)
    if not session:
        raise MpError("no session")
    if not (player["is_host"] or player["id"] == _settings(cid).get("turn_player")):
        raise MpDenied("only the host or the current traveler may pass the lantern")
    _start_turn(cid)


# ==========================================================================
# Chat
# ==========================================================================

def chat(cid: str, player: dict, text: str) -> dict:
    text = "".join(ch for ch in (text or "").strip() if ch.isprintable())[:400]
    if not text:
        raise MpError("say something first")
    now = time.time()
    with _CHAT_GUARD:
        times = _CHAT_TIMES[player["id"]]
        while times and now - times[0] > CHAT_WINDOW:
            times.popleft()
        if len(times) >= CHAT_LIMIT:
            raise MpError("the shore needs a breath — slow down a little")
        times.append(now)
    data = {"name": player["display_name"], "text": text,
            "color": jloads(player["data_json"], {}).get("color", "#9b8cff"),
            "character": None}
    ch = db.query_one("SELECT name FROM characters WHERE id=?", (player["character_id"] or "",))
    if ch:
        data["character"] = ch["name"]
    emit(cid, "chat", player["id"], data)
    return data


# ==========================================================================
# Player-to-player interactions: trades, gifts, clue sharing
# ==========================================================================

def _state_mutate(cid: str, mutator) -> dict:
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    mutator(state)
    db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
               (jdumps(state), utcnow(), cid))
    return state


def propose_trade(cid: str, player: dict, to_player_id: str, item_row_id: str, qty: int) -> dict:
    ch = gm.get_character(cid, player["character_id"])
    row = db.query_one(
        "SELECT * FROM inventory WHERE campaign_id=? AND id=? AND character_id=?",
        (cid, str(item_row_id), ch["id"]),
    )
    if not row:
        raise MpError("that item is not in your pack")
    qty = max(1, min(int(qty), row["qty"]))
    target = db.query_one(
        "SELECT * FROM mp_players WHERE campaign_id=? AND id=? AND status IN ('connected','offline')",
        (cid, to_player_id),
    )
    if not target or target["id"] == player["id"]:
        raise MpError("choose a fellow traveler")

    def mut(state):
        offers = state.setdefault("mp_trades", [])
        offers[:] = [o for o in offers if o["ts"] > _cutoff()]
        offers.append({
            "id": new_id("trd"), "from_pid": player["id"], "from_name": player["display_name"],
            "to_pid": target["id"], "item_row_id": row["id"], "item_id": row["item_id"],
            "item_name": row["name"], "qty": qty, "ts": time.time(),
        })
    _state_mutate(cid, mut)
    emit(cid, "trade_offer", player["id"],
         {"offer_id": None, "from": player["display_name"], "to": target["display_name"],
          "item": row["name"], "qty": qty},
         visibility=f"player:{target['id']}")
    return {"narration": f"Offered {row['name']} ×{qty} to {target['display_name']}."}


def _cutoff() -> float:
    return time.time() - TRADE_TTL


def respond_trade(cid: str, player: dict, offer_id: str, accept: bool) -> dict:
    """Answer a trade offer. The move itself is atomic under the session lock:
    the item must still belong to the offerer when the answer lands."""
    with session_lock(cid):
        state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
        offers = state.get("mp_trades", [])
        offer = next((o for o in offers if o["id"] == offer_id), None)
        if not offer:
            raise MpError("that offer is gone")
        if offer["to_pid"] != player["id"]:
            raise MpDenied("that offer is not yours to answer")
        if accept:
            row = db.query_one(
                "SELECT * FROM inventory WHERE campaign_id=? AND id=?",
                (cid, offer["item_row_id"]),
            )
            if not row or (row["character_id"] or "") != _char_of(cid, offer["from_pid"]) \
                    or row["qty"] < offer["qty"]:
                raise MpError("the offerer no longer holds that item")
            _move_item(cid, row, _char_of(cid, player["id"]), offer["qty"])
        offers[:] = [o for o in offers if o["id"] != offer_id]
        state["mp_trades"] = offers
        db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
                   (jdumps(state), utcnow(), cid))
        verb = "accepted" if accept else "declined"
        emit(cid, "system", "system", {
            "text": f"{player['display_name']} {verb} {offer['from_name']}'s offer of "
                    f"{offer['item_name']} ×{offer['qty']}."})
        db.log_event(cid, "mp_trade", {"offer": offer_id, "accepted": bool(accept),
                                       "item": offer["item_id"], "qty": offer["qty"]})
        return {"narration": f"You {verb} the offer."}


def _char_of(cid: str, player_id: str) -> str:
    r = db.query_one("SELECT character_id FROM mp_players WHERE campaign_id=? AND id=?",
                     (cid, player_id))
    return (r["character_id"] or "") if r else ""


def _move_item(cid: str, row, to_character_id: str, qty: int) -> None:
    """Atomic inventory transfer between characters (split/merge aware)."""
    if row["qty"] - qty <= 0:
        db.execute("UPDATE inventory SET character_id=? WHERE id=?", (to_character_id, row["id"]))
    else:
        db.execute("UPDATE inventory SET qty=? WHERE id=?", (row["qty"] - qty, row["id"]))
        dest = db.query_one(
            "SELECT id, qty FROM inventory WHERE campaign_id=? AND item_id=? AND character_id=?",
            (cid, row["item_id"], to_character_id),
        )
        if dest:
            db.execute("UPDATE inventory SET qty=? WHERE id=?", (min(9, dest["qty"] + qty), dest["id"]))
        else:
            db.execute(
                "INSERT INTO inventory (id, campaign_id, character_id, item_id, name, kind, qty,"
                " equipped, data_json) VALUES (?,?,?,?,?,?,?,0,?)",
                (new_id("itm"), cid, to_character_id, row["item_id"], row["name"], row["kind"],
                 qty, row["data_json"]),
            )


def gift_beads(cid: str, player: dict, to_player_id: str, amount: int) -> dict:
    amount = int(amount)
    if not 1 <= amount <= 10:
        raise MpError("a gift is between 1 and 10 glassbeads")
    target = db.query_one(
        "SELECT * FROM mp_players WHERE campaign_id=? AND id=? AND status IN ('connected','offline')",
        (cid, to_player_id),
    )
    if not target or target["id"] == player["id"]:
        raise MpError("choose a fellow traveler")
    with session_lock(cid):
        sender = gm.get_character(cid, player["character_id"])
        purse = int(gm.ch_get(sender, "beads", 0))
        if purse < amount:
            raise MpError(f"your purse holds {purse} glassbeads")
        gm.ch_set(sender, "beads", purse - amount)
        receiver = gm.get_character(cid, _char_of(cid, target["id"]))
        gm.ch_set(receiver, "beads", int(gm.ch_get(receiver, "beads", 0)) + amount)
    emit(cid, "system", "system", {
        "text": f"{player['display_name']} presses {amount} glassbead{'s' if amount != 1 else ''}"
                f" into {target['display_name']}'s hand."})
    db.log_event(cid, "mp_gift", {"from": player["id"], "to": target["id"], "amount": amount})
    return {"narration": f"Given. Your purse holds {purse - amount} glassbeads."}


def share_clue(cid: str, player: dict, thread_id: str) -> dict:
    ch = gm.get_character(cid, player["character_id"])
    row = db.query_one(
        "SELECT id, thread_id, text FROM clues WHERE campaign_id=? AND thread_id=? AND shared=0"
        " ORDER BY rowid LIMIT 1", (cid, thread_id),
    )
    if not row:
        raise MpError("no unshared clue on that thread")
    db.execute("UPDATE clues SET shared=1 WHERE id=?", (row["id"],))
    emit(cid, "system", "system", {
        "text": f"{ch['name']} shares a thread of {thread_id.replace('_', ' ')} with the party: “{row['text']}”"})
    db.log_event(cid, "mp_clue_shared", {"thread": thread_id, "by": ch["id"]})
    return {"narration": "The party leans in as you share it."}


def pending_offers(cid: str, player: dict) -> list[dict]:
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    cutoff = _cutoff()
    return [o for o in state.get("mp_trades", [])
            if o["to_pid"] == player["id"] and o["ts"] > cutoff]


# ==========================================================================
# Shared shore improvements (contributions) & party travel
# ==========================================================================

def contribute(cid: str, player: dict, upgrade_id: str, amount: int) -> dict:
    from .legacy import UPGRADES, owned_upgrades
    if upgrade_id not in UPGRADES:
        raise MpError("no such improvement")
    if upgrade_id in owned_upgrades(cid):
        raise MpError("already built")
    amount = int(amount)
    if not 1 <= amount <= 10:
        raise MpError("contribute between 1 and 10 glassbeads")
    ch = gm.get_character(cid, player["character_id"])
    purse = int(gm.ch_get(ch, "beads", 0))
    if purse < amount:
        raise MpError(f"your purse holds {purse} glassbeads")
    with session_lock(cid):
        if upgrade_id in owned_upgrades(cid):
            raise MpError("already built")
        gm.ch_set(ch, "beads", purse - amount)

        def mut(state):
            pot = state.setdefault("mp_contribs", {}).setdefault(upgrade_id, {})
            pot[player["id"]] = pot.get(player["id"], 0) + amount
        state = _state_mutate(cid, mut)
        pot = state.get("mp_contribs", {}).get(upgrade_id, {})
        total = sum(pot.values())
        cost = UPGRADES[upgrade_id]["cost"]
        if total >= cost and campaign_location_is(cid, UPGRADES[upgrade_id]["location"]):
            # the pot buys it: no further charge, contributions were escrowed
            db.execute("INSERT INTO upgrades (campaign_id, upgrade_id, purchased_at)"
                       " VALUES (?,?,?)", (cid, upgrade_id, utcnow()))
            flags = set(state.get("flags", []))
            flags.add(f"up_{upgrade_id}")
            _state_mutate(cid, lambda s: s.__setitem__("flags", sorted(flags)))
            db.log_event(cid, "upgrade", {"upgrade_id": upgrade_id, "cost": cost, "from_pot": True})
            remember(cid, "all", "event", f"The shore grew: {UPGRADES[upgrade_id]['name']} was built.")
            emit(cid, "system", "system",
                 {"text": f"The party raises {UPGRADES[upgrade_id]['name']} together ({total} glassbeads)."})
            # clear the (now spent) pot
            _state_mutate(cid, lambda s: s.get("mp_contribs", {}).pop(upgrade_id, None))
    emit(cid, "system", "system", {
        "text": f"{player['display_name']} adds {amount} glassbead{'s' if amount != 1 else ''}"
                f" toward {UPGRADES[upgrade_id]['name']} ({total}/{cost} in the pot)."})
    db.log_event(cid, "mp_contribute", {"upgrade_id": upgrade_id, "amount": amount,
                                        "by": player["id"]})
    return {"narration": f"Laid among the stones. The pot holds {total} of {cost}."}


def campaign_location_is(cid: str, loc_id: str) -> bool:
    row = db.query_one("SELECT location_id FROM campaigns WHERE id=?", (cid,))
    return bool(row and row["location_id"] == loc_id)


def propose_travel(cid: str, player: dict, destination: str) -> dict:
    """One player proposes a door; the whole party must agree."""
    with session_lock(cid):
        state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
        existing = state.get("mp_travel")
        if existing and existing.get("destination") == destination:
            return vote_travel(cid, player, True)
        # validate the destination through the engine's resolver
        pack = worldpacks.load_pack(gm.get_campaign(cid)["pack_id"])
        loc, _world = gm._resolve_location(cid, pack, destination)
        if not loc:
            raise MpError("unknown location")
        state["mp_travel"] = {
            "destination": destination, "name": loc.get("name", destination),
            "by_pid": player["id"], "by_name": player["display_name"],
            "votes": {player["id"]: True}, "ts": time.time(),
        }
        db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
                   (jdumps(state), utcnow(), cid))
        emit(cid, "travel_proposal", player["id"], {
            "destination": destination, "name": loc.get("name", destination),
            "by": player["display_name"]})
        return _maybe_execute_travel(cid, player)


def vote_travel(cid: str, player: dict, accept: bool) -> dict:
    with session_lock(cid):
        state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
        prop = state.get("mp_travel")
        if not prop:
            raise MpError("no journey is proposed")
        if player["id"] == prop.get("by_pid"):
            if not accept:
                state["mp_travel"] = None
                db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
                emit(cid, "system", "system", {"text": f"{player['display_name']} withdraws the proposal."})
                return {"narration": "Proposal withdrawn."}
            return _maybe_execute_travel(cid, player)
        prop["votes"][player["id"]] = bool(accept)
        db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
                   (jdumps(state), utcnow(), cid))
        if not accept:
            state["mp_travel"] = None
            db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
            emit(cid, "system", "system", {"text": f"{player['display_name']} declines the journey — it is called off."})
            return {"narration": "The journey is called off."}
        return _maybe_execute_travel(cid, player)


def _maybe_execute_travel(cid: str, player: dict) -> dict:
    """Depart when every connected traveler has agreed."""
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    prop = state.get("mp_travel")
    if not prop:
        return {"narration": "The journey stands ready."}
    voters = [p for p in _order(cid)]
    missing = [p["display_name"] for p in voters if p["id"] not in prop["votes"]]
    if missing:
        return {"narration": f"The door waits for: {', '.join(missing)}."}
    destination = prop["destination"]
    by_name = prop.get("by_name", "someone")
    state["mp_travel"] = None
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
    result = gm.travel(cid, destination)
    emit(cid, "travel", player["id"], {
        "location": destination, "name": prop.get("name", ""),
        "by": by_name, "narration": result.get("narration", ""),
        "changes": result.get("changes", [])})
    emit(cid, "system", "system", {"text": f"The party passes through together, led by {by_name}."})
    return {"narration": result.get("narration", ""), "changes": result.get("changes", []),
            "location": destination}


def force_travel(cid: str, player: dict, destination: str) -> dict:
    """Host prerogative: move the party without a vote."""
    require_host(player)
    result = gm.travel(cid, destination)
    emit(cid, "travel", player["id"], {"location": destination,
                                       "narration": result.get("narration", ""),
                                       "changes": result.get("changes", [])})
    return result


def current_proposal(cid: str) -> dict | None:
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    prop = state.get("mp_travel")
    if not prop:
        return None
    conn = [p["display_name"] for p in _order(cid)]
    return {"destination": prop["destination"], "name": prop.get("name", ""),
            "by": prop.get("by_name", ""), "votes": list(prop["votes"].keys()),
            "waiting_for": [n for n in conn if n not in
                            [db.query_one("SELECT display_name FROM mp_players WHERE id=?", (pid,))["display_name"]
                             for pid in prop["votes"]]]}


# ==========================================================================
# Party memories
# ==========================================================================

def record_party_moment(cid: str, adventure: str, ending_id: str, names: list[str]) -> None:
    """An adventure ended while a party shared the shore. The multiverse
    remembers the company, not just the wanderer."""
    if not _session(cid) or not names:
        return
    summary = (f"The company of {', '.join(names)} ended {adventure} ({ending_id.replace('_', ' ')}).")
    register = _register_party_consequence
    register(cid, f"party:{adventure}:{ending_id}", summary)
    remember(cid, "tavern", "ending", summary)


def _register_party_consequence(cid: str, trigger: str, summary: str) -> None:
    from .legacy import register_consequence
    register_consequence(cid, trigger, summary, {})


def remember(cid: str, scope: str, kind: str, text: str) -> None:
    from .legacy import remember as legacy_remember
    legacy_remember(cid, scope, kind, text)


# ==========================================================================
# Session view (lobby & in-game), stream tickets
# ==========================================================================

def session_view(cid: str, player: dict) -> dict:
    session = _session(cid)
    if not session:
        raise MpError("no shared voyage on this shore")
    sweep_presence(cid)
    settings = jloads(session["settings_json"], {})
    view = {
        "campaign_id": cid,
        "campaign_name": gm.get_campaign(cid)["name"],
        "status": session["status"],
        "mode": session["mode"],
        "player_limit": int(session["player_limit"]),
        "approve_join": bool(settings.get("approve_join")),
        "turn_timeout": int(settings.get("turn_timeout", TURN_TIMEOUT)),
        "members": party_members(cid),
        "you": {
            "player_id": player["id"], "name": player["display_name"],
            "is_host": bool(player["is_host"]), "ready": bool(player["ready"]),
            "character_id": player["character_id"],
            "color": jloads(player["data_json"], {}).get("color", "#9b8cff"),
        },
        "travel_proposal": current_proposal(cid),
        "offers_for_you": pending_offers(cid, player),
        "contribs": jloads(db.query_one(
            "SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {}
        ).get("mp_contribs", {}),
        "turn_player": settings.get("turn_player"),
        "latest_seq": latest_seq(cid),
    }
    chat_rows = db.query(
        "SELECT ts, type, actor, data_json FROM mp_events WHERE campaign_id=? AND type IN"
        " ('chat','system','presence','dice') ORDER BY seq DESC LIMIT 40", (cid,),
    )
    view["chat"] = [{
        "ts": r["ts"], "actor": r["actor"], "type": r["type"],
        "data": jloads(r["data_json"], {}),
    } for r in reversed(chat_rows)]
    if player["is_host"]:
        view["invites"] = list_invites(cid, player)
    return view


def session_view_pot(cid: str) -> dict:
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    return state.get("mp_contribs", {})


def new_stream_ticket(player: dict) -> str:
    ticket = secrets.token_urlsafe(24)
    with _TICKETS_GUARD:
        # one live ticket per player: issuing replaces the old one
        for t in [k for k, v in _TICKETS.items() if v[1] == player["id"]]:
            _TICKETS.pop(t, None)
        _TICKETS[ticket] = (player["campaign_id"], player["id"], time.time() + TICKET_TTL)
    return ticket


def pop_stream_ticket(ticket: str) -> tuple[str, str] | None:
    with _TICKETS_GUARD:
        entry = _TICKETS.pop(ticket, None)
    if not entry or entry[2] < time.time():
        return None
    return entry[0], entry[1]


def stream(cid: str, player: dict, last_seq: int):
    """SSE generator: replays missed events, then follows live. Also runs the
    presence sweep and structured-turn timeouts while anyone is watching."""
    yield f": shore stream open\n\n"
    seq = max(0, int(last_seq))
    last_beat = time.time()
    idle = 0
    while True:
        session = _session(cid)
        if not session or session["status"] == "ended":
            yield _sse({"type": "session_ended"})
            return
        for ev in events_since(cid, seq, player):
            seq = ev["seq"]
            yield _sse(ev)
        sweep_presence(cid)
        session = _session(cid)
        if session and session["mode"] == "turns" and session["status"] == "active":
            settings = _settings(cid)
            current = settings.get("turn_player")
            timeout = int(settings.get("turn_timeout", TURN_TIMEOUT))
            started = float(settings.get("turn_started_at", 0) or 0)
            if current and (time.time() - started) > timeout:
                _start_turn(cid)
        if time.time() - last_beat > 15:
            yield ": ping\n\n"
            last_beat = time.time()
        time.sleep(1.0)
        idle += 1
        if idle > 7200:   # ~2h: end the response; clients reconnect seamlessly
            return


def _sse(payload: dict) -> str:
    import json as _json
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
