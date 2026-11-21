"""Saturday Multiverse — REST API blueprint.

Solo-first, multiplayer-aware. Every campaign mutation is a single
authenticated request against host-authoritative state. When a campaign
carries a shared-shore session, the same endpoints accept an `X-MP-Token`
header, resolve the caller to a player row, and scope every change to that
player's character. Guests never see the host's AI configuration.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from flask import Blueprint, Response, jsonify, request

from . import ai, config, db, gen, gm, legacy, mp, qr, worldpacks

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


def _mp_emit_result(cid: str, player, res: dict, kind: str) -> None:
    """Broadcast one authoritative result to the party."""
    session = mp._session(cid)
    if not session:
        return
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
    })


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
    return jsonify({"ok": True, "name": config.APP_NAME, "version": config.APP_VERSION,
                    "data_dir": str(config.DATA_DIR)})


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
        _mp_turn(cid, player)
        with _mp_locked(cid):
            res = gm.run_turn(cid, body.get("text", ""), chid)
            _mp_emit_result(cid, player, res, "narration")
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
            _mp_emit_result(cid, player, res, "narration")
        return jsonify(res)
    except (ValueError, mp.MpDenied) as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/check")
def campaign_check(cid):
    body = request.get_json(silent=True) or {}
    try:
        player, chid = _mp_resolve(cid)
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
        player, _chid = _mp_resolve(cid)
        with _mp_locked(cid):
            res = legacy.talk(cid, body.get("npc_id", ""), body.get("topic", "the shore"))
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
        player = _mp_auth(cid)
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
        return jsonify({"events": mp.events_since(cid, since, player),
                        "latest_seq": mp.latest_seq(cid)})
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
