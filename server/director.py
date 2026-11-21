"""Saturday Multiverse — The Living Campaign Director.

Tracks the larger narrative structure across sessions: quests, mysteries,
threats, character arcs, faction stances and consequences — with the actual
events as evidence. The Director may SUGGEST pacing beats; it never forces
events, never rewrites history, never touches dice or rewards, and can be
turned down or off per campaign. The engine owns the truth; the GM tells
the story; the Director remembers its continuity.
"""
from __future__ import annotations

from . import db
from .db import jdumps, jloads, new_id, utcnow

MODES = ("off", "gentle", "active")
CADENCE = 5  # pacing consideration every N campaign turns (gentle)
THREAD_KINDS = ("quest", "mystery", "threat", "arc", "faction", "consequence")
STATUSES = ("introduced", "active", "dormant", "resolved", "failed", "abandoned")


def _threads(cid: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM director_threads WHERE campaign_id=? ORDER BY updated_at", (cid,))]


def _thread(cid: str, kind: str, title: str) -> dict | None:
    return next((t for t in _threads(cid)
                 if t["kind"] == kind and t["title"].lower() == title.lower()), None)


def track(cid: str, kind: str, title: str, status: str = "introduced",
          detail: dict | None = None, evidence: dict | None = None) -> dict:
    """Create or transition a thread. Transitions record the supporting event;
    an AI suggestion alone is never evidence."""
    if kind not in THREAD_KINDS or status not in STATUSES:
        raise ValueError("bad thread kind or status")
    t = _thread(cid, kind, title)
    if t:
        if t["status"] != status:
            db.execute(
                "UPDATE director_threads SET status=?, updated_at=? WHERE id=?",
                (status, utcnow(), t["id"]))
            ev = jloads(t["evidence_json"], [])
            ev.append({"ts": utcnow(), "status": status, **(evidence or {})})
            db.execute("UPDATE director_threads SET evidence_json=? WHERE id=?",
                       (jdumps(ev[-40:]), t["id"]))
        return _thread(cid, kind, title)
    tid = new_id("thr")
    db.execute(
        "INSERT INTO director_threads (id, campaign_id, kind, title, status,"
        " detail_json, evidence_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, cid, kind, title[:120], status, jdumps(detail or {}),
         jdumps([{"ts": utcnow(), "status": status, **(evidence or {})}]), utcnow(), utcnow()),
    )
    return _thread(cid, kind, title)


def seed(cid: str, pack: dict) -> None:
    """Seed threads from a world pack: quests, hidden mysteries, threats."""
    for q in pack.get("intro_quests", []):
        track(cid, "quest", q.get("title", "An open thread"), "introduced",
              {"source": "pack"})
    for s in pack.get("gm_secrets", [])[:6]:
        track(cid, "mystery", s[:80], "dormant", {"source": "gm_secret"})
    for kind in ("threat",):
        pass


def observe(cid: str, pack: dict) -> None:
    """Deterministic thread transitions from AUTHORITATIVE events only.
    Reads the event log; AI narration is never treated as having happened."""
    state = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))
    if not state:
        return
    st = jloads(state["state_json"], {})
    last = int(st.get("director_seq") or 0)
    from . import mp
    events = mp.events_since(cid, last, None)
    if not events:
        return
    for e in events:
        etype, data = e["type"], e.get("data", {})
        if etype == "quest_update":
            qid = str(data.get("quest_id", ""))
            status = data.get("status", "")
            title = next((q["title"] for q in pack.get("intro_quests", [])
                          if q.get("id") == qid), qid or "a quest")
            if status in ("done", "completed", "resolved"):
                track(cid, "quest", title, "resolved", evidence={"event": "quest_update", "seq": e["seq"]})
            elif status in ("failed",):
                track(cid, "quest", title, "failed", evidence={"event": "quest_update", "seq": e["seq"]})
            elif status:
                track(cid, "quest", title, "active", evidence={"event": "quest_update", "seq": e["seq"]})
        elif etype == "ending":
            for q in pack.get("intro_quests", []):
                t = _thread(cid, "quest", q["title"])
                if t and t["status"] in ("introduced", "active", "dormant"):
                    track(cid, "quest", q["title"], "resolved",
                          evidence={"event": "ending", "seq": e["seq"]})
        elif etype == "combat_victory":
            track(cid, "threat", f"Enemies of the party ({data.get('monster', 'foes')})",
                  "resolved", evidence={"event": "combat_victory", "seq": e["seq"]})
        elif etype == "combat_start":
            track(cid, "threat", f"Enemies of the party ({data.get('monster', 'foes')})",
                  "active", evidence={"event": "combat_start", "seq": e["seq"]})
        elif etype == "discovery":
            track(cid, "consequence", f"Discovery: {str(data.get('name', ''))[:60]}" or "A discovery",
                  "active", evidence={"event": "discovery", "seq": e["seq"]})
    st["director_seq"] = events[-1]["seq"]
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(st), cid))


def suggest(cid: str, pack: dict) -> list[dict]:
    """Optional pacing suggestions, subordinate to player agency. Suggestions
    are advisory lines for the GM; nothing is forced or auto-applied."""
    st = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?",
                             (cid,))["state_json"], {})
    mode = st.get("director_mode", "gentle")
    if mode == "off":
        return []
    turn = int((db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,)) or {"turn": 0})["turn"])
    cadence = CADENCE if mode == "gentle" else max(2, CADENCE // 2)
    if turn % cadence or turn == 0:
        return []
    out = []
    for t in _threads(cid):
        if t["kind"] == "quest" and t["status"] in ("introduced", "dormant"):
            out.append({"thread_id": t["id"], "kind": t["kind"], "title": t["title"],
                        "suggestion": f"The party has left '{t['title']}' untouched — "
                                      f"let the world press it gently, if they ignore it again."})
        if t["kind"] == "mystery" and t["status"] == "dormant":
            out.append({"thread_id": t["id"], "kind": t["kind"], "title": t["title"],
                        "suggestion": "A small clue could surface naturally — "
                                      "only if the players look at all."})
    return out[:3]


def set_mode(cid: str, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("director mode must be off, gentle or active")
    st = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?",
                             (cid,))["state_json"], {})
    st["director_mode"] = mode
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(st), cid))
    return {"mode": mode}


def campaign_view(cid: str, pack: dict) -> dict:
    observe(cid, pack)
    threads = []
    for t in _threads(cid):
        t = dict(t)
        t["detail"] = jloads(t.pop("detail_json"), {})
        t["evidence"] = jloads(t.pop("evidence_json"), [])
        threads.append(t)
    return {"threads": threads,
            "suggestions": suggest(cid, pack),
            "mode": jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?",
                                        (cid,))["state_json"], {}).get("director_mode", "gentle")}
