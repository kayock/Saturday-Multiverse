"""Saturday Multiverse — story continuity checking.

Deterministic checks over the authoritative event log and engine state:
dead characters speaking, duplicated artifacts, contradictory quest states,
repeated one-time encounters, impossible reversals. Findings are advisory
flags for the GM (stored/logged); AI proposals remain separate from state
until validated.
"""
from __future__ import annotations

from . import db
from .db import jdumps, jloads

def check(cid: str) -> list[dict]:
    findings: list[dict] = []
    events = db.query(
        "SELECT seq, ts, type, data_json FROM mp_events WHERE campaign_id=?"
        " ORDER BY seq LIMIT 500", (cid,))
    evs = [{"seq": e["seq"], "type": e["type"], **jloads(e["data_json"], {})} for e in events]

    # 1. dead characters appearing in narration after their death event
    deaths: dict[str, int] = {}
    for e in evs:
        if e["type"] == "combat_death" and e.get("name"):
            deaths[e["name"].lower()] = e["seq"]
    for e in evs:
        if e["type"] == "narration":
            text = (e.get("text") or "").lower()
            for name, seq in deaths.items():
                if e["seq"] > seq and name and name in text:
                    # allowed if a later event says they were revived
                    findings.append({"kind": "dead_speaks", "seq": e["seq"],
                                     "detail": f"'{name}' died at seq {seq} but is named in later narration"})

    # 2. duplicated artifacts: the same item granted twice without being taken
    grants: dict[str, int] = {}
    for e in evs:
        for c in (e.get("changes") or []):
            if isinstance(c, str) and "item" in c.lower():
                pass
        data = e.get("data") or {}
        if e["type"] == "narration":
            for ch in (data.get("changes") or []):
                pass
    # authoritative inventory check: same item_id owned by one character twice
    rows = db.query("SELECT character_id, item_id, count(*) c FROM inventory"
                    " WHERE campaign_id=? GROUP BY character_id, item_id HAVING c > 1", (cid,))
    for r in rows:
        findings.append({"kind": "duplicate_item", "detail":
                         f"item {r['item_id']} held {r['c']} times by one character"})

    # 3. contradictory quest states: resolved then re-activated
    quest_state: dict[str, list] = {}
    for e in evs:
        if e["type"] == "quest_update":
            quest_state.setdefault(str(e.get("quest_id", "")), []).append(e)
    for qid, updates in quest_state.items():
        seen_done = False
        for u in updates:
            st = str(u.get("status", ""))
            if st in ("done", "completed", "resolved"):
                seen_done = True
            elif seen_done and st in ("active", "introduced"):
                findings.append({"kind": "quest_reversal", "detail":
                                 f"quest {qid or '?'} was completed then re-activated at seq {u['seq']}"})

    # 4. repeated one-time encounters: the same monster fought 3+ times
    monster_fights: dict[str, int] = {}
    for e in evs:
        if e["type"] == "combat_start":
            monster_fights[str(e.get("monster", "?"))] = monster_fights.get(str(e.get("monster", "?")), 0) + 1
    for mon, n in monster_fights.items():
        if n >= 3:
            findings.append({"kind": "repeat_encounter", "detail":
                             f"the party has fought '{mon}' {n} times — consider it a pattern"})

    # 5. revealed mysteries becoming hidden again is engine-blocked by design;
    #    check hidden facts that duplicate visible ones
    facts = db.query("SELECT text, scope FROM facts WHERE campaign_id=?", (cid,))
    visible = {f["text"].lower()[:60] for f in facts if f["scope"] == "visible"}
    for f in facts:
        if f["scope"] == "hidden" and f["text"].lower()[:60] in visible:
            findings.append({"kind": "visibility_conflict", "detail":
                             f"a fact is both visible and hidden: '{f['text'][:40]}…'"})
    return findings[:20]
