"""Saturday Multiverse — Game Master engine.

Division of labor (the core honesty rule of this project):

- The AI narrates and *proposes*: prose, NPC lines, one check request,
  an inventory request, memory facts, quick suggestions.
- The application *decides*: rolls every die, validates every proposal
  against the world-pack catalog, applies every state change, and writes
  the event log.

If no model is configured (or the model misbehaves), the "Offline
Storyteller" fallback keeps the game fully playable using scene data and
the same deterministic mechanics. The client is always told which mode
produced a turn (`meta.ai_used`), so a fallback is never passed off as AI.
"""
from __future__ import annotations

import json
import secrets

from . import ai, config, db, rules, worldpacks
from .db import jdumps, jloads, new_id, utcnow

VALID_SKILLS = ["notice", "lore", "persuade", "fight", "endure", "bind"]
STATS = ["wits", "might", "mettle", "bind"]

TIDE_CYCLE = 12          # drift beats per full tide cycle
TIDE_LOW_FROM = 6        # second half of the cycle is low tide
DECK_CADENCE = 3        # draw an omen every N turns
MAX_OPEN_QUESTS = 8


# ==========================================================================
# Time, tide and weather (all derived or stored state — never AI-driven)
# ==========================================================================

def tide_for(drift: int) -> str:
    return "low" if (drift % TIDE_CYCLE) >= TIDE_LOW_FROM else "high"


def _pick_weighted(options: list[dict]) -> dict:
    total = sum(max(1, o.get("weight", 1)) for o in options)
    roll = secrets.randbelow(total)
    acc = 0
    for o in options:
        acc += max(1, o.get("weight", 1))
        if roll < acc:
            return o
    return options[-1]


def advance_time(campaign: dict, beats: int = 1) -> dict:
    """Advance drift, refresh weather on boundaries. Always re-reads state
    from the database so it never clobbers a concurrent update."""
    pack = worldpacks.load_pack(campaign["pack_id"]) or {}
    row = db.query_one("SELECT drift, state_json FROM campaigns WHERE id=?", (campaign["id"],))
    state = jloads(row["state_json"], {})
    drift = row["drift"] + beats
    old_weather = state.get("weather")
    if (row["drift"] // 5) != (drift // 5) or not old_weather:
        table = pack.get("weather") or [{"key": "mist", "weight": 1, "desc": "Sea mist."}]
        w = _pick_weighted(table)
        state["weather"] = {"key": w["key"], "desc": w.get("desc", w["key"])}
    db.execute(
        "UPDATE campaigns SET drift=?, state_json=?, updated_at=? WHERE id=?",
        (drift, jdumps(state), utcnow(), campaign["id"]),
    )
    campaign["drift"] = drift
    return state


# ==========================================================================
# Campaign lifecycle
# ==========================================================================

def create_campaign(name: str, pack_id: str, character_spec: dict) -> str:
    pack = worldpacks.load_pack(pack_id)
    if not pack:
        raise ValueError(f"unknown world pack: {pack_id}")
    name = (name or "").strip()[:80] or "A Voyage Without a Name"
    char_name = (character_spec.get("name") or "").strip()[:40]
    if not char_name:
        raise ValueError("the wanderer needs a name")
    archetype_id = character_spec.get("archetype", "")
    arc = worldpacks.get_archetype(pack, archetype_id)
    if not arc:
        raise ValueError("pick a road: one of the pack's archetypes")

    attrs = dict(arc.get("stats", {}))
    extra = character_spec.get("extra_stat", {})
    if extra:
        stat = str(extra.get("stat", "")).lower()
        if stat not in STATS:
            raise ValueError("extra point must go to wits, might, mettle or bind")
        attrs[stat] = attrs.get(stat, 0) + 1
    specialty = character_spec.get("specialty", "")
    if specialty and specialty not in VALID_SKILLS:
        raise ValueError("unknown specialty skill")

    cid = new_id("cmp")
    chid = new_id("chr")
    ts = utcnow()
    vigor_max = 10 + attrs.get("might", 0)
    nerve_max = 10 + attrs.get("mettle", 0)
    skills = {s: (1 if s == specialty else 0) for s in VALID_SKILLS}

    portrait = {
        "seed": character_spec.get("portrait_seed") or new_id("seed"),
        "palette": arc.get("palette", "tide"),
        "archetype": archetype_id,
    }
    db.execute(
        "INSERT INTO characters (id, campaign_id, name, archetype, portrait_json,"
        " attributes_json, skills_json, vigor, vigor_max, nerve, nerve_max, data_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            chid, cid, char_name, archetype_id, jdumps(portrait), jdumps(attrs),
            jdumps(skills), vigor_max, vigor_max, nerve_max, nerve_max,
            jdumps({"specialty": specialty, "history": character_spec.get("history", "")[:400]}),
        ),
    )
    hub = pack.get("hub_location") or (pack["locations"][0]["id"] if pack["locations"] else "")
    state = {
        "flags": {},
        "adventure_id": None,
        "beat": None,
        "deck_mode": "agent",
        "last_omen": None,
        "omen_bonus": None,
        "weather": {"key": "mist", "desc": "Low sea mist."},
        "endings_seen": [],
    }
    db.execute(
        "INSERT INTO campaigns (id, name, pack_id, character_id, scene_id, location_id,"
        " turn, drift, state_json, summary, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?, ?,0,0,?,?, 'active', ?, ?)",
        (cid, name, pack_id, chid, "hub", hub, jdumps(state), "", ts, ts),
    )
    for item_id in arc.get("kit", []):
        give_item(cid, pack, item_id, silent=True)
    for fact in pack.get("intro_facts", []):
        db.execute(
            "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (new_id("fct"), cid, ts, fact[:300], "visible", 2, "pack"),
        )
    for quest in pack.get("intro_quests", []):
        db.execute(
            "INSERT INTO quests (id, campaign_id, quest_id, title, status, notes_json)"
            " VALUES (?,?,?,?, 'open', '[]')",
            (new_id("qst"), cid, quest["id"], quest["title"][:120]),
        )
    loc = worldpacks.get_location(pack, hub) or {}
    db.add_journal(cid, f"The voyage begins at {loc.get('name', hub)}. {loc.get('desc', '')}", "auto")
    db.log_event(cid, "campaign_created", {"name": name, "pack": pack_id, "archetype": archetype_id})
    db.add_transcript(cid, "system", f"Campaign '{name}' forged on {ts}.")
    return cid


def get_campaign(cid: str) -> dict | None:
    row = db.query_one("SELECT * FROM campaigns WHERE id=? AND status='active'", (cid,))
    return dict(row) if row else None


def get_character(cid: str) -> dict | None:
    row = db.query_one("SELECT * FROM characters WHERE campaign_id=?", (cid,))
    if not row:
        return None
    ch = dict(row)
    ch["attributes"] = jloads(ch.pop("attributes_json"), {})
    ch["skills"] = jloads(ch.pop("skills_json"), {})
    ch["portrait"] = jloads(ch.pop("portrait_json"), {})
    ch["data"] = jloads(ch.pop("data_json"), {})
    return ch


def list_campaigns() -> list[dict]:
    rows = db.query(
        "SELECT c.id, c.name, c.pack_id, c.location_id, c.turn, c.updated_at,"
        " ch.name AS char_name, ch.archetype, ch.vigor, ch.vigor_max, ch.nerve, ch.nerve_max"
        " FROM campaigns c LEFT JOIN characters ch ON ch.campaign_id = c.id"
        " WHERE c.status='active' ORDER BY c.updated_at DESC"
    )
    return [dict(r) for r in rows]


def archive_campaign(cid: str) -> None:
    db.execute("UPDATE campaigns SET status='archived', updated_at=? WHERE id=?", (utcnow(), cid))
    db.log_event(cid, "campaign_archived", {})


# ==========================================================================
# Inventory
# ==========================================================================

def give_item(cid: str, pack: dict, item_id: str, qty: int = 1, silent: bool = False) -> dict | None:
    item = worldpacks.get_item(pack, item_id)
    if not item:
        return None
    qty = max(1, min(9, int(qty)))
    row = db.query_one(
        "SELECT id, qty FROM inventory WHERE campaign_id=? AND item_id=?", (cid, item_id)
    )
    if row:
        db.execute("UPDATE inventory SET qty=? WHERE id=?", (min(9, row["qty"] + qty), row["id"]))
    else:
        db.execute(
            "INSERT INTO inventory (id, campaign_id, item_id, name, kind, qty, equipped, data_json)"
            " VALUES (?,?,?,?,?,1,0,?)",
            (new_id("itm"), cid, item_id, item["name"], item.get("kind", "trinket"), jdumps(item)),
        )
    if not silent:
        db.log_event(cid, "item_give", {"item_id": item_id, "qty": qty})
    return {"item_id": item_id, "name": item["name"], "qty": qty}


def take_item(cid: str, pack: dict, item_id: str, qty: int = 1) -> dict | None:
    row = db.query_one(
        "SELECT id, name, qty FROM inventory WHERE campaign_id=? AND item_id=?", (cid, item_id)
    )
    if not row:
        return None
    item = worldpacks.get_item(pack, item_id) or {"name": row["name"]}
    qty = max(1, min(row["qty"], int(qty)))
    if row["qty"] - qty <= 0:
        db.execute("DELETE FROM inventory WHERE id=?", (row["id"],))
    else:
        db.execute("UPDATE inventory SET qty=? WHERE id=?", (row["qty"] - qty, row["id"]))
    db.log_event(cid, "item_take", {"item_id": item_id, "qty": qty})
    return {"item_id": item_id, "name": item["name"], "qty": qty}


def get_inventory(cid: str) -> list[dict]:
    rows = db.query(
        "SELECT item_id, name, kind, qty, data_json FROM inventory"
        " WHERE campaign_id=? ORDER BY kind, name",
        (cid,),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["item"] = jloads(d.pop("data_json"), {})
        out.append(d)
    return out


# ==========================================================================
# Effects application (single choke-point for every state mutation)
# ==========================================================================

def apply_effects(cid: str, pack: dict, effects: dict, changes: list[str]) -> dict:
    """Apply a validated effects dict; append human-readable change lines."""
    ch = get_character(cid)
    if not isinstance(effects, dict):
        return {}
    safe = {}

    if effects.get("journal"):
        db.add_journal(cid, str(effects["journal"])[:400], "auto")
        changes.append("Journal entry added.")
        safe["journal"] = True
    if effects.get("fact"):
        f = str(effects["fact"])[:300]
        db.execute(
            "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (new_id("fct"), cid, utcnow(), f, "visible", 2, "game"),
        )
        changes.append(f"Remembered: {f}")
    if effects.get("hidden_fact"):
        f = str(effects["hidden_fact"])[:300]
        db.execute(
            "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (new_id("fct"), cid, utcnow(), f, "hidden", 3, "game"),
        )
        safe["hidden_fact"] = True
    for g in (effects.get("item_give") or [])[:4]:
        if isinstance(g, dict) and give_item(cid, pack, str(g.get("item_id")), int(g.get("qty", 1))):
            changes.append(f"Gained: {worldpacks.get_item(pack, g['item_id'])['name']}.")
    for t in (effects.get("item_take") or [])[:4]:
        if isinstance(t, dict) and take_item(cid, pack, str(t.get("item_id")), int(t.get("qty", 1))):
            changes.append(f"Lost: {t['item_id'].replace('_', ' ')}.")
    qu = effects.get("quest_update")
    if isinstance(qu, dict) and qu.get("quest_id"):
        _quest_update(cid, qu)
        changes.append(f"Quest updated: {qu['quest_id']}.")
    harm = effects.get("harm")
    if isinstance(harm, dict) and ch:
        amount = max(0, min(6, int(harm.get("amount", 1))))
        htype = "nerve" if harm.get("type") == "nerve" else "vigor"
        rules.apply_harm(ch, amount, htype)
        _persist_character(ch)
        changes.append(f"{'Nerve' if htype == 'nerve' else 'Vigor'} −{amount}.")
    heal = effects.get("heal")
    if isinstance(heal, dict) and ch:
        if heal.get("vigor"):
            ch["vigor"] = min(ch["vigor_max"], ch["vigor"] + int(heal["vigor"]))
        if heal.get("nerve"):
            ch["nerve"] = min(ch["nerve_max"], ch["nerve"] + int(heal["nerve"]))
        _persist_character(ch)
        changes.append("Restored some strength.")
    if effects.get("flag"):
        state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
        flags = set(state.get("flags", []))
        for fl in ([effects["flag"]] if isinstance(effects["flag"], str) else list(effects["flag"])[:5]):
            flags.add(str(fl)[:60])
        state["flags"] = sorted(flags)
        db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
    if effects.get("discover"):
        loc_id = str(effects["discover"])
        db.execute(
            "INSERT INTO locations_state (campaign_id, location_id, discovered, data_json)"
            " VALUES (?,?,1,'{}') ON CONFLICT(campaign_id, location_id)"
            " DO UPDATE SET discovered=1",
            (cid, loc_id),
        )
        loc = worldpacks.get_location(pack, loc_id) or {}
        changes.append(f"Discovered: {loc.get('name', loc_id)}.")
        db.add_journal(cid, f"Discovered {loc.get('name', loc_id)}.", "discovery")
    rel = effects.get("npc_rel")
    if isinstance(rel, dict) and rel.get("npc_id"):
        _npc_rel(cid, pack, str(rel["npc_id"]), int(rel.get("delta", 0)))
    if effects.get("return_shore"):
        hub = pack.get("hub_location", "tidegate")
        state = jloads(
            db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {}
        )
        state["beat"] = None
        state["adventure_done"] = True
        db.execute(
            "UPDATE campaigns SET location_id=?, scene_id='hub', state_json=?, updated_at=? WHERE id=?",
            (hub, jdumps(state), utcnow(), cid),
        )
        changes.append("Returned to the Living Shore.")
    return safe


def _quest_update(cid: str, qu: dict) -> None:
    qid = str(qu["quest_id"])[:60]
    status = qu.get("status")
    if status not in ("open", "done", "failed", None):
        status = None
    existing = db.query_one(
        "SELECT id FROM quests WHERE campaign_id=? AND quest_id=?", (cid, qid)
    )
    if not existing:
        open_count = db.query_one(
            "SELECT COUNT(*) AS n FROM quests WHERE campaign_id=? AND status='open'", (cid,)
        )["n"]
        if open_count >= MAX_OPEN_QUESTS:
            return
        db.execute(
            "INSERT INTO quests (id, campaign_id, quest_id, title, status, notes_json)"
            " VALUES (?,?,?,?,?,?)",
            (new_id("qst"), cid, qid, str(qu.get("title", qid))[:120],
             status or "open", jdumps([str(qu.get("note", ""))[:200]]) if qu.get("note") else "[]"),
        )
    elif status:
        notes = []
        if qu.get("note"):
            notes.append(str(qu["note"])[:200])
        db.execute(
            "UPDATE quests SET status=?, notes_json=notes_json WHERE id=?",
            (status, existing["id"]),
        )
        if notes:
            db.execute(
                "UPDATE quests SET notes_json=? WHERE id=?",
                (jdumps(notes), existing["id"]),
            )


def _npc_rel(cid: str, pack: dict, npc_id: str, delta: int) -> None:
    npc = worldpacks.get_npc(pack, npc_id)
    name = npc["name"] if npc else npc_id
    row = db.query_one(
        "SELECT id, data_json FROM npcs WHERE campaign_id=? AND npc_id=?", (cid, npc_id)
    )
    if row:
        data = jloads(row["data_json"], {"rel": 0, "facts": []})
        data["rel"] = max(-5, min(5, data.get("rel", 0) + delta))
        data["met"] = True
        db.execute("UPDATE npcs SET data_json=? WHERE id=?", (jdumps(data), row["id"]))
    else:
        db.execute(
            "INSERT INTO npcs (id, campaign_id, npc_id, name, data_json) VALUES (?,?,?,?,?)",
            (new_id("npc"), cid, npc_id, name,
             jdumps({"rel": max(-5, min(5, delta)), "facts": [], "met": True})),
        )


def _persist_character(ch: dict) -> None:
    db.execute(
        "UPDATE characters SET vigor=?, nerve=?, attributes_json=?, skills_json=?, data_json=?"
        " WHERE id=?",
        (ch["vigor"], ch["nerve"], jdumps(ch["attributes"]), jdumps(ch["skills"]),
         jdumps(ch.get("data", {})), ch["id"]),
    )


# ==========================================================================
# Dice
# ==========================================================================

def _mods_for(ch: dict, skill: str) -> tuple[int, str]:
    stat = rules.skill_to_stat(skill)
    stat_mod = int(ch["attributes"].get(stat, 0))
    skill_mod = int(ch["skills"].get(skill, 0))
    return stat_mod + skill_mod, stat


def _roll_and_log(cid: str, ch: dict, skill: str, shift: int = 0, sit_mod: int = 0,
                  harm_type: str = "", reason: str = "") -> dict:
    mod, stat = _mods_for(ch, skill)
    result = rules.roll_check(stat_mod=mod, sit_mod=sit_mod, shift=shift)
    outcome = result.outcome
    harm = rules.harm_for(outcome)
    if harm and ch:
        htype = harm_type or ("vigor" if skill in ("fight", "endure") else "nerve")
        rules.apply_harm(ch, harm, htype)
        _persist_character(ch)
    db.execute(
        "INSERT INTO dicelog (id, campaign_id, ts, kind, skill, stat_mod, dice_json, total,"
        " difficulty, outcome, effect, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("dce"), cid, utcnow(), "check", skill, mod, jdumps(result.dice),
         result.total, 7 + shift, outcome, rules.harm_for(outcome),
         (reason or "")[:120]),
    )
    db.log_event(cid, "dice_roll", {"skill": skill, "dice": result.dice, "total": result.total,
                                    "outcome": outcome, "reason": reason[:120]})
    return {
        "dice": result.dice,
        "mod": mod,
        "sit_mod": sit_mod,
        "total": result.total,
        "outcome": outcome,
        "text": result.text,
        "harm": harm,
        "harm_type": harm_type or ("vigor" if skill in ("fight", "endure") else "nerve"),
    }


def manual_check(cid: str, skill: str, hard: bool = False) -> dict:
    ch = get_character(cid)
    if not ch:
        raise ValueError("no character")
    if skill not in VALID_SKILLS:
        raise ValueError(f"skill must be one of {VALID_SKILLS}")
    shift = -1 if hard else 0
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    sit = _consume_omen(state, skill)
    roll = _roll_and_log(cid, ch, skill, shift=shift, sit_mod=sit, reason="manual roll")
    if sit:
        db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
    return roll


def _consume_omen(state: dict, skill: str) -> int:
    """Consume a pending omen bonus/penalty that applies to this skill."""
    pending = state.get("omen_bonus")
    if not isinstance(pending, dict):
        return 0
    if pending.get("skill") in (None, skill) or pending.get("skill") == "any":
        state["omen_bonus"] = None
        return max(-2, min(2, int(pending.get("mod", 0))))
    return 0


# ==========================================================================
# Prompt building
# ==========================================================================

GM_JSON_CONTRACT = """Respond with ONLY one JSON object (no markdown fences, no prose outside it):
{"narration": "<=NARRATION_WORDS words, second person, present tense. If you call for a check, narrate up to the moment of truth and stop there.",
 "npc_lines": [{"npc": "<npc_id>", "line": "spoken dialogue"}],
 "check": null,
 "inventory_request": null,
 "memory": {"facts": [], "hidden_note": null, "relationships": {}},
 "choices": ["short suggested action", "..."],
 "scene_hint": "three-word scene header"}

Field rules:
- "check": null, or {"skill": one of notice|lore|persuade|fight|endure|bind, "hard": false, "reason": "<8 words>", "harm_type": "vigor|nerve"}. Call at most ONE check per turn, only when failure would matter.
- "inventory_request": null, or up to 2 entries {"action": "give|take", "item_id": "<from the catalog>", "qty": 1}. The app decides whether it happens.
- "memory.facts": up to 3 short durable facts worth remembering for weeks.
- "memory.hidden_note": null or one short secret (villain plans, hidden truths). NEVER reveal it in narration.
- "memory.relationships": {"<npc_id>": 1 or -1} when a relationship meaningfully shifts.
- "choices": 0-3 short suggested actions for the player. Suggestions only - the player may type anything.
- Never write the player's dialogue, thoughts or decisions. End the narration on a situation or question."""


def _trim(text: str, n: int) -> str:
    return (text or "").strip()[:n]


def _visible_facts(cid: str, limit: int = 10) -> list[str]:
    rows = db.query(
        "SELECT text FROM facts WHERE campaign_id=? AND scope='visible'"
        " ORDER BY importance DESC, ts DESC LIMIT ?",
        (cid, limit),
    )
    return [r["text"] for r in rows]


def _quests_for(cid: str) -> list[dict]:
    rows = db.query(
        "SELECT quest_id, title, status, notes_json FROM quests WHERE campaign_id=?"
        " ORDER BY status='open' DESC, rowid DESC LIMIT 12",
        (cid,),
    )
    return [{"id": r["quest_id"], "title": r["title"], "status": r["status"],
             "notes": jloads(r["notes_json"], [])} for r in rows]


def _history(cid: str, limit: int = 8) -> list[dict]:
    rows = db.query(
        "SELECT role, content FROM transcript WHERE campaign_id=? AND role IN ('player','gm')"
        " ORDER BY rowid DESC LIMIT ?",
        (cid, limit),
    )
    out = []
    for r in reversed(rows):
        role = "user" if r["role"] == "player" else "assistant"
        out.append({"role": role, "content": _trim(r["content"], 700)})
    return out


def _catalog_lines(pack: dict) -> str:
    items = pack.get("items", [])[:30]
    return "; ".join(f"{i['id']} ({i['name']})" for i in items)


def _npc_lines(pack: dict) -> str:
    npcs = pack.get("npcs", [])[:10]
    return "; ".join(f"{n['id']}: {n['name']} — {n.get('role', '')}" for n in npcs)


def build_system_prompt(pack: dict, ch: dict, campaign: dict, state: dict, narration_words: int) -> str:
    tide = tide_for(campaign["drift"])
    weather = (state.get("weather") or {}).get("key", "mist")
    return f"""You are the Game Master of SATURDAY MULTIVERSE — an intimate tabletop roleplaying session for one player.

WORLD PACK: {pack['name']} (v{pack.get('version', '1')})
GAME MASTER STYLE: {_trim(pack.get('gm_style', ''), 300)}

LORE (the world's truth; never contradict it):
{_trim(worldpacks.lore_text(pack), 1400)}

PLAYER CHARACTER: {_trim(ch['name'], 40)}, {ch['archetype']} — stats {ch['attributes']}, skills {ch['skills']}, Vigor {ch['vigor']}/{ch['vigor_max']}, Nerve {ch['nerve']}/{ch['nerve_max']}.
TIDE: {tide}. WEATHER: {weather}. TURN: {campaign['turn'] + 1}.

ITEM CATALOG (valid item_ids): {_catalog_lines(pack)}
NPCS (valid npc_ids): {_npc_lines(pack)}

RULES OF YOUR OFFICE:
1. Mechanics are the app's job. Never roll dice, never state outcomes of checks, never grant injuries or items in prose. If the story clearly needs an item moved, use inventory_request.
2. Never decide, say, or think anything for the player.
3. Stay inside this world pack's lore. No other universes, no mention of dice, rules, models or this interface.
4. Keep horror atmospheric — dread and strangeness, not torture-porn. Nothing sexual. This is a game for adults but a kind one.
5. Hidden story information stays hidden (see memory.hidden_note).
6. The tide and weather above are facts; the shore's mood follows them.

{GM_JSON_CONTRACT.replace('NARRATION_WORDS', str(narration_words))}"""


def build_user_prompt(campaign: dict, pack: dict, ch: dict, state: dict, action: str) -> str:
    loc = worldpacks.get_location(pack, campaign["location_id"]) or {}
    beat = state.get("beat")
    scene = worldpacks.get_scene(pack, state.get("adventure_id") or "", beat) if beat else None
    inventory = ", ".join(f"{i['name']} x{i['qty']}" for i in get_inventory(campaign["id"])) or "empty pack"
    quests = _quests_for(campaign["id"])
    open_q = "; ".join(f"{q['title']} ({q['status']})" for q in quests if q["status"] == "open") or "none"
    parts = [
        f"CURRENT LOCATION: {loc.get('name', campaign['location_id'])} — {_trim(loc.get('desc', ''), 260)}",
    ]
    if scene:
        parts.append(
            f"ADVENTURE SCENE: {scene.get('title', beat)} — {_trim(scene.get('brief', ''), 400)}"
        )
        if scene.get("gm_directive"):
            parts.append(f"SCENE DIRECTIVE: {_trim(scene['gm_directive'], 200)}")
    if state.get("last_omen"):
        parts.append(f"OMEN IN PLAY (weave subtly, never explain): {state['last_omen'].get('title', '')}")
    parts.append(f"INVENTORY: {inventory}")
    parts.append(f"OPEN QUESTS: {open_q}")
    facts = _visible_facts(campaign["id"])
    if facts:
        parts.append("KNOWN FACTS: " + " | ".join(facts))
    parts.append(f"PLAYER'S ACTION: {_trim(action, 800)}")
    return "\n".join(parts)


def get_inventory_full(cid: str) -> list[dict]:
    rows = db.query(
        "SELECT item_id, name, qty FROM inventory WHERE campaign_id=? ORDER BY name", (cid,)
    )
    return [dict(r) for r in rows]


# ==========================================================================
# The turn
# ==========================================================================

def run_turn(cid: str, action_text: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    ch = get_character(cid)
    if not ch:
        raise ValueError("campaign has no character")
    pack = worldpacks.load_pack(campaign["pack_id"])
    if not pack:
        raise ValueError("world pack missing")
    action_text = _trim(action_text, 800)
    if not action_text:
        raise ValueError("say what you do")

    state = jloads(campaign["state_json"], {})
    db.execute("UPDATE campaigns SET turn=?, updated_at=? WHERE id=?",
               (campaign["turn"] + 1, utcnow(), cid))
    campaign["turn"] += 1
    advance_time(campaign, 1)
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})

    # Omen deck: an original agent-managed deck, drawn on cadence.
    omen = None
    if state.get("deck_mode", "agent") == "agent" and campaign["turn"] % DECK_CADENCE == 0:
        omen = _draw_omen(cid, pack, state)

    cfg = ai.get_ai_config()
    meta = {"ai_used": False, "fallback_reason": None, "model": None, "latency_ms": None}
    contract = None
    if cfg.get("enabled"):
        messages = [
            {"role": "system", "content": build_system_prompt(
                pack, ch, campaign, state, int(cfg.get("narration_words", 220)))},
            *_history(cid),
            {"role": "user", "content": build_user_prompt(campaign, pack, ch, state, action_text)},
        ]
        try:
            text, callmeta = ai.chat(messages, cfg)
            contract = ai.extract_json(text)
            if contract is None or not isinstance(contract.get("narration"), str):
                # one strict retry
                messages.append({"role": "assistant", "content": text[:800]})
                messages.append({"role": "user", "content": "That was not valid JSON for the contract. Reply again with ONLY the JSON object."})
                text, callmeta = ai.chat(messages, cfg)
                contract = ai.extract_json(text)
            meta.update({"model": callmeta.get("model"), "latency_ms": callmeta.get("latency_ms")})
            if contract is None or not isinstance(contract.get("narration"), str):
                meta["fallback_reason"] = "model did not return the JSON contract"
                contract = None
        except ai.AiError as exc:
            meta["fallback_reason"] = exc.detail
            contract = None
    else:
        meta["fallback_reason"] = "AI Game Master disabled in Settings"

    changes: list[str] = []
    dice = None
    scene_hint = ""

    if contract:
        narration = _trim(contract.get("narration"), 4000)
        scene_hint = _trim(contract.get("scene_hint"), 40)
        # check request
        chk = contract.get("check")
        if isinstance(chk, dict) and chk.get("skill") in VALID_SKILLS:
            shift = -1 if chk.get("hard") else 0
            sit = _consume_omen(state, chk["skill"])
            harm_type = chk.get("harm_type") if chk.get("harm_type") in ("vigor", "nerve") else ""
            dice = _roll_and_log(cid, ch, chk["skill"], shift=shift, sit_mod=sit,
                                 harm_type=harm_type, reason=str(chk.get("reason", ""))[:120])
            state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
        # inventory request (validated against the pack catalog)
        inv_req = contract.get("inventory_request")
        if isinstance(inv_req, list):
            for req in inv_req[:2]:
                if not isinstance(req, dict):
                    continue
                item_id = str(req.get("item_id", ""))
                qty = int(req.get("qty", 1) or 1)
                if req.get("action") == "give" and worldpacks.get_item(pack, item_id):
                    if give_item(cid, pack, item_id, qty):
                        changes.append(f"Gained: {worldpacks.get_item(pack, item_id)['name']}.")
                elif req.get("action") == "take":
                    if take_item(cid, pack, item_id, qty):
                        changes.append(f"Lost: {item_id.replace('_', ' ')}.")
        # memory
        mem = contract.get("memory")
        if isinstance(mem, dict):
            for fact in (mem.get("facts") or [])[:3]:
                if isinstance(fact, str) and fact.strip():
                    db.execute(
                        "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (new_id("fct"), cid, utcnow(), _trim(fact, 300), "visible", 2, "gm"),
                    )
            if isinstance(mem.get("hidden_note"), str) and mem["hidden_note"].strip():
                db.execute(
                    "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (new_id("fct"), cid, utcnow(), _trim(mem["hidden_note"], 300), "hidden", 3, "gm"),
                )
            rels = mem.get("relationships")
            if isinstance(rels, dict):
                for npc_id, delta in list(rels.items())[:3]:
                    if worldpacks.get_npc(pack, str(npc_id)) and int(delta) in (-1, 1):
                        _npc_rel(cid, pack, str(npc_id), int(delta))
                        changes.append(f"{npc_id}: relationship shifted.")
        meta["ai_used"] = True
    else:
        narration = _fallback_narration(pack, campaign, state, action_text)

    # quick suggestions (AI only; the fallback offers none — the scene shows its own)
    choices = []
    if contract and isinstance(contract.get("choices"), list):
        choices = [_trim(str(c), 120) for c in contract["choices"][:3] if str(c).strip()]

    db.add_transcript(cid, "player", action_text)
    db.add_transcript(cid, "gm", narration, {"dice": dice, "changes": changes,
                                             "omen": omen, "scene_hint": scene_hint, **meta})
    summary = _trim(narration, 160)
    db.execute("UPDATE campaigns SET summary=?, state_json=?, updated_at=? WHERE id=?",
               (summary, jdumps(state), utcnow(), cid))
    db.log_event(cid, "turn", {"ai_used": meta["ai_used"], "turn": campaign["turn"]})
    db.add_journal(cid, _trim(narration, 240), "auto")

    return {
        "narration": narration,
        "scene_hint": scene_hint,
        "dice": dice,
        "changes": changes,
        "omen": omen,
        "choices": choices,
        "meta": meta,
    }


# --------------------------------------------------------------------------
# Offline Storyteller (honest fallback: same mechanics, template prose)
# --------------------------------------------------------------------------

FALLBACK_OPENERS = [
    "The shore holds its breath around you.",
    "Somewhere behind the mist, the sea keeps its own count of your steps.",
    "The light bends strangely here, as if the air remembers older nights.",
    "Sand shifts beneath your heels with a sound like slow breathing.",
    "Far off, the beam pulses once, twice, and waits.",
]

FALLBACK_CLOSERS = [
    "What do you do?",
    "The next move is yours.",
    "How do you go on?",
    "What do you reach for?",
]


def _fallback_narration(pack: dict, campaign: dict, state: dict, action: str) -> str:
    tide = tide_for(campaign["drift"])
    weather = (state.get("weather") or {}).get("key", "mist")
    loc = worldpacks.get_location(pack, campaign["location_id"]) or {}
    scene = worldpacks.get_scene(pack, state.get("adventure_id") or "", state.get("beat") or "") \
        if state.get("beat") else None
    flavor_pool = (scene or {}).get("flavor") or loc.get("flavor") or pack.get("fallback_flavor") or FALLBACK_OPENERS
    flavor = secrets.choice(flavor_pool)
    short_action = _trim(action, 140)
    return (
        f"{flavor} The {weather} thickens; the tide is {tide}. "
        f"You set yourself to it: {short_action} "
        f"(The AI Game Master is not connected — narration is running on the built-in "
        f"Offline Storyteller. Configure a model in Settings for full narration.) "
        f"{secrets.choice(FALLBACK_CLOSERS)}"
    )


# ==========================================================================
# Omen deck (original card set supplied by the world pack)
# ==========================================================================

def _draw_omen(cid: str, pack: dict, state: dict) -> dict | None:
    cards = worldpacks.get_omens(pack)
    if not cards:
        return None
    row = db.query_one("SELECT * FROM decks WHERE campaign_id=? AND deck_id='omens'", (cid,))
    if not row:
        deck = list(cards)
        for i in range(len(deck) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        draw, discard, held, draws = deck, [], [], 0
    else:
        draw = jloads(row["draw_json"], [])
        discard = jloads(row["discard_json"], [])
        held = jloads(row["held_json"], [])
        draws = row["draws"]
    card, draw, discard = rules.draw_from_deck(draw, discard)
    if not card:
        return None
    draws += 1
    if row:
        db.execute(
            "UPDATE decks SET draw_json=?, discard_json=?, held_json=?, draws=?"
            " WHERE campaign_id=? AND deck_id='omens'",
            (jdumps(draw), jdumps(discard), jdumps(held), draws, cid),
        )
    else:
        db.execute(
            "INSERT INTO decks (campaign_id, deck_id, draw_json, discard_json, held_json, draws)"
            " VALUES (?,?,?,?,?,?)",
            (cid, "omens", jdumps(draw), jdumps(discard), jdumps(held), draws),
        )
    state["last_omen"] = card
    if card.get("kind") == "edge" and card.get("boost"):
        state["omen_bonus"] = {"skill": card.get("boost"), "mod": 1}
    elif card.get("kind") == "complication":
        state["omen_bonus"] = {"skill": "any", "mod": -1}
    db.log_event(cid, "omen_draw", {"card_id": card.get("id"), "title": card.get("title")})
    return card


# ==========================================================================
# Scripted adventure beats
# ==========================================================================

def _choice_available(choice: dict, cid: str, state: dict) -> tuple[bool, str]:
    if choice.get("requires_flag") and choice["requires_flag"] not in state.get("flags", {}):
        return False, choice.get("locked_hint", "Something is missing.")
    if choice.get("forbid_flag") and choice["forbid_flag"] in state.get("flags", {}):
        return False, choice.get("locked_hint", "That path has closed.")
    if choice.get("requires_item"):
        row = db.query_one(
            "SELECT 1 FROM inventory WHERE campaign_id=? AND item_id=?",
            (cid, choice["requires_item"]),
        )
        if not row:
            return False, choice.get("locked_hint", "You lack what it requires.")
    return True, ""


def _effects_for(cid: str, pack: dict, effects: dict) -> list[str]:
    changes: list[str] = []
    if effects:
        apply_effects(cid, pack, effects, changes)
    return changes


def _set_beat(cid: str, state: dict, beat: str | None) -> None:
    state["beat"] = beat
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))


def choose(cid: str, choice_id: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    state = jloads(campaign["state_json"], {})
    adv = worldpacks.get_adventure(pack, state.get("adventure_id") or "")
    if not adv or not state.get("beat"):
        raise ValueError("no active adventure scene")
    scene = adv["scenes"].get(state["beat"])
    if not scene:
        raise ValueError("scene missing from pack")
    choice = next((c for c in scene.get("choices", []) if c.get("id") == choice_id), None)
    if not choice:
        raise ValueError("unknown choice for this scene")
    ok, why = _choice_available(choice, cid, state)
    if not ok:
        raise ValueError(why)

    changes: list[str] = []
    dice = None
    branch = None
    if isinstance(choice.get("check"), dict):
        chk = choice["check"]
        skill = chk.get("skill")
        if skill not in VALID_SKILLS:
            raise ValueError("bad check skill in pack data")
        ch = get_character(cid)
        shift = -1 if chk.get("hard") else 0
        sit = _consume_omen(state, skill)
        dice = _roll_and_log(cid, ch, skill, shift=shift, sit_mod=sit,
                             reason=choice.get("label", "")[:120])
        band = dice["outcome"]
        passed = band in ("clean", "surge")
        if band == "riptide" and chk.get("riptide_counts_pass"):
            passed = True
        branch = choice.get("on_pass") if passed else choice.get("on_fail") or {}
        branch = branch or {}
    else:
        branch = {
            "goto": choice.get("goto"),
            "effects": choice.get("effects", {}),
        }

    goto = branch.get("goto")
    if goto and goto in adv["scenes"]:
        _set_beat(cid, state, goto)
    changes += _effects_for(cid, pack, branch.get("effects") or {})

    # endings and epilogues
    ending_id = None
    epilogue = None
    eff = (branch.get("effects") or {})
    if eff.get("ending"):
        ending_id = str(eff["ending"])
        ending = adv.get("endings", {}).get(ending_id, {})
        epilogue = ending.get("text", "")
        if ending_id not in state.setdefault("endings_seen", []):
            state["endings_seen"].append(ending_id)
        state["adventure_done"] = True
        state["beat"] = None
        ret = ending.get("return_location", pack.get("hub_location"))
        db.execute(
            "UPDATE campaigns SET location_id=?, scene_id='hub', state_json=?, updated_at=? WHERE id=?",
            (ret, jdumps(state), utcnow(), cid),
        )

    # narration: prefer a live GM bridge, fall back to the scene's own text
    narration = None
    if goto and goto in adv["scenes"]:
        new_scene = adv["scenes"][goto]
        narration = _gm_scene_bridge(cid, pack, campaign, choice, new_scene) if ai.get_ai_config().get("enabled") else None
        if not narration:
            narration = _trim(new_scene.get("intro", ""), 1200) or new_scene.get("title", "")
    elif epilogue:
        narration = epilogue
    else:
        narration = "The moment passes."

    db.add_transcript(cid, "player", f"[chose] {choice.get('label', choice_id)}")
    db.add_transcript(cid, "gm", narration, {"dice": dice, "changes": changes, "choice_id": choice_id})
    db.add_journal(cid, _trim(narration, 240), "auto")
    advance_time(campaign, 1)
    return {"narration": narration, "dice": dice, "changes": changes,
            "ending": ending_id, "scene": goto, "meta": {"ai_used": bool(narration and ending_id is None and not epilogue)}}


def _gm_scene_bridge(cid: str, pack: dict, campaign: dict, choice: dict, new_scene: dict) -> str | None:
    """Short AI narration of the arrival into a scripted scene. Fail-safe."""
    try:
        ch = get_character(cid)
        cfg = ai.get_ai_config()
        sys_p = build_system_prompt(pack, ch, campaign, jloads(campaign["state_json"], {}), 110)
        user_p = (
            f"The player just chose: \"{choice.get('label', '')}\". "
            f"Narrate ONLY their arrival into this scene (no check, no items):\n"
            f"SCENE: {new_scene.get('title', '')} — {_trim(new_scene.get('brief', ''), 320)}\n"
            f"Respond with ONLY the JSON contract object; narration <=110 words."
        )
        text, _ = ai.chat([{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}], cfg)
        data = ai.extract_json(text)
        if data and isinstance(data.get("narration"), str):
            return _trim(data["narration"], 900)
    except ai.AiError:
        pass
    return None


# ==========================================================================
# Travel, rest, items
# ==========================================================================

def travel(cid: str, location_id: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    loc = worldpacks.get_location(pack, location_id)
    if not loc:
        raise ValueError("unknown location")
    state = jloads(campaign["state_json"], {})

    # gating: tide
    req = loc.get("requires") or {}
    tide = tide_for(campaign["drift"])
    if req.get("tide") and req["tide"] != tide:
        raise ValueError(f"The {loc['name']} only shows itself at {req['tide']} tide (now: {tide}).")
    # gating: discovery
    disc_row = db.query_one(
        "SELECT discovered FROM locations_state WHERE campaign_id=? AND location_id=?",
        (cid, location_id),
    )
    discovered = bool(disc_row and disc_row["discovered"]) or loc.get("known", False)
    if req.get("discovered") and not discovered:
        raise ValueError("You haven't found the way there yet.")

    db.execute(
        "INSERT INTO locations_state (campaign_id, location_id, discovered, data_json)"
        " VALUES (?,?,1,'{}') ON CONFLICT(campaign_id, location_id) DO UPDATE SET discovered=1",
        (cid, location_id),
    )

    narration = None
    dice = None
    changes: list[str] = []
    event = "travel"

    if loc.get("adventure"):
        adv = worldpacks.get_adventure(pack, loc["adventure"])
        if not adv:
            raise ValueError("adventure pack data missing")
        state["adventure_id"] = adv["id"]
        resume = (
            state.get("beat") in adv.get("scenes", {})
            and not state.get("adventure_done")
        )
        if resume:
            scene = adv["scenes"][state["beat"]]
            narration = f"The door remembers you. {scene.get('intro', '')}"
            event = "adventure_resume"
        else:
            state["beat"] = adv.get("entry")
            state["adventure_done"] = False
            scene = adv["scenes"].get(adv["entry"], {})
            narration = _trim(scene.get("intro", ""), 1200) or adv.get("title", "")
            event = "adventure_enter"
            for eff in adv.get("on_enter", []):
                changes += _effects_for(cid, pack, eff)
        db.execute(
            "UPDATE campaigns SET location_id=?, scene_id=?, state_json=?, updated_at=? WHERE id=?",
            (location_id, state["beat"], jdumps(state), utcnow(), cid),
        )
    else:
        db.execute(
            "UPDATE campaigns SET location_id=?, scene_id='hub', updated_at=? WHERE id=?",
            (location_id, utcnow(), cid),
        )
        narration = _trim(loc.get("desc", ""), 800)
        if ai.get_ai_config().get("enabled"):
            bridge = _gm_scene_bridge(cid, pack, campaign,
                                      {"label": f"traveled to {loc['name']}"}, loc)
            if bridge:
                narration = bridge
        for eff in loc.get("on_enter", []):
            changes += _effects_for(cid, pack, eff)

    db.add_transcript(cid, "player", f"[traveled] {loc['name']}")
    db.add_transcript(cid, "gm", narration, {"location_id": location_id, "event": event})
    db.add_journal(cid, f"{loc.get('name', location_id)}: {_trim(narration, 200)}", "travel")
    db.log_event(cid, event, {"location_id": location_id})
    advance_time(campaign, 1)
    return {"narration": narration, "changes": changes, "location": location_id,
            "tide": tide, "meta": {"ai_used": loc.get("adventure") is None}}


def rest(cid: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    loc = worldpacks.get_location(pack, campaign["location_id"]) or {}
    rest_spec = loc.get("rest")
    if not rest_spec:
        raise ValueError("This is no place to rest.")
    ch = get_character(cid)
    dv = min(int(rest_spec.get("vigor", 2)), ch["vigor_max"] - ch["vigor"])
    dn = min(int(rest_spec.get("nerve", 2)), ch["nerve_max"] - ch["nerve"])
    ch["vigor"] += max(0, dv)
    ch["nerve"] += max(0, dn)
    _persist_character(ch)
    advance_time(campaign, 2)
    msg = loc.get("rest_text", "You rest, and the shore allows it.")
    db.add_journal(cid, f"Rested at {loc['name']}.", "rest")
    db.log_event(cid, "rest", {"vigor": dv, "nerve": dn})
    return {"narration": msg, "healed": {"vigor": dv, "nerve": dn}}


def use_item(cid: str, item_id: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    item = worldpacks.get_item(pack, item_id)
    if not item:
        raise ValueError("unknown item")
    row = db.query_one(
        "SELECT id FROM inventory WHERE campaign_id=? AND item_id=?", (cid, item_id)
    )
    if not row:
        raise ValueError("You don't have that.")
    effects = item.get("use") or {}
    if not effects:
        return {"narration": item.get("desc", "It does nothing — yet."), "changes": []}
    changes: list[str] = []
    apply_effects(cid, pack, effects, changes)
    if effects.get("consume"):
        take_item(cid, pack, item_id, 1)
        changes.append(f"Used up: {item['name']}.")
    narration = effects.get("text", f"You put the {item['name']} to use.")
    db.add_transcript(cid, "player", f"[used item] {item['name']}")
    db.add_transcript(cid, "gm", narration, {"item": item_id, "changes": changes})
    return {"narration": narration, "changes": changes}


# ==========================================================================
# Views / export
# ==========================================================================

def campaign_view(cid: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    state = jloads(campaign["state_json"], {})
    ch = get_character(cid)
    loc = worldpacks.get_location(pack, campaign["location_id"]) or {}
    adv = worldpacks.get_adventure(pack, state.get("adventure_id") or "") if state.get("adventure_id") else None
    beat_active = bool(
        state.get("beat") and loc.get("adventure") and loc["adventure"] == state.get("adventure_id")
    )
    scene = adv["scenes"].get(state["beat"]) if adv and beat_active else None

    doors = []
    for portal in pack.get("portals", []):
        doors.append({
            "id": portal["id"],
            "label": portal.get("label", portal["id"]),
            "target_location": portal.get("target_location"),
            "sealed": portal.get("sealed", False),
            "seal_note": portal.get("seal_note", ""),
        })

    journal_rows = db.query(
        "SELECT id, ts, kind, text FROM journal WHERE campaign_id=? ORDER BY rowid DESC LIMIT 40",
        (cid,),
    )
    quests = _quests_for(cid)
    dice_rows = db.query(
        "SELECT ts, skill, dice_json, total, outcome, note FROM dicelog"
        " WHERE campaign_id=? ORDER BY rowid DESC LIMIT 12",
        (cid,),
    )
    facts = _visible_facts(cid, 15)
    npcs_rows = db.query(
        "SELECT npc_id, name, data_json FROM npcs WHERE campaign_id=?", (cid,)
    )
    loc_state = {
        r["location_id"]: bool(r["discovered"])
        for r in db.query(
            "SELECT location_id, discovered FROM locations_state WHERE campaign_id=?", (cid,)
        )
    }
    for l in pack.get("locations", []):
        if l.get("known", False):
            loc_state.setdefault(l["id"], True)

    cfg = ai.get_ai_config()
    return {
        "id": cid,
        "name": campaign["name"],
        "pack": {
            "id": pack["id"], "name": pack["name"], "theme": pack.get("theme", {}),
            "locations": [
                {"id": l["id"], "name": l["name"], "short": l.get("short", "")}
                for l in pack.get("locations", [])
            ],
        },
        "character": ch,
        "location": loc,
        "scene": {
            "adventure_id": state.get("adventure_id") if beat_active else None,
            "beat": state.get("beat") if beat_active else None,
            "title": (scene or {}).get("title"),
            "brief": (scene or {}).get("brief"),
            "choices": [
                {
                    "id": c["id"],
                    "label": c.get("label", c["id"]),
                    "hint": c.get("hint", ""),
                    "check": c.get("check"),
                    "available": _choice_available(c, cid, state)[0],
                    "locked_hint": _choice_available(c, cid, state)[1],
                }
                for c in ((scene or {}).get("choices", []))
            ],
            "hotspots": (scene or {}).get("hotspots") or loc.get("hotspots", []),
            "adventure_done": bool(state.get("adventure_done")),
        } if (adv or loc) else None,
        "tide": tide_for(campaign["drift"]),
        "weather": state.get("weather", {"key": "mist", "desc": "Sea mist."}),
        "turn": campaign["turn"],
        "drift": campaign["drift"],
        "inventory": get_inventory(cid),
        "journal": [dict(r) for r in reversed(journal_rows)],
        "quests": quests,
        "facts": facts,
        "dice_log": [
            {**dict(r), "dice": jloads(r["dice_json"], [])} for r in reversed(dice_rows)
        ],
        "omen": state.get("last_omen"),
        "npcs": [
            {"npc_id": r["npc_id"], "name": r["name"], **jloads(r["data_json"], {})}
            for r in npcs_rows
        ],
        "discovered": loc_state,
        "portals": doors,
        "ai": {"enabled": bool(cfg.get("enabled")), "model": cfg.get("model", ""),
               "base_url": cfg.get("base_url", "")},
        "endings_seen": state.get("endings_seen", []),
        "summary": campaign["summary"],
    }


def export_campaign(cid: str) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    tables = {
        "campaigns": "id=?", "characters": "campaign_id=?", "inventory": "campaign_id=?",
        "journal": "campaign_id=?", "quests": "campaign_id=?", "npcs": "campaign_id=?",
        "facts": "campaign_id=?", "transcript": "campaign_id=?", "dicelog": "campaign_id=?",
        "locations_state": "campaign_id=?", "decks": "campaign_id=?", "events": "campaign_id=?",
    }
    out = {"schema": config.SCHEMA_VERSION, "exported_at": utcnow(), "tables": {}}
    for table, col in tables.items():
        rows = db.query(f"SELECT * FROM {table} WHERE {col}", (cid,))
        out["tables"][table] = [dict(r) for r in rows]
    db.log_event(cid, "export", {})
    return out


def import_campaign(data: dict) -> str:
    if not isinstance(data, dict) or "tables" not in data:
        raise ValueError("not a Saturday Multiverse export")
    tables = data["tables"]
    camp_rows = tables.get("campaigns", [])
    if not camp_rows:
        raise ValueError("export contains no campaign")
    old = camp_rows[0]
    cid = new_id("cmp")
    ts = utcnow()
    db.execute(
        "INSERT INTO campaigns (id, name, pack_id, character_id, scene_id, location_id, turn,"
        " drift, state_json, summary, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,'active',?,?)",
        (cid, f"{old['name']} (imported)", old["pack_id"], None, old.get("scene_id"),
         old.get("location_id"), old.get("turn", 0), old.get("drift", 0),
         old.get("state_json", "{}"), old.get("summary", ""), ts, ts),
    )
    mapping = {
        "characters": ("id, campaign_id, name, archetype, portrait_json, attributes_json,"
                       " skills_json, vigor, vigor_max, nerve, nerve_max, data_json",
                       ["id", "name", "archetype", "portrait_json", "attributes_json",
                        "skills_json", "vigor", "vigor_max", "nerve", "nerve_max", "data_json"]),
    }
    ch_rows = tables.get("characters", [])
    if ch_rows:
        c = ch_rows[0]
        cols, keys = mapping["characters"]
        vals = [new_id("chr"), cid] + [c.get(k) for k in keys[1:]]
        db.execute(f"INSERT INTO characters ({cols}) VALUES ({','.join('?' * len(vals))})", tuple(vals))
        db.execute("UPDATE campaigns SET character_id=? WHERE id=?",
                   (vals[0], cid))
    for table, cols in [
        ("inventory", "id, campaign_id, item_id, name, kind, qty, equipped, data_json"),
        ("journal", "id, campaign_id, ts, kind, text"),
        ("quests", "id, campaign_id, quest_id, title, status, notes_json"),
        ("npcs", "id, campaign_id, npc_id, name, data_json"),
        ("facts", "id, campaign_id, ts, text, scope, importance, source"),
        ("dicelog", "id, campaign_id, ts, kind, skill, stat_mod, dice_json, total, difficulty, outcome, effect, note"),
        ("locations_state", "campaign_id, location_id, discovered, data_json"),
        ("decks", "campaign_id, deck_id, draw_json, discard_json, held_json, draws"),
    ]:
        for r in tables.get(table, []):
            r = dict(r)
            r["campaign_id"] = cid
            r.pop("id", None) if table not in ("locations_state", "decks") else None
            keys = cols.replace(" ", "").split(",")
            vals = [r.get(k) for k in keys if k != "id"]
            collist = ",".join(k for k in keys if k != "id")
            try:
                db.execute(
                    f"INSERT INTO {table} ({collist}) VALUES ({','.join('?' * len(vals))})",
                    tuple(vals),
                )
            except Exception:  # noqa: BLE001 - tolerate partial/dirty imports
                continue
    db.log_event(cid, "import", {"from": old["id"]})
    return cid
