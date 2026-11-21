"""Saturday Multiverse — REST API blueprint.

Solo-first, multiplayer-aware: every campaign mutation is a single
authenticated request against host-authoritative state. Milestone 3 will
attach player tokens and sync events to these same endpoints.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from flask import Blueprint, Response, jsonify, request

from . import ai, config, db, gm, qr, worldpacks

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
    return jsonify({"error": str(exc)}), code


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
    return jsonify({"ai": ai.masked_ai_config(),
                    "host": {"token_required": bool(config.HOST_TOKEN),
                             "bind": f"{config.HOST}:{config.PORT}"}})


@api.put("/settings")
def put_settings():
    body = request.get_json(silent=True) or {}
    if "ai" in body:
        try:
            ai.set_ai_config(body["ai"])
        except (ValueError, TypeError) as exc:
            return _err(exc)
    return jsonify({"ai": ai.masked_ai_config()})


@api.post("/ai/test")
def ai_test():
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
        return jsonify(gm.campaign_view(cid))
    except ValueError as exc:
        return _err(exc, 404)


@api.delete("/campaigns/<cid>")
def campaign_archive(cid):
    if not gm.get_campaign(cid):
        return _err(ValueError("campaign not found"), 404)
    gm.archive_campaign(cid)
    return jsonify({"ok": True})


@api.post("/campaigns/<cid>/action")
def campaign_action(cid):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(gm.run_turn(cid, body.get("text", "")))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/choose")
def campaign_choose(cid):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(gm.choose(cid, body.get("choice_id", "")))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/check")
def campaign_check(cid):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(gm.manual_check(cid, body.get("skill", ""), bool(body.get("hard"))))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/travel")
def campaign_travel(cid):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(gm.travel(cid, body.get("location_id", "")))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/rest")
def campaign_rest(cid):
    try:
        return jsonify(gm.rest(cid))
    except ValueError as exc:
        return _err(exc)


@api.post("/campaigns/<cid>/use_item")
def campaign_use_item(cid):
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(gm.use_item(cid, body.get("item_id", "")))
    except ValueError as exc:
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
