"""Saturday Multiverse — REST API blueprint.

Solo-first, multiplayer-aware. Every campaign mutation is a single
authenticated request against host-authoritative state. When a campaign
carries a shared-shore session, the same endpoints accept an `X-MP-Token`
header, resolve the caller to a player row, and scope every change to that
player's character. Guests never see the host's AI configuration.
"""
from __future__ import annotations

import base64
import time
from collections import defaultdict, deque

import os
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from .db import jdumps, jloads, new_id, utcnow
from . import ai, config, continuity, db, experience, director, forge, gen, gm, legacy, library, mp, qr, rules_dnd, combat, worldpacks

api = Blueprint("api", __name__, url_prefix="/api")

_RATE: dict[str, deque] = defaultdict(deque)


def _client_ip() -> str:
    return request.remote_addr or "local"


def _rate_ok(bucket: str, limit: int) -> bool:
    key = f"{bucket}:{_client_ip()}"
    now = time.time()
    q = _RATE[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


@api.before_request
def _guard():
    # Optional shared-secret gate for non-loopback clients.
    ip = _client_ip()
    if config.HOST_TOKEN and ip not in ("127.0.0.1", "::1", "localhost"):
        if request.headers.get("X-Auth-Token", "") != config.HOST_TOKEN:
            return jsonify({"error": "invalid host token"}), 401
    limit = config.RATE_LIMIT_AI if request.path.startswith("/api/campaigns") and request.method == "POST" \
        else config.RATE_LIMIT_API
    if not _rate_ok("api", limit):
        return jsonify({"error": "rate limit exceeded — slow down, traveler"}), 429
    return None


def _err(exc: Exception, code: int = 400):
    if isinstance(exc, mp.MpDenied):
        code = 403
    return jsonify({"error": str(exc)}), code


@api.errorhandler(mp.MpDenied)
def _mp_denied_handler(exc):
    return jsonify({"error": str(exc)}), 403


@api.errorhandler(mp.MpError)
def _mp_error_handler(exc):
    return jsonify({"error": str(exc)}), 400


# --------------------------------------------------------------------------
# Multiplayer request context
# --------------------------------------------------------------------------

def _mp_resolve(cid: str):
    """(player, character_id) for this request. Solo campaigns pass through
    with (None, None); shared sessions REQUIRE a valid session token — the
    cross-site-safe CSRF equivalent, since browsers cannot forge a custom
    header without a CORS preflight."""
    session = mp._session(cid)
    if not session:
        return None, None
    player = mp.auth(cid, request.headers.get("X-MP-Token", ""))
    if session["status"] == "paused" and request.method == "POST" \
            and not request.path.endswith(("/session", "/view")):
        raise mp.MpError("the voyage is paused by the host")
    return player, player["character_id"]


def _mp_locked(cid: str):
    """Context manager: serialize authoritative work for shared sessions."""
    session = mp._session(cid)
    if session:
        return mp.session_lock(cid)
    import contextlib
    return contextlib.nullcontext()


def _mp_turn(cid: str, player):
    if player:
        mp.enforce_turn(cid, player)


def _mp_emit_dice_only(cid: str, player, res: dict) -> None:
    """A bare manual roll announces dice, not narration."""
    session = mp._session(cid)
    if not session:
        return
    d = res.get("dice")
    if not d:
        return
    name = player["display_name"] if player else "the shore"
    if isinstance(d, dict):
        text, outcome, dice = d.get("text", ""), d.get("outcome", ""), d.get("dice", [])
    else:
        text, outcome, dice = res.get("text", ""), res.get("outcome", ""), d
    mp.emit(cid, "dice", player["id"] if player else "gm", {
        "name": name, "text": text, "outcome": outcome, "dice": dice,
    })


def _mp_emit_result(cid: str, player, res: dict, kind: str, chid: str | None = None) -> None:
    """Broadcast one authoritative result. Split parties see their own group's
    narrations; world-level events stay party-wide."""
    session = mp._session(cid)
    if not session:
        return
    visibility = "party"
    if chid:
        row = db.query_one("SELECT location_id FROM characters WHERE id=?", (chid,))
        if row and row["location_id"]:
            visibility = f"loc:{row['location_id']}"
    elif player:
        eff = mp.char_location(cid, player)
        if eff:
            visibility = f"loc:{eff}"
    name = player["display_name"] if player else "the shore"
    d = res.get("dice")
    if d:
        if isinstance(d, dict):
            text, outcome, dice = d.get("text", ""), d.get("outcome", ""), d.get("dice", [])
        else:  # manual_check returns the roll flat: dice list + top-level text
            text, outcome, dice = res.get("text", ""), res.get("outcome", ""), d
        mp.emit(cid, "dice", player["id"] if player else "gm", {
            "name": name, "text": text, "outcome": outcome, "dice": dice,
        })
    mp.emit(cid, kind, player["id"] if player else "gm", {
        "name": name,
        "text": (res.get("narration") or res.get("text") or "")[:1200],
        "changes": res.get("changes", []),
    }, visibility=visibility)


def _forbid_guest_admin():
    """Host/local-only endpoints: a guest token may never reach them."""
    token = request.headers.get("X-MP-Token", "")
    if not token:
        return None
    row = db.query_one(
        "SELECT is_host FROM mp_players WHERE token_hash=?", (mp.hash_token(token),)
    )
    if row and not row["is_host"]:
        raise mp.MpDenied("guests do not manage the host's server")


# --------------------------------------------------------------------------
# System
# --------------------------------------------------------------------------

@api.get("/health")
def health():
    db.init_db()
    import os as _os
    payload = {"ok": True, "name": config.APP_NAME, "version": config.APP_VERSION,
               "data_dir": str(config.DATA_DIR),
               "schema": config.SCHEMA_VERSION,
               "fts5": db.fts_available(),
               "fts_warning": db.fts_warning(),
               "data_dir_writable": _os.access(config.DATA_DIR, _os.W_OK)
               if config.DATA_DIR.exists() else False,
               "ai_configured": bool(ai.get_ai_config().get("enabled"))}
    # truthful listener reporting: the advertised protocol always matches
    # what actually serves this port (direct TLS vs plain HTTP + proxy)
    try:
        from .app import startup_plan
        plan = startup_plan()
    except Exception:  # noqa: BLE001
        plan = {"mode": "off", "listener": "http"}
    payload["listener"] = plan.get("listener", "http")
    tls_requested = _os.environ.get("SATURDAY_TLS", "").strip() in ("1", "true", "yes")
    payload["tls"] = {"requested": tls_requested, "mode": plan.get("mode", "off")}
    if plan.get("mode") in ("direct", "proxy"):
        # certificate health for the operator; no paths with secrets, no keys
        try:
            from . import tls as _tls
            user_cert = _os.environ.get("SATURDAY_TLS_CERT", "").strip()
            cert_path = Path(user_cert) if user_cert else _tls.SERVER_CERT
            report = _tls.diagnose(cert_path)
            payload["tls"].update({"days_left": report.get("days_left"),
                                   "certificate_ok": bool(report.get("ok")),
                                   "problems": report.get("problems", [])})
        except Exception as exc:  # noqa: BLE001
            payload["tls"].update({"certificate_ok": False,
                                   "problems": [str(exc)[:120]]})
    return jsonify(payload)


@api.get("/settings")
def get_settings():
    # guests receive the flag and the model name only — never keys or URLs
    token = request.headers.get("X-MP-Token", "")
    if token:
        row = db.query_one("SELECT is_host FROM mp_players WHERE token_hash=?",
                           (mp.hash_token(token),))
        if row and not row["is_host"]:
            cfg = ai.masked_ai_config()
            inner = cfg.get("ai", cfg)
            return jsonify({"ai": {"enabled": bool(inner.get("enabled", False)),
                                   "model": str(inner.get("model", ""))},
                            "guest": True})
    return jsonify({"ai": ai.masked_ai_config(),
                    "host": {"token_required": bool(config.HOST_TOKEN),
                             "bind": f"{config.HOST}:{config.PORT}"}})


@api.put("/settings")
def put_settings():
    _forbid_guest_admin()
    body = request.get_json(silent=True) or {}
    if "ai" in body:
        try:
            ai.set_ai_config(body["ai"])
        except (ValueError, TypeError) as exc:
            return _err(exc)
    return jsonify({"ai": ai.masked_ai_config()})


@api.post("/ai/test")
def ai_test():
    _forbid_guest_admin()
    body = request.get_json(silent=True) or {}
    cfg = ai.get_ai_config()
    if body.get("ai"):
        merged = dict(cfg)
        merged.update({k: v for k, v in body["ai"].items() if k in ai.DEFAULT_AI_CONFIG})
        result = ai.test_connection(merged)
    else:
        result = ai.test_connection()
    return jsonify(result)


# --------------------------------------------------------------------------
# World packs
# --------------------------------------------------------------------------

@api.get("/packs")
def packs():
    return jsonify({"packs": worldpacks.list_packs()})


@api.post("/packs/import")
def packs_import():
    _forbid_guest_admin()
    body = request.get_json(silent=True) or {}
    try:
        result = worldpacks.import_pack(body.get("pack_json", ""))
    except ValueError as exc:
        return _err(exc)
    return jsonify(result)


@api.post("/packs/detail")
def pack_detail():
    """Full public manifest of one pack (for the character-creation screen)."""
    body = request.get_json(silent=True) or {}
    pack = worldpacks.load_pack(body.get("pack_id", ""))
    if not pack:
        return _err(ValueError("unknown world pack"), 404)
    return jsonify({"pack": {k: v for k, v in pack.items() if not k.startswith("_")}})


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------

@api.get("/campaigns")
def campaigns_list():
    return jsonify({"campaigns": gm.list_campaigns()})


@api.post("/campaigns")
def campaigns_create():
    _forbid_guest_admin()
    body = request.get_json(silent=True) or {}
    try:
        cid = gm.create_campaign(
            body.get("name", ""), body.get("pack_id", ""), body.get("character", {})
        )
    except ValueError as exc:
        return _err(exc)
    return jsonify({"campaign_id": cid, "view": gm.campaign_view(cid)})


@api.get("/campaigns/<cid>")
def campaign_get(cid):
    try:
        player, chid = _mp_resolve(cid)
        return jsonify(gm.campaign_view(cid, chid))
    except ValueError as exc:
        return _err(exc, 404)


@api.delete("/campaigns/<cid>")
def campaign_archive(cid):
    _forbid_guest_admin()
    if not gm.get_campaign(cid):
        return _err(ValueError("campaign not found"), 404)
    gm.archive_campaign(cid)
    return jsonify({"ok": True})


@api.post("/campaigns/<cid>/action")
def campaign_action(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        mp.require_player(player)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = gm.run_turn(cid, body.get("text", ""), chid)
            _mp_emit_result(cid, player, res, "narration", chid=chid)
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/choose")
def campaign_choose(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = gm.choose(cid, body.get("choice_id", ""), chid)
            _mp_emit_result(cid, player, res, "narration", chid=chid)
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/check")
def campaign_check(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        mp.require_player(player)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = gm.manual_check(cid, body.get("skill", ""), bool(body.get("hard")),
                                  bool(body.get("risk")), chid)
            _mp_emit_dice_only(cid, player, res)
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/travel")
def campaign_travel(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        mp.require_player(player)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            if player and mp._session(cid) and mp._session(cid)["status"] == "active" \
                    and not body.get("solo"):
                res = mp.propose_travel(cid, player, body.get("location_id", ""))
            else:
                res = gm.travel(cid, body.get("location_id", ""), chid)
                _mp_emit_result(cid, player, res, "travel")
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/rest")
def campaign_rest(cid):
    try:
        player, chid = _mp_resolve(cid)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = gm.rest(cid, chid)
            _mp_emit_result(cid, player, res, "rest")
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


# --------------------------------------------------------------------------
# Milestones 1.5 / 2.0 / 2.5
# --------------------------------------------------------------------------

@api.post("/campaigns/<cid>/style")
def campaign_style(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, _chid = _mp_resolve(cid)
        if player:
            mp.require_host(player)  # the persona is the host's to set
        res = legacy.set_style(cid, body.get("style_id", "classic"),
                               body.get("custom_text", ""))
        if player:
            mp.emit(cid, "system", "system",
                    {"text": f"The host sets the Game Master's voice to {res['label']}."})
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/styles")
def styles_list():
    return jsonify({"styles": [
        {"id": sid, "label": s["label"]}
        for sid, s in legacy.GM_STYLES.items()
    ] + [{"id": "custom", "label": "Custom"}]})


@api.post("/campaigns/<cid>/talk")
def campaign_talk(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        if not player:
            # no multiplayer session exists: a legitimate solo request — the
            # teller is the campaign's own character (hotfix 4: this fallback
            # is decided by session state, never by an auth failure)
            chid = experience.teller_character(cid, None)
        with _mp_locked(cid):
            # hotfix 4: the authenticated player's own character hears this
            # conversation; a spectator carries no character and learns none
            # of it
            res = legacy.talk(cid, body.get("npc_id", ""), body.get("topic", "the shore"),
                              chid=chid)
            if player:
                mp.emit(cid, "system", "system",
                        {"text": f"{player['display_name']} speaks with {res['npc']['name']}."})
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/washashore")
def campaign_washashore(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        pack = worldpacks.load_pack(gm.get_campaign(cid)["pack_id"])
        if body.get("action") == "check":
            return jsonify({"washashore": legacy.check_washashore(cid, pack)})
        with _mp_locked(cid):
            res = legacy.pick_washashore(cid, pack, chid)
            if player:
                mp.emit(cid, "system", "system",
                        {"text": f"{player['display_name']} gathers {res['label']} from the sand."})
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/push")
def campaign_push(cid):
    try:
        player, chid = _mp_resolve(cid)
        with _mp_locked(cid):
            result = legacy.push_roll(cid, chid)
            result.pop("pack", None)
            mp.emit(cid, "system", "system",
                    {"text": f"{player['display_name']} pushes the tide — {result['pending']['outcome']}."}
                    ) if player else None
        return jsonify(result)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/resist")
def campaign_resist(cid):
    try:
        player, chid = _mp_resolve(cid)
        with _mp_locked(cid):
            result = legacy.resist_roll(cid, chid)
            if player:
                mp.emit(cid, "system", "system",
                        {"text": f"{player['display_name']} braces against it — harm eases to {result['pending']['harm']}."})
        return jsonify(result)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/pending/accept")
def campaign_pending_accept(cid):
    """Player accepts the resolved roll; the tactical window closes."""
    _mp_resolve(cid)
    legacy._clear_pending(cid, _mp_resolve(cid)[1])
    return jsonify({"ok": True})


@api.get("/campaigns/<cid>/omen_hand")
def campaign_omen_hand(cid):
    _, chid = _mp_resolve(cid)
    return jsonify(legacy.omen_hand(cid, chid))


@api.post("/campaigns/<cid>/omen/draw")
def campaign_omen_draw(cid):
    try:
        player, chid = _mp_resolve(cid)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = legacy.draw_to_hand(cid, chid)
            if player:
                mp.emit(cid, "system", "system",
                        {"text": f"{player['display_name']} draws {res['card']['title']} from the deck."})
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/omen/play")
def campaign_omen_play(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        with _mp_locked(cid):
            res = legacy.play_omen(cid, body.get("card_id", ""), chid)
            if player:
                mp.emit(cid, "system", "system", {"text": f"{player['display_name']}: {res['narration']}"})
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/campaigns/<cid>/upgrades")
def campaign_upgrades(cid):
    _, chid = _mp_resolve(cid)
    return jsonify({"upgrades": legacy.list_upgrades(cid, chid),
                    "beads": legacy.get_beads(cid, chid),
                    "pot": mp.session_view_pot(cid)})


@api.post("/campaigns/<cid>/upgrades")
def campaign_upgrade_buy(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        with _mp_locked(cid):
            res = legacy.buy_upgrade(cid, body.get("upgrade_id", ""), chid)
            if player:
                mp.emit(cid, "system", "system", {"text": f"{player['display_name']}: {res['narration']}"})
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/worlds")
def campaign_world_generate(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, _chid = _mp_resolve(cid)
        w = legacy.generate_and_store(cid, body.get("seed", ""))
        if player:
            mp.emit(cid, "system", "system",
                    {"text": f"{player['display_name']} whispers a seed and opens {w['name']}."})
        identity = w.get("identity", {})
        return jsonify({
            "world_id": w["id"], "name": w.get("name", identity.get("name", "")),
            "seed": w.get("seed", body.get("seed", "")),
            "archetype": identity.get("archetype_label", ""),
            "tint": identity.get("tint", 0),
            "entry_location": identity.get("entry_location", ""),
            "existing": bool(w.get("existing")),
        })
    except ValueError as exc:
        return _err(exc)


@api.get("/campaigns/<cid>/worlds")
def campaign_world_list(cid):
    return jsonify({"worlds": legacy.list_worlds(cid)})


@api.get("/seeds/suggest")
def seeds_suggest():
    return jsonify({"suggestions": gen.suggest_seeds(6)})


@api.get("/echoes")
def echoes_list():
    only_unused = request.args.get("unused") == "1"
    return jsonify({"echoes": legacy.list_echoes(only_unused)})


@api.get("/campaigns/<cid>/ledger")
def campaign_ledger(cid):
    try:
        _, chid = _mp_resolve(cid)
        return jsonify(legacy.ledger(cid, chid))
    except ValueError as exc:
        return _err(exc, 404)


@api.post("/campaigns/<cid>/use_item")
def campaign_use_item(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = gm.use_item(cid, body.get("item_id", ""), chid)
            _mp_emit_result(cid, player, res, "item")
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/journal")
def campaign_journal(cid):
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()[:600]
    if not text:
        return _err(ValueError("journal entry is empty"))
    jid = db.add_journal(cid, text, "player")
    return jsonify({"id": jid})


@api.get("/campaigns/<cid>/transcript")
def campaign_transcript(cid):
    limit = min(300, max(1, int(request.args.get("limit", "60"))))
    rows = db.query(
        "SELECT ts, role, content, data_json FROM transcript WHERE campaign_id=?"
        " ORDER BY rowid DESC LIMIT ?",
        (cid, limit),
    )
    import json as _json
    out = []
    for r in reversed(rows):
        out.append({"ts": r["ts"], "role": r["role"], "content": r["content"],
                    "data": db.jloads(r["data_json"], {})})
    return jsonify({"transcript": out})


@api.get("/campaigns/<cid>/search")
def campaign_search(cid):
    q = request.args.get("q", "").strip()[:120]
    if not q:
        return jsonify({"results": []})
    return jsonify({"results": db.search_campaign(cid, q)})


@api.get("/campaigns/<cid>/export")
def campaign_export(cid):
    try:
        data = gm.export_campaign(cid)
    except ValueError as exc:
        return _err(exc, 404)
    return Response(
        db.jdumps(data),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={cid}.json"},
    )


@api.post("/import")
def campaign_import():
    body = request.get_json(silent=True) or {}
    try:
        cid = gm.import_campaign(body)
    except (ValueError, KeyError) as exc:
        return _err(exc)
    return jsonify({"campaign_id": cid})


@api.post("/campaigns/<cid>/qr")
def campaign_qr(cid):
    body = request.get_json(silent=True) or {}
    if not gm.get_campaign(cid):
        return _err(ValueError("campaign not found"), 404)
    return jsonify(qr.parse_payload(cid, body.get("payload", "")))


# --------------------------------------------------------------------------
# Backups (whole-database, for save recovery)
# --------------------------------------------------------------------------

@api.post("/backup")
def backup_create():
    config.ensure_dirs()
    ts = time.strftime("%Y%m%d_%H%M%S")
    bid = db.new_id("bak")
    path = config.BACKUP_DIR / f"backup_{ts}.db"
    src = db.get_conn()
    dst_db_path = str(path)
    import sqlite3
    dst = sqlite3.connect(dst_db_path)
    with dst:
        src.backup(dst)
    dst.close()
    size = path.stat().st_size
    db.execute(
        "INSERT INTO backups (id, created_at, campaign_id, path, size) VALUES (?,?,?,?,?)",
        (bid, db.utcnow(), None, str(path), size),
    )
    return jsonify({"id": bid, "path": str(path), "size": size})


@api.get("/backups")
def backup_list():
    rows = db.query("SELECT id, created_at, path, size FROM backups ORDER BY created_at DESC LIMIT 50")
    return jsonify({"backups": [dict(r) for r in rows]})


@api.post("/backups/<bid>/restore")
def backup_restore(bid):
    row = db.query_one("SELECT path FROM backups WHERE id=?", (bid,))
    if not row:
        return _err(ValueError("backup not found"), 404)
    import pathlib
    import shutil
    src = pathlib.Path(row["path"])
    if not src.exists():
        return _err(ValueError("backup file missing from disk"), 404)
    global_conn = db.get_conn()
    global_conn.close()
    db._CONN = None  # force reopen after file swap
    shutil.copyfile(src, config.DB_PATH)
    db.init_db()
    return jsonify({"ok": True, "restored_from": str(src)})


# --------------------------------------------------------------------------
# The Shared Shore — multiplayer endpoints
# --------------------------------------------------------------------------

def _mp_body():
    return request.get_json(silent=True) or {}


def _mp_auth(cid: str, allow_pending: bool = False) -> dict:
    return mp.auth(cid, request.headers.get("X-MP-Token", ""), allow_pending)


@api.post("/mp/host")
def mp_host():
    """Open (or reopen) a shared session on a campaign and join as host."""
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        if not cid and isinstance(body.get("new_campaign"), dict):
            spec = body["new_campaign"]
            cid = gm.create_campaign(spec.get("name", ""), spec.get("pack_id", "living_shore"),
                                     spec.get("character", {}))
        if not cid:
            return _err(ValueError("pick a campaign to share"))
        res = mp.host_session(cid, body.get("display_name", ""),
                              body.get("character") if body.get("character") else None)
        res["view"] = mp.session_view(cid, mp.auth(cid, res["token"]))
        res["invite_url_path"] = "/?join="
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/invite")
def mp_invite():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        res = mp.create_invite(cid, player, body.get("label", ""),
                               int(body.get("uses", 0) or 0),
                               body.get("expires_sec", 86400 * 14))
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/mp/invites/<cid>")
def mp_invites(cid):
    try:
        player = _mp_auth(cid)
        return jsonify({"invites": mp.list_invites(cid, player)})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/invite/revoke")
def mp_invite_revoke():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        mp.revoke_invite(cid, player, body.get("invite_id", ""))
        return jsonify({"ok": True})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/join")
def mp_join():
    """Follow an invitation: display name + new wanderer = on the shore."""
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        if not cid:
            # resolve the campaign from the invite token itself
            row = db.query_one("SELECT campaign_id FROM mp_invites WHERE token_hash=?",
                               (mp.hash_token(str(body.get("invite_token", ""))),))
            if not row:
                return _err(mp.MpDenied("that invitation is not valid"), 403)
            cid = row["campaign_id"]
        res = mp.join(cid, body.get("invite_token", ""), body.get("display_name", ""),
                      body.get("character"))
        res["view"] = mp.session_view(cid, mp.auth(cid, res["token"], allow_pending=True))
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/reconnect")
def mp_reconnect():
    """A returning traveler presents their token; the shore restores them."""
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        if not cid:
            row = db.query_one("SELECT campaign_id FROM mp_players WHERE token_hash=?",
                               (mp.hash_token(str(body.get("token", ""))),))
            if not row:
                return _err(mp.MpDenied("no voyage remembers that token"), 403)
            cid = row["campaign_id"]
        # a reconnecting client may present the token in the body (it lost its
        # session state); the header still works for live clients
        token = request.headers.get("X-MP-Token") or str(body.get("token", ""))
        player = mp.auth(cid, token)
        view = mp.session_view(cid, player)
        return jsonify({"campaign_id": cid, "player_id": player["id"],
                        "view": view, "resume_view": gm.campaign_view(cid, player["character_id"])})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/mp/view/<cid>")
def mp_view(cid):
    try:
        player = _mp_auth(cid)
        return jsonify(mp.session_view(cid, player))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc, 404)


@api.post("/mp/ready")
def mp_ready():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        mp.set_ready(cid, player, bool(body.get("ready")))
        return jsonify({"ok": True})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/start")
def mp_start():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        mp.start_session(cid, player)
        return jsonify({"ok": True, "view": mp.session_view(cid, player)})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/session")
def mp_session_control():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify(mp.session_control(cid, player, body.get("action", "")))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/settings")
def mp_settings():
    """Host tuning: turn mode, timeouts, approval."""
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        mp.require_host(player)
        if body.get("mode"):
            mp.set_mode(cid, player, body["mode"], body.get("turn_timeout"))
        session = mp._session(cid)
        settings = mp._settings(cid)
        if "approve_join" in body:
            settings["approve_join"] = bool(body["approve_join"])
            mp._save_settings(cid, settings)
        return jsonify({"mode": session["mode"], "settings": settings})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/chat")
def mp_chat():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify({"message": mp.chat(cid, player, body.get("text", ""))})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/mp/stream")
def mp_stream():
    """SSE: replay from ?last_seq, then follow live. Authenticated by a
    one-time short-lived ticket (tokens never appear in URLs)."""
    entry = mp.pop_stream_ticket(request.args.get("ticket", ""))
    if not entry:
        return jsonify({"error": "stream ticket missing or expired"}), 403
    cid, player_id = entry
    row = db.query_one("SELECT * FROM mp_players WHERE id=?", (player_id,))
    if not row or row["campaign_id"] != cid:
        return jsonify({"error": "stream ticket invalid"}), 403
    mp.touch(row)
    last_seq = int(request.args.get("last_seq", 0) or 0)
    resp = Response(mp.stream(cid, dict(row), last_seq), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@api.post("/mp/stream-ticket")
def mp_stream_ticket():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify({"ticket": mp.new_stream_ticket(player), "ttl": mp.TICKET_TTL})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/mp/events/<cid>")
def mp_events_replay(cid):
    """REST replay (used by tests and by clients that prefer polling)."""
    try:
        player = _mp_auth(cid)
        since = int(request.args.get("last_seq", 0) or 0)
        page = mp.events_since_page(cid, since, player)
        return jsonify({"events": page["events"], "cursor": page["cursor"],
                        "latest_seq": page["latest"]})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/travel/vote")
def mp_travel_vote():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        with mp.session_lock(cid):
            res = mp.vote_travel(cid, player, bool(body.get("accept")))
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/travel/force")
def mp_travel_force():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        with mp.session_lock(cid):
            res = mp.force_travel(cid, player, body.get("location_id", ""))
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/turn/advance")
def mp_turn_advance():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        mp.advance_turn(cid, player)
        return jsonify({"ok": True})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/trade")
def mp_trade_propose():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify(mp.propose_trade(cid, player, body.get("to_player", ""),
                                        body.get("item_row_id", ""), body.get("qty", 1)))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/trade/respond")
def mp_trade_respond():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify(mp.respond_trade(cid, player, body.get("offer_id", ""),
                                        bool(body.get("accept"))))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/gift")
def mp_gift():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify(mp.gift_beads(cid, player, body.get("to_player", ""),
                                     body.get("amount", 0)))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/clue/share")
def mp_clue_share():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify(mp.share_clue(cid, player, body.get("thread_id", "")))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/contribute")
def mp_contribute():
    body = _mp_body()
    try:
        cid = body.get("campaign_id", "")
        player = _mp_auth(cid)
        return jsonify(mp.contribute(cid, player, body.get("upgrade_id", ""),
                                     body.get("amount", 0)))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/players/<cid>/remove")
def mp_player_remove(cid, target_id=None):
    body = _mp_body()
    try:
        player = _mp_auth(cid)
        mp.remove_player(cid, player, target_id or body.get("player_id", ""),
                         bool(body.get("ban")))
        return jsonify({"ok": True})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/mp/players/<cid>/approve")
def mp_player_approve(cid, target_id=None):
    body = _mp_body()
    try:
        player = _mp_auth(cid)
        mp.approve_player(cid, player, target_id or body.get("player_id", ""))
        return jsonify({"ok": True})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


# --------------------------------------------------------------------------
# The Infinite Library + Campaign Forge (Milestone 3.5)
# --------------------------------------------------------------------------

@api.get("/library")
def library_list():
    import base64
    _forbid_guest_admin()
    token = request.headers.get("X-MP-Token", "")
    is_guest = False
    if token:
        row = db.query_one("SELECT is_host FROM mp_players WHERE token_hash=?",
                           (mp.hash_token(token),))
        is_guest = bool(row and not row["is_host"])
    docs = library.list_docs(include_private=not is_guest)
    packs = [p for p in worldpacks.list_packs() if p.get("id") != "living_shore"]
    return jsonify({"docs": docs, "packs": packs})


@api.post("/library/import")
def library_import():
    _forbid_guest_admin()
    body = _mp_body()
    try:
        data = base64.b64decode(body.get("data_b64", "") or "")
        doc = library.import_document(
            data, body.get("filename", ""),
            title=body.get("title", ""), author=body.get("author", ""),
            source_url=body.get("source_url", ""), license=body.get("license", "Private"),
            attribution=body.get("attribution", ""),
            private=bool(body.get("private")),
        )
        return jsonify(doc)
    except (ValueError, library.LibraryError) as exc:
        return _err(exc)
    except Exception as exc:
        return _err(ValueError(f"import failed: {exc}"))


@api.post("/library/search")
def library_search_ep():
    _forbid_guest_admin()
    body = _mp_body()
    return jsonify({"hits": library.search(body.get("query", ""),
                                           doc_id=body.get("doc_id") or None,
                                           k=int(body.get("k", 8) or 8))})


@api.get("/library/<doc_id>/retrieve")
def library_retrieve(doc_id):
    _forbid_guest_admin()
    text = request.args.get("text", "")
    return jsonify({"passages": library.retrieve_for_prompt(doc_id, text, k=4)})


@api.delete("/library/<doc_id>")
def library_delete(doc_id):
    _forbid_guest_admin()
    try:
        library.delete_doc(doc_id)
        return jsonify({"ok": True})
    except (ValueError, library.LibraryError) as exc:
        return _err(exc)


@api.get("/forge/drafts")
def forge_list():
    _forbid_guest_admin()
    return jsonify({"drafts": forge.list_drafts()})


@api.post("/forge/drafts")
def forge_create():
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.create_draft(body.get("doc_id", ""),
                                          body.get("mode", "faithful")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/drafts/<draft_id>")
def forge_get(draft_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.draft_view(draft_id))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc, 404)


@api.post("/forge/drafts/<draft_id>/regen")
def forge_regen(draft_id):
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.regenerate_section(draft_id, body.get("section", ""),
                                                body.get("notes", "")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.post("/forge/drafts/<draft_id>/approve")
def forge_approve(draft_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.approve_draft(draft_id))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/packs/<pack_id>/preview")
def pack_preview(pack_id):
    """Adventure preview + encyclopedia + licensing for one pack."""
    pack = worldpacks.load_pack(pack_id)
    if not pack:
        return _err(ValueError("no such world pack"), 404)
    advs = []
    for adv in pack.get("adventures", []):
        scenes = adv.get("scenes", {})
        scenes = scenes.values() if isinstance(scenes, dict) else scenes
        advs.append({
            "id": adv.get("id"), "title": adv.get("title"),
            "summary": adv.get("summary", ""), "entry": adv.get("entry"),
            "scenes": [{"id": s.get("id"), "title": s.get("title"),
                        "brief": s.get("brief", "")} for s in scenes],
            "endings": list(adv.get("endings", {}).keys())
            if isinstance(adv.get("endings"), dict) else
            [e.get("id") for e in adv.get("endings", [])],
        })
    return jsonify({
        "id": pack["id"], "name": pack["name"], "summary": pack.get("summary", ""),
        "genre_tags": pack.get("genre_tags", []), "gm_style": pack.get("gm_style", ""),
        "license": pack.get("license", {}),
        "supports_rulesets": pack.get("supports_rulesets", ["undertow"]),
        "locations": [{"id": l["id"], "name": l["name"], "short": l.get("short", "")}
                      for l in pack.get("locations", [])],
        "npcs": [{"id": n["id"], "name": n["name"], "role": n.get("role", ""),
                  "desc": n.get("desc", "")} for n in pack.get("npcs", [])],
        "adventures": advs,
        "n_omens": len(pack.get("omens", [])),
        "n_items": len(pack.get("items", [])),
    })


# --------------------------------------------------------------------------
# Milestone 3.6: party splitting, spectators, player-controlled combat
# --------------------------------------------------------------------------

@api.post("/campaigns/<cid>/mp/invite-spectator")
def mp_invite_spectator(cid):
    body = request.get_json(silent=True) or {}
    try:
        player = mp.auth(cid, request.headers.get("X-MP-Token", ""))
        mp.require_host(player)
        return jsonify(mp.create_invite(cid, player, body.get("label", "watch"),
                                        int(body.get("uses", 1) or 1), spectator=True))
    except (ValueError, mp.MpError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/mp/split")
def mp_split(cid):
    body = request.get_json(silent=True) or {}
    try:
        player = mp.auth(cid, request.headers.get("X-MP-Token", ""))
        return jsonify(mp.set_location(cid, player, body.get("location_id", "")))
    except (ValueError, mp.MpError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/mp/regroup")
def mp_regroup(cid):
    body = request.get_json(silent=True) or {}
    try:
        player = mp.auth(cid, request.headers.get("X-MP-Token", ""))
        return jsonify(mp.regroup(cid, player, everyone=bool(body.get("everyone"))))
    except (ValueError, mp.MpError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/campaigns/<cid>/combat")
def combat_view(cid):
    try:
        player, chid = _mp_resolve(cid)
        if not chid:  # solo play: view from the campaign's own character
            ch = gm.get_character(cid)
            chid = ch["id"] if ch else None
        v = combat.view(cid, for_chid=chid)
        return jsonify({"encounter": v})
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/combat")
def combat_act(cid):
    """A player-controlled combat action. Only the character's own turn,
    only their own sheet: forged actions for others are impossible here."""
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
        mp.require_player(player)
        if not chid:
            # solo voyage: the campaign's own character acts (the same engine,
            # the same validation; a multiplayer session keeps token ownership)
            ch = gm.get_character(cid)
            chid = ch["id"] if ch else None
        if not chid:
            raise mp.MpDenied("you have no character in this fight")
        if body.get("chid") and body["chid"] != chid:
            raise mp.MpDenied("you may act only for your own character")
        with _mp_locked(cid):
            if body.get("type") == "join":
                v = combat.join(cid, body.get("encounter_id", ""), chid,
                                location=mp.char_location(cid, player))
            else:
                v = combat.action(cid, body.get("encounter_id", ""), chid, body)
            if v is None:  # the action ended the encounter
                v = combat.last_view(cid) or {}
        _mp_emit_result(cid, player, {"narration": " | ".join(v.get("log", [])[-2:]),
                                      "changes": []}, "combat", chid=chid)
        return jsonify(v)
    except (ValueError, mp.MpError, mp.MpDenied, combat.CombatError) as exc:
        return _err(exc)


# --------------------------------------------------------------------------
# Milestone 3.6: Campaign Director, continuity, checkpoints, forge jobs
# --------------------------------------------------------------------------

@api.get("/campaigns/<cid>/director")
def director_view(cid):
    try:
        pack = worldpacks.load_pack(gm.get_campaign(cid)["pack_id"])
        return jsonify(director.campaign_view(cid, pack))
    except ValueError as exc:
        return _err(exc, 404)


@api.post("/campaigns/<cid>/director/mode")
def director_mode(cid):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(director.set_mode(cid, body.get("mode", "gentle")))
    except ValueError as exc:
        return _err(exc)


@api.get("/campaigns/<cid>/continuity")
def continuity_view(cid):
    return jsonify({"findings": continuity.check(cid)})


@api.post("/campaigns/<cid>/checkpoints")
def checkpoint_create(cid):
    body = request.get_json(silent=True) or {}
    try:
        export = gm.export_campaign(cid)
        cp_id = new_id("ckp")
        db.execute("INSERT INTO campaign_checkpoints (id, campaign_id, name, export_json,"
                   " created_at) VALUES (?,?,?,?,?)",
                   (cp_id, cid, (body.get("name") or "checkpoint")[:80],
                    jdumps(export), utcnow()))
        db.log_event(cid, "checkpoint_created", {"checkpoint_id": cp_id})
        return jsonify({"checkpoint_id": cp_id})
    except ValueError as exc:
        return _err(exc)


@api.get("/campaigns/<cid>/checkpoints")
def checkpoint_list(cid):
    rows = [dict(r) for r in db.query(
        "SELECT id, name, created_at FROM campaign_checkpoints WHERE campaign_id=?"
        " ORDER BY created_at DESC", (cid,))]
    return jsonify({"checkpoints": rows})


@api.post("/campaigns/<cid>/checkpoints/<cp_id>/restore")
def checkpoint_restore(cid, cp_id):
    """Restoration creates a NEW campaign from the checkpoint (no automatic
    rollback of shared state, no reward duplication, ownership preserved)."""
    row = db.query_one("SELECT export_json FROM campaign_checkpoints WHERE id=? AND campaign_id=?",
                       (cp_id, cid))
    if not row:
        return _err(ValueError("no such checkpoint"), 404)
    data = jloads(row["export_json"], {})
    new_cid = gm.import_campaign(data)
    return jsonify({"campaign_id": new_cid})


@api.get("/forge/jobs")
def forge_jobs_list():
    _forbid_guest_admin()
    return jsonify({"jobs": forge.list_jobs()})


@api.post("/forge/jobs")
def forge_job_create():
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.create_job(body.get("doc_id", ""), body.get("mode", "faithful"),
                                        body.get("scope", "short")))
    except (ValueError, forge.JobError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/jobs/<job_id>")
def forge_job_get(job_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.job_view(job_id))
    except (ValueError, forge.JobError) as exc:
        return _err(exc, 404)


@api.post("/forge/jobs/<job_id>/cancel")
def forge_job_cancel(job_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.cancel_job(job_id))
    except (ValueError, forge.JobError) as exc:
        return _err(exc)


@api.post("/forge/jobs/<job_id>/retry")
def forge_job_retry(job_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.retry_job(job_id))
    except (ValueError, forge.JobError) as exc:
        return _err(exc)


@api.post("/forge/jobs/<job_id>/run")
def forge_job_run(job_id):
    """Run/resume a job synchronously under a manual lease (the watchdog uses
    the same claim path, so two workers can never share one job)."""
    _forbid_guest_admin()
    try:
        return jsonify(forge.run_job(job_id, worker="manual"))
    except (ValueError, forge.JobError) as exc:
        return _err(exc)


@api.post("/forge/jobs/<job_id>/approve")
def forge_job_approve(job_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.approve_job(job_id))
    except (ValueError, forge.JobError, forge.ForgeError) as exc:
        return _err(exc)


@api.post("/forge/drafts/<draft_id>/edit")
def forge_draft_edit(draft_id):
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.edit_draft(draft_id, body.get("ops", []), body.get("note", "")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/drafts/<draft_id>/history")
def forge_draft_history(draft_id):
    _forbid_guest_admin()
    return jsonify({"history": forge.draft_history(draft_id)})


@api.post("/forge/drafts/<draft_id>/restore")
def forge_draft_restore(draft_id):
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.restore_revision(draft_id, int(body.get("seq", 0))))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/drafts/<draft_id>/compare")
def forge_draft_compare(draft_id):
    _forbid_guest_admin()
    try:
        a = int(request.args.get("a", 0))
        b = int(request.args.get("b", 0))
        return jsonify(forge.compare_revisions(draft_id, a, b))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.post("/forge/drafts/<draft_id>/duplicate")
def forge_draft_duplicate(draft_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.duplicate_draft(draft_id))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/drafts/<draft_id>/export")
def forge_draft_export(draft_id):
    _forbid_guest_admin()
    try:
        return jsonify(forge.export_draft(draft_id))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/drafts/<draft_id>/flow")
def forge_draft_flow(draft_id):
    _forbid_guest_admin()
    try:
        draft = forge.draft_view(draft_id)
        return jsonify({"findings": forge.validate_flow(draft["pack"])})
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc, 404)


@api.get("/rules/dnd/coverage")
def dnd_coverage():
    return jsonify(rules_dnd.COVERAGE)


@api.post("/library/match-source")
def library_match_source():
    """Find the indexed document matching a pack's source title/author.
    Links survive restarts and reindexing because matching happens at
    use-time, not by stored document ids."""
    body = _mp_body()
    title = (body.get("title") or "").strip()
    author = (body.get("author") or "").strip()
    docs = library.list_docs()
    best, score = None, 0
    for d in docs:
        s = 0
        if title and title.lower()[:40] in (d["title"] or "").lower():
            s += 2
        if author and author.lower()[:30] in (d["author"] or "").lower():
            s += 2
        if d["source_url"] and body.get("source_url") and d["source_url"] == body["source_url"]:
            s += 3
        if s > score:
            best, score = d, s
    if best and score >= 2:
        return jsonify({"doc_id": best["id"], "title": best["title"],
                        "author": best["author"], "score": score,
                        "n_chunks": best["n_chunks"]})
    return jsonify({"doc_id": None, "score": score or 0})


@api.get("/packs/<pack_id>/source-link")
def pack_source_link(pack_id):
    pack = worldpacks.load_pack(pack_id)
    if not pack:
        return _err(ValueError("no such world pack"), 404)
    lic = pack.get("license", {})
    return jsonify({"source_title": lic.get("source_title"), "author": lic.get("author"),
                    "source_url": lic.get("source_url"), "license": lic.get("license"),
                    "attribution": lic.get("attribution"),
                    "linked_doc_id": lic.get("library_doc_id")})


# --------------------------------------------------------------------------
# Milestone 3.6 steering update: collaborative worldbuilding on the same
# universal Forge. Identity = existing multiplayer session tokens; the local
# player is the creator when no session is open. No new accounts or keys.
# --------------------------------------------------------------------------

def _collab_is_creator(row, actor_id: str) -> bool:
    collab = jloads(row["collab_json"] or "{}", {})
    return bool(actor_id) and (actor_id == row["owner"] or actor_id == collab.get("creator"))


def _collab_actor(cid_hint: str | None = None):
    """(player_id, player_name, workshop_campaign_id) from existing identities.
    The header token resolves its own campaign — no new accounts, no new keys."""
    body_raw = request.get_json(silent=True) or {}
    token = request.headers.get("X-MP-Token") or str(body_raw.get("campaign_token", ""))
    cid = body_raw.get("campaign_id") or cid_hint
    if token:
        if not cid:
            row = db.query_one("SELECT campaign_id FROM mp_players WHERE token_hash=?",
                               (mp.hash_token(token),))
            cid = row["campaign_id"] if row else None
        if cid:
            try:
                player = mp.auth(cid, token)
                return player["id"], player["display_name"], cid
            except (mp.MpDenied, mp.MpError):
                pass
    return "local", "the local player", None


@api.post("/forge/collab")
def forge_collab_create():
    _forbid_guest_admin()
    body = _mp_body()
    try:
        pid, pname, _sess = _collab_actor(body.get("workshop_cid") or body.get("campaign_id"))
        return jsonify(forge.create_collab(body.get("name", ""), pid, pname,
                                           body.get("from_campaign_id")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/collab/<draft_id>")
def forge_collab_view(draft_id):
    try:
        token = request.headers.get("X-MP-Token", "")
        viewer = "local"
        if token:
            row = db.query_one("SELECT campaign_id FROM mp_players WHERE token_hash=?",
                               (mp.hash_token(token),))
            if row:
                try:
                    player = mp.auth(row["campaign_id"], token)
                    viewer = player["id"]
                except (mp.MpDenied, mp.MpError):
                    viewer = "local"
        return jsonify(forge.collab_view(draft_id, viewer))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc, 404)


@api.post("/forge/collab/<draft_id>/contribute")
def forge_collab_contribute(draft_id):
    body = _mp_body()
    try:
        pid, pname, sess = _collab_actor()
        # collaborators join through the workshop session, or the local player
        if sess is None:
            token = request.headers.get("X-MP-Token") or str(body.get("campaign_token", ""))
            if token and body.get("workshop_cid"):
                player = mp.auth(body["workshop_cid"], token)
                pid, pname = player["id"], player["display_name"]
        return jsonify(forge.contrib_propose(draft_id, pid, pname, body.get("ops", []),
                                             body.get("note", ""), body.get("base_rev")))
    except (ValueError, forge.ForgeError, mp.MpDenied, mp.MpError) as exc:
        return _err(exc)


@api.post("/forge/collab/<draft_id>/proposals/<pid2>/apply")
def forge_collab_apply(draft_id, pid2):
    body = _mp_body()
    try:
        actor_id, _pname, sess = _collab_actor()
        if sess and body.get("workshop_cid"):
            player = mp.auth(body["workshop_cid"],
                             request.headers.get("X-MP-Token") or str(body.get("campaign_token", "")))
            actor_id = player["id"]
        row = db.query_one("SELECT owner, collab_json FROM forge_drafts WHERE id=?", (draft_id,))
        is_creator = bool(row) and _collab_is_creator(row, actor_id)
        if not is_creator:
            _forbid_guest_admin()  # non-creators keep the guest boundary
        return jsonify(forge.contrib_apply(draft_id, pid2, actor_id,
                                           bool(body.get("force"))))
    except (ValueError, forge.ForgeError, mp.MpDenied, mp.MpError) as exc:
        return _err(exc)


@api.post("/forge/collab/<draft_id>/proposals/<pid2>/reject")
def forge_collab_reject(draft_id, pid2):
    body = _mp_body()
    try:
        actor_id, _pname, sess = _collab_actor()
        if sess and body.get("workshop_cid"):
            player = mp.auth(body["workshop_cid"],
                             request.headers.get("X-MP-Token") or str(body.get("campaign_token", "")))
            actor_id = player["id"]
        row = db.query_one("SELECT owner, collab_json FROM forge_drafts WHERE id=?", (draft_id,))
        if not (bool(row) and _collab_is_creator(row, actor_id)):
            _forbid_guest_admin()
        return jsonify(forge.contrib_reject(draft_id, pid2, actor_id))
    except (ValueError, forge.ForgeError, mp.MpDenied, mp.MpError) as exc:
        return _err(exc)


@api.post("/forge/collab/<draft_id>/suggest")
def forge_collab_suggest(draft_id):
    body = _mp_body()
    try:
        return jsonify(forge.collab_suggest(draft_id, body.get("kind", "npc"),
                                            body.get("prompt", ""), ai.get_ai_config()))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.post("/forge/collab/<draft_id>/approve")
def forge_collab_approve(draft_id):
    body = _mp_body()
    try:
        actor_id, _pname, sess = _collab_actor()
        if sess and body.get("workshop_cid"):
            player = mp.auth(body["workshop_cid"],
                             request.headers.get("X-MP-Token") or str(body.get("campaign_token", "")))
            actor_id = player["id"]
        row = db.query_one("SELECT owner, collab_json FROM forge_drafts WHERE id=?", (draft_id,))
        if not (bool(row) and _collab_is_creator(row, actor_id)):
            _forbid_guest_admin()
        return jsonify(forge.collab_approve(draft_id, actor_id))
    except (ValueError, forge.ForgeError, mp.MpDenied, mp.MpError) as exc:
        return _err(exc)


# --------------------------------------------------------------------------
# v0.4.0 — The Living Worlds: recaps, Engine Trace, goals, campfire, timelines
# --------------------------------------------------------------------------

@api.get("/campaigns/<cid>/recap")
def recap_view(cid):
    """Player-aware recap: when a multiplayer session is active, the token
    scopes what this specific traveler may see; solo voyages pass through."""
    try:
        player, _chid = _mp_resolve(cid)
        return jsonify(experience.recap(cid, player=player))
    except ValueError as exc:
        return _err(exc, 404)


@api.post("/campaigns/<cid>/recap/dismiss")
def recap_dismiss(cid):
    """Per-player dismissal: resolves the multiplayer identity (solo voyages
    use the 'local' viewer) and records THIS viewer's last-seen marker only."""
    try:
        player, _chid = _mp_resolve(cid)
        return jsonify(experience.dismiss_recap(cid, player=player))
    except ValueError as exc:
        return _err(exc, 404)


@api.get("/campaigns/<cid>/goals")
def goals_list(cid):
    return jsonify({"goals": experience.list_goals(cid)})


@api.post("/campaigns/<cid>/goals")
def goals_create(cid):
    body = _mp_body()
    try:
        player, _chid = _mp_resolve(cid)
        pid = player["id"] if player else "local"
        # a multiplayer guest may only create personal goals owned by
        # themselves; party goals and forged ownership are refused
        scope = body.get("scope", "party")
        if player and scope == "personal" and body.get("owner_player_id")                 and body["owner_player_id"] != player["id"]:
            raise mp.MpDenied("you cannot set another traveler as the owner")
        if player and scope == "personal" and not body.get("owner_player_id"):
            body = dict(body, owner_player_id=player["id"])
        return jsonify(experience.create_goal(
            cid, body.get("title", ""), body.get("target", 3),
            scope, pid, body.get("detail", "")))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/goals/<goal_id>/progress")
def goals_progress(cid, goal_id):
    """Voluntary player-authored progress. This endpoint can never produce
    engine-verified progress (no `verified` switch is exposed to clients);
    verified achievements come only from engine events."""
    body = _mp_body()
    try:
        delta = int(body.get("delta", 1))
    except (TypeError, ValueError):
        return _err(ValueError("delta must be an integer"))
    try:
        experience.goal_view_scoped(cid, goal_id)
    except ValueError as exc:
        return _err(exc, 404)
    try:
        player, _chid = _mp_resolve(cid)
        return jsonify(experience.goal_progress(cid, goal_id, delta,
                                                body.get("reason", "player progress"),
                                                verified=False, player=player))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/goals/<goal_id>/abandon")
def goals_abandon(cid, goal_id):
    try:
        experience.goal_view_scoped(cid, goal_id)
    except ValueError as exc:
        return _err(exc, 404)
    try:
        player, _chid = _mp_resolve(cid)
        return jsonify(experience.abandon_goal(cid, goal_id, player=player))
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.get("/campaigns/<cid>/campfire")
def campfire_list(cid):
    return jsonify({"stories": experience.list_stories(cid)})


@api.get("/campaigns/<cid>/campfire/shareable")
def campfire_shareable(cid):
    """What the requesting teller may explicitly share at the fire: their own
    places and specific eligible memories (empty for spectators).

    Hotfix 4: failed multiplayer authorization is NEVER treated as "solo".
    When an active session exists, a valid player token is required
    (`_mp_resolve` → `mp.auth` raises → 403, with no character-owned
    knowledge in the response); the solo fallback to the campaign's own
    character is reached only when NO multiplayer session exists."""
    try:
        player, _chid = _mp_resolve(cid)
    except mp.MpDenied as exc:
        return _err(exc, 403)
    except ValueError as exc:  # includes mp.MpError
        return _err(exc)
    try:
        teller = player["character_id"] if player \
            else experience.teller_character(cid, None)
        return jsonify(experience.shareable_knowledge(cid, teller))
    except ValueError as exc:
        return _err(exc, 404)


@api.post("/campaigns/<cid>/campfire")
def campfire_add(cid):
    body = _mp_body()
    try:
        player, _chid = _mp_resolve(cid)
        pid = player["id"] if player else "local"
        pname = player["display_name"] if player else "the local player"
        return jsonify(experience.add_story(cid, pid, pname, body.get("kind", "story"),
                                            body.get("text", ""),
                                            body.get("related_event_seq"),
                                            share_refs=body.get("share")))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/timelines")
def timeline_branch(cid):
    body = _mp_body()
    try:
        player, _chid = _mp_resolve(cid)
        return jsonify(experience.branch_campaign(
            cid, body.get("checkpoint_id"), body.get("name", "Alternate Timeline"),
            player["id"] if player else "local"))
    except ValueError as exc:
        return _err(exc, 404)


@api.get("/campaigns/<cid>/timelines")
def timeline_list(cid):
    return jsonify({"branches": experience.list_branches(cid)})


@api.get("/campaigns/<cid>/timelines/compare/<other_cid>")
def timeline_compare(cid, other_cid):
    try:
        return jsonify(experience.compare_timelines(cid, other_cid))
    except ValueError as exc:
        return _err(exc, 404)


@api.post("/forge/collab/<draft_id>/playtest")
def workshop_playtest(draft_id):
    """Launch a draft world into an isolated playtest portal — a real campaign
    from the draft pack; approved worlds and real saves are untouched."""
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.start_playtest(draft_id, body.get("name", "")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.post("/forge/collab/<draft_id>/playtest/stop")
def workshop_playtest_stop(draft_id):
    _forbid_guest_admin()
    body = _mp_body()
    try:
        return jsonify(forge.stop_playtest(draft_id, body.get("campaign_id", "")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)


@api.get("/forge/collab/<draft_id>/playtest/report")
def workshop_playtest_report(draft_id):
    _forbid_guest_admin()
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(forge.playtest_report(draft_id, body.get("campaign_id", "")))
    except (ValueError, forge.ForgeError) as exc:
        return _err(exc)
