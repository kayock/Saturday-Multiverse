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

from . import ai, config, continuity, db, director, gen, legacy, library, routing, rules, rules_dnd, worldpacks
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
    ruleset = str(character_spec.get("ruleset", "undertow")).lower()
    if ruleset not in ("undertow", "dnd5e"):
        ruleset = "undertow"
    dnd_sheet = None
    if ruleset == "dnd5e":
        dnd_sheet = rules_dnd.build_character({
            "class": character_spec.get("class", "fighter"),
            "species": character_spec.get("species", "human"),
            "background": character_spec.get("background", "folk_hero"),
        })
        archetype_id = dnd_sheet["class"]
        arc = {"name": dnd_sheet["class_name"], "stats": {}, "palette": "tide",
               "kit": [], "dnd": True}
    else:
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
    if ruleset == "dnd5e":
        vigor_max = dnd_sheet["hp_max"]
        nerve_max = 0
        attrs = {k: dnd_sheet["ability_mods"][k] for k in ("wits", "might", "mettle", "bind")} \
            if False else {"wits": dnd_sheet["ability_mods"]["int"],
                           "might": dnd_sheet["ability_mods"]["str"],
                           "mettle": dnd_sheet["ability_mods"]["wis"],
                           "bind": dnd_sheet["ability_mods"]["cha"]}
        skills = {}
    else:
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
            jdumps({"specialty": specialty, "history": character_spec.get("history", "")[:400],
                    "dnd": dnd_sheet} if dnd_sheet else
                   {"specialty": specialty, "history": character_spec.get("history", "")[:400]}),
        ),
    )
    hub = pack.get("hub_location") or (pack["locations"][0]["id"] if pack["locations"] else "")
    hub_loc = worldpacks.get_location(pack, hub) or {}
    start_adv = hub_loc.get("adventure")
    state = {
        "flags": {},
        "adventure_id": start_adv or None,
        "beat": None,
        "deck_mode": "agent",
        "last_omen": None,
        "omen_bonus": None,
        "weather": {"key": "mist", "desc": "Low sea mist."},
        "endings_seen": [],
    }
    _bind_source(cid, state, pack)
    if start_adv:
        adv0 = worldpacks.get_adventure(pack, start_adv)
        if adv0 and adv0.get("entry"):
            state["beat"] = adv0["entry"]
    db.execute(
        "INSERT INTO campaigns (id, name, pack_id, character_id, scene_id, location_id,"
        " turn, drift, ruleset, state_json, summary, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?, ?,0,0,?, ?, '', 'active', ?, ?)",
        (cid, name, pack_id, chid, "hub", hub, ruleset, jdumps(state), ts, ts),
    )
    for item_id in arc.get("kit", []) if not dnd_sheet else []:
        give_item(cid, pack, item_id, silent=True, chid=chid)
    for fact in pack.get("intro_facts", []):
        db.execute(
            "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (new_id("fct"), cid, ts, fact[:300], "visible", 2, "pack"),
        )
    for secret in pack.get("gm_secrets", []):
        db.execute(
            "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (new_id("fct"), cid, ts, secret[:300], "hidden", 3, "pack"),
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
    mid = legacy.remember(cid, "tavern", "visitor", f"A newcomer named {char_name} arrived on the shore.")
    try:
        from . import experience as _exp
        _owner = db.query_one(
            "SELECT character_id FROM campaigns WHERE id=?", (cid,))["character_id"]
        _exp.note_heard(cid, _owner, "tavern")
        # hotfix 4: the character learns their own arrival tale — a specific,
        # authoritative acquisition (they may retell exactly this at the fire)
        if mid:
            _exp.note_memory(cid, _owner, mid)
    except Exception:
        pass
    echo_ids = character_spec.get("echo_ids") or []
    if echo_ids:
        for c in legacy.weave_echoes(cid, pack, echo_ids):
            db.add_journal(cid, c, "echo")
            db.add_transcript(cid, "system", c)
    return cid


def create_character(cid: str, spec: dict) -> str:
    """Create an additional wanderer in an EXISTING campaign (multiplayer
    joins). Same validation and kits as campaign creation."""
    pack = worldpacks.load_pack(spec.get("pack_id") or get_campaign(cid)["pack_id"])
    if not pack:
        raise ValueError(f"unknown world pack")
    char_name = (spec.get("name") or "").strip()[:40]
    if not char_name:
        raise ValueError("the wanderer needs a name")
    ruleset = _campaign_ruleset(cid)
    dnd_sheet = None
    if ruleset == "dnd5e":
        dnd_sheet = rules_dnd.build_character({
            "class": spec.get("class", "fighter"),
            "species": spec.get("species", "human"),
            "background": spec.get("background", "folk_hero"),
        })
        archetype_id = dnd_sheet["class"]
        arc = {"name": dnd_sheet["class_name"], "stats": {}, "palette": "tide",
               "kit": [], "dnd": True}
        attrs = {"wits": dnd_sheet["ability_mods"]["int"],
                 "might": dnd_sheet["ability_mods"]["str"],
                 "mettle": dnd_sheet["ability_mods"]["wis"],
                 "bind": dnd_sheet["ability_mods"]["cha"]}
        skills = {}
        vigor_max = dnd_sheet["hp_max"]
        nerve_max = 0
    else:
        arc = worldpacks.get_archetype(pack, spec.get("archetype", ""))
        if not arc:
            raise ValueError("pick a road: one of the pack's archetypes")
        archetype_id = spec.get("archetype")
        attrs = dict(arc.get("stats", {}))
        extra = spec.get("extra_stat") or {}
        if extra:
            stat = str(extra.get("stat", "")).lower()
            if stat not in STATS:
                raise ValueError("extra point must go to wits, might, mettle or bind")
            attrs[stat] = attrs.get(stat, 0) + 1
        skills = {s: (1 if s == spec.get("specialty") else 0) for s in VALID_SKILLS}
        if spec.get("specialty") not in VALID_SKILLS:
            raise ValueError(f"specialty must be one of {VALID_SKILLS}")
        vigor_max = 10 + attrs.get("might", 0)
        nerve_max = 10 + attrs.get("mettle", 0)
    chid = new_id("chr")
    ts = utcnow()
    portrait = {
        "seed": spec.get("portrait_seed") or new_id("seed"),
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
            jdumps({"specialty": spec.get("specialty"),
                    "history": (spec.get("history") or "")[:400],
                    "dnd": dnd_sheet} if dnd_sheet else
                   {"specialty": spec.get("specialty"),
                    "history": (spec.get("history") or "")[:400]}),
        ),
    )
    for item_id in arc.get("kit", []) if not dnd_sheet else []:
        give_item(cid, pack, item_id, silent=True, chid=chid)
    db.add_transcript(cid, "system", f"{char_name} steps out of the sea-foam.")
    mid = legacy.remember(cid, "tavern", "visitor", f"A newcomer named {char_name} arrived on the shore.")
    try:
        from . import experience as _exp
        # hotfix 4: the joining character learns their own arrival tale
        if mid:
            _exp.note_memory(cid, chid, mid)
    except Exception:
        pass
    echo_ids = spec.get("echo_ids") or []
    if echo_ids:
        for c in legacy.weave_echoes(cid, pack, echo_ids):
            db.add_journal(cid, c, "echo")
            db.add_transcript(cid, "system", c)
    db.log_event(cid, "character_joined", {"character_id": chid, "name": char_name})
    return chid


def get_campaign(cid: str) -> dict | None:
    row = db.query_one("SELECT * FROM campaigns WHERE id=? AND status='active'", (cid,))
    return dict(row) if row else None


def list_characters(cid: str) -> list[dict]:
    """Every wanderer in the campaign, in join order (party play), each with
    its parsed engine data like get_character()."""
    out = []
    for row in db.query("SELECT * FROM characters WHERE campaign_id=? ORDER BY rowid", (cid,)):
        ch = dict(row)
        ch["data"] = jloads(ch.get("data_json") or "{}", {})
        out.append(ch)
    return out


def get_character(cid: str, chid: str | None = None) -> dict | None:
    """Resolve a character. With chid: that character. Without: the campaign's
    first wanderer (solo play / legacy saves)."""
    if chid:
        row = db.query_one(
            "SELECT * FROM characters WHERE campaign_id=? AND id=?", (cid, chid)
        )
    else:
        row = db.query_one("SELECT * FROM characters WHERE campaign_id=?", (cid,))
    if not row:
        return None
    ch = dict(row)
    ch["attributes"] = jloads(ch.pop("attributes_json"), {})
    ch["skills"] = jloads(ch.pop("skills_json"), {})
    ch["portrait"] = jloads(ch.pop("portrait_json"), {})
    ch["data"] = jloads(ch.pop("data_json"), {})
    return ch


def ch_get(ch: dict, key: str, default=None):
    """Per-character engine state (beads, death, pending rolls, omen bonus)."""
    if not ch:
        return default
    return ch.get("data", {}).get(key, default)


def ch_set(ch: dict, key: str, value) -> None:
    if not ch:
        return
    ch.setdefault("data", {})[key] = value
    _persist_character(ch)


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

def _world_item(cid: str, item_id: str) -> dict | None:
    """Generated worlds carry their own (engine-created) item catalogs."""
    for r in db.query("SELECT identity_json FROM worlds WHERE campaign_id=?", (cid,)):
        for item in jloads(r["identity_json"], {}).get("items", []):
            if item.get("id") == item_id:
                return item
    return None


def give_item(cid: str, pack: dict, item_id: str, qty: int = 1, silent: bool = False,
              chid: str | None = None) -> dict | None:
    item = worldpacks.get_item(pack, item_id) or _world_item(cid, item_id)
    if not item:
        return None
    qty = max(1, min(9, int(qty)))
    owner = chid or (get_character(cid) or {}).get("id")
    row = db.query_one(
        "SELECT id, qty FROM inventory WHERE campaign_id=? AND item_id=? AND character_id=?",
        (cid, item_id, owner),
    )
    if row:
        db.execute("UPDATE inventory SET qty=? WHERE id=?", (min(9, row["qty"] + qty), row["id"]))
    else:
        db.execute(
            "INSERT INTO inventory (id, campaign_id, character_id, item_id, name, kind, qty, equipped, data_json)"
            " VALUES (?,?,?,?,?,?,1,0,?)",
            (new_id("itm"), cid, owner, item_id, item["name"], item.get("kind", "trinket"), jdumps(item)),
        )
    if not silent:
        db.log_event(cid, "item_give", {"item_id": item_id, "qty": qty, "character_id": owner})
    return {"item_id": item_id, "name": item["name"], "qty": qty}


def take_item(cid: str, pack: dict, item_id: str, qty: int = 1,
              chid: str | None = None) -> dict | None:
    owner = chid or (get_character(cid) or {}).get("id")
    row = db.query_one(
        "SELECT id, name, qty FROM inventory WHERE campaign_id=? AND item_id=? AND character_id=?",
        (cid, item_id, owner),
    )
    if not row:
        return None
    item = worldpacks.get_item(pack, item_id) or {"name": row["name"]}
    qty = max(1, min(row["qty"], int(qty)))
    if row["qty"] - qty <= 0:
        db.execute("DELETE FROM inventory WHERE id=?", (row["id"],))
    else:
        db.execute("UPDATE inventory SET qty=? WHERE id=?", (row["qty"] - qty, row["id"]))
    db.log_event(cid, "item_take", {"item_id": item_id, "qty": qty, "character_id": owner})
    return {"item_id": item_id, "name": item["name"], "qty": qty}


def get_inventory(cid: str, chid: str | None = None) -> list[dict]:
    """A character's pack. Rows with a NULL owner (very old saves) stay
    visible to everyone until they are first touched."""
    if chid:
        rows = db.query(
            "SELECT id, character_id, item_id, name, kind, qty, data_json FROM inventory"
            " WHERE campaign_id=? AND (character_id=? OR character_id IS NULL) ORDER BY kind, name",
            (cid, chid),
        )
    else:
        rows = db.query(
            "SELECT id, character_id, item_id, name, kind, qty, data_json FROM inventory"
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

def apply_effects(cid: str, pack: dict, effects: dict, changes: list[str],
                  chid: str | None = None) -> dict:
    """Apply a validated effects dict; append human-readable change lines."""
    ch = get_character(cid, chid)
    # idempotent retries: an effect declaring once:true and naming its flag is
    # skipped when the flag is already set — a retried request never
    # double-grants rewards or double-applies world changes
    once_flag = effects.get("flag")
    if effects.get("once") and once_flag:
        st0 = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
        if once_flag in st0.get("flags", []):
            return changes

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
    enc = effects.get("dnd_encounter")
    if enc and isinstance(enc, dict) and _campaign_ruleset(cid) == "dnd5e":
        # persistent, player-controlled combat: the encounter starts here and
        # advances turn by turn; the engine resolves every outcome
        from . import combat as _combat
        try:
            camp_row = db.query_one("SELECT location_id FROM campaigns WHERE id=?", (cid,))
            started = _combat.start(cid, enc.get("monster", "goblin"),
                                    enc.get("count", 1),
                                    location=camp_row["location_id"] if camp_row else None)
            state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?",
                                        (cid,))["state_json"], {})
            state["encounter_id"] = started["encounter_id"]
            db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
                       (jdumps(state), utcnow(), cid))
            changes.append(started["log"][0] if started.get("log")
                           else "Combat begins — the dice are yours.")
        except _combat.CombatError as exc:
            changes.append(f"(The {enc.get('monster', 'creature')} slinks back into the dark: {exc})")

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
        try:
            from . import experience as _exp
            _exp.auto_credit(cid, "discovery", f"discovered {loc_id}")
            _exp.note_visit(cid, chid, loc_id)
            _exp.note_discovery(cid, chid, loc_id)
        except Exception:
            pass
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
        try:
            from . import experience as _exp
            for _row in db.query("SELECT id FROM characters WHERE campaign_id=?", (cid,)):
                _exp.note_visit(cid, _row["id"], hub)
        except Exception:
            pass
        changes.append("Returned to the Living Shore.")
    beads = effects.get("beads")
    if isinstance(beads, int) and beads != 0:
        if ch:
            purse = int(ch_get(ch, "beads", 0)) + beads
            ch_set(ch, "beads", max(0, purse))
            changes.append(f"Glassbeads {'+' if beads > 0 else '−'}{abs(beads)} (now {max(0, purse)}).")
    cl = effects.get("clue")
    if isinstance(cl, dict) and cl.get("thread_id"):
        res = legacy.add_clue(cid, str(cl["thread_id"])[:60], str(cl.get("text", ""))[:300], "choice")
        if res:
            changes.append(f"Thread payoff: {res['thread']}.")
            changes.append(res["narration"])
        else:
            changes.append("A clue settles into place.")
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
        if status == "done":
            try:
                from . import experience as _exp
                _exp.auto_credit(cid, "quest_resolved", f"quest {qid} resolved")
            except Exception:
                pass
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

UNDERTOW_TO_DND = {
    "notice": "perception", "lore": "history", "persuade": "persuasion",
    "fight": "athletics", "endure": "athletics", "bind": "arcana",
}


def _source_doc_for(pack: dict):
    """Match the indexed library document this pack adapts, by title/author
    (never by a fixed doc id — reindexing keeps links intact)."""
    lic = pack.get("license", {}) or {}
    title = (lic.get("source_title") or "").strip()
    author = (lic.get("author") or "").strip()
    if not title and not author:
        return None
    best, score = None, 0
    for d in library.list_docs():
        s = 0
        if title and title.lower()[:40] in (d["title"] or "").lower():
            s += 2
        if author and author.lower()[:30] in (d["author"] or "").lower():
            s += 2
        if s > score:
            best, score = d, s
    return best if best and score >= 2 else None


def _initial_horizon(doc_id: str) -> tuple[int, int]:
    """Where the story's revealed window begins: the first 15% of the book,
    clamped to a chapter boundary so the opening chapters are present."""
    row = db.query_one("SELECT MAX(seq) AS m FROM library_chunks WHERE doc_id=?", (doc_id,))
    total = int(row["m"] or 0) + 1
    target = max(0, min(total - 1, int(total * 0.15)))
    row2 = db.query_one(
        "SELECT MAX(seq) AS s FROM (SELECT seq, heading, LAG(heading) OVER (ORDER BY seq)"
        " ph FROM library_chunks WHERE doc_id=?) WHERE ph IS NOT NULL AND heading != ph"
        " AND seq <= ?", (doc_id, target))
    boundary = int(row2["s"]) if row2 and row2["s"] is not None else target
    return boundary, total


def _bind_source(cid: str, state: dict, pack: dict) -> None:
    """Bind a source-linked pack to its indexed document and open the story's
    revealed window. Later chapters stay unretrievable until discoveries and
    scene progress legitimately advance the horizon."""
    if state.get("source_doc_id"):
        return  # already bound
    doc = _source_doc_for(pack)
    if not doc:
        return
    boundary, total = _initial_horizon(doc["id"])
    state["source_doc_id"] = doc["id"]
    state["source_total"] = total
    state["source_horizon"] = boundary
    db.log_event(cid, "source_bound", {"doc_id": doc["id"], "horizon": boundary,
                                       "total": total})


def _advance_horizon(cid: str, state: dict, frac: float, reason: str) -> None:
    """Advance the revealed window (engine-defined mechanic: scene progress
    and discoveries legitimately reveal more of the book)."""
    total = int(state.get("source_total") or 0)
    horizon = int(state.get("source_horizon") or 0)
    if not total:
        return
    new_h = min(total - 1, max(horizon, int(horizon + total * frac)))
    if new_h > horizon:
        state["source_horizon"] = new_h
        db.log_event(cid, "horizon_advance", {"reason": reason, "horizon": new_h,
                                              "total": total})


def _effective_location(cid: str, ch: dict | None, campaign: dict | None = None) -> str:
    """Split-party aware location: a character's override, else the party focus."""
    if ch:
        row = db.query_one("SELECT location_id FROM characters WHERE id=?", (ch["id"],))
        if row and row["location_id"]:
            return row["location_id"]
    if campaign:
        return campaign["location_id"]
    row = db.query_one("SELECT location_id FROM campaigns WHERE id=?", (cid,))
    return row["location_id"] if row else None


def _campaign_ruleset(cid: str) -> str:
    row = db.query_one("SELECT ruleset FROM campaigns WHERE id=?", (cid,))
    return (row["ruleset"] if row else "undertow") or "undertow"


def _dnd_sheet(ch: dict) -> dict | None:
    sheet = ch_get(ch, "dnd")
    return sheet if isinstance(sheet, dict) else None


def _dnd_roll(cid: str, ch: dict, skill: str, hard: bool = False, risk: bool = False,
              reason: str = "", sit_mod: int = 0) -> dict:
    """A d20 check under the SRD ruleset, reported in the shared five-band
    vocabulary so pack choices work identically for both systems."""
    sheet = _dnd_sheet(ch)
    if not sheet:
        raise ValueError("this character has no D&D sheet")
    mapped = UNDERTOW_TO_DND.get(skill, skill if skill in rules_dnd.SKILL_ABILITY else "perception")
    roll = rules_dnd.check(sheet, mapped, dc=13, hard=hard, risk=risk, sit_mod=sit_mod)
    db.execute(
        "INSERT INTO dicelog (id, campaign_id, ts, kind, skill, stat_mod, dice_json, total,"
        " difficulty, outcome, effect, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("dce"), cid, utcnow(), "d20", mapped, roll["mod"], jdumps(roll["dice"]),
         roll["total"], roll["dc"], roll["outcome"], 0, (reason or "")[:120]),
    )
    db.log_event(cid, "dice_roll", {"skill": mapped, "dice": roll["dice"], "total": roll["total"],
                                    "outcome": roll["outcome"], "reason": reason[:120],
                                    "ruleset": "dnd5e", "risk": bool(risk)})
    _persist_character(ch)
    return roll


def _mods_for(ch: dict, skill: str) -> tuple[int, str]:
    stat = rules.skill_to_stat(skill)
    stat_mod = int(ch["attributes"].get(stat, 0))
    skill_mod = int(ch["skills"].get(skill, 0))
    return stat_mod + skill_mod, stat


def _check_death(cid: str, ch: dict) -> bool:
    """Both lamps out: the wanderer's story concludes, and the multiverse
    keeps an echo of them."""
    if not ch or ch["vigor"] > 0 or ch["nerve"] > 0:
        return False
    if ch_get(ch, "dead"):
        return False
    ch_set(ch, "dead", True)
    legacy.create_echo(
        cid, "achievement", "Remembrance",
        f"{ch['name']} walked the shore and did not come back. The tavern pours one out.",
        {"trait_skill": "endure", "trait_delta": 1},
    )
    db.log_event(cid, "character_fell", {"name": ch["name"], "character_id": ch["id"]})
    legacy.remember(cid, "tavern", "event", f"{ch['name']} was lost to the tide. Nobody says how.")
    return True


def _roll_and_log(cid: str, ch: dict, skill: str, shift: int = 0, sit_mod: int = 0,
                  harm_type: str = "", reason: str = "", risk: bool = False,
                  pending: bool = True) -> dict:
    mod, stat = _mods_for(ch, skill)
    result = rules.roll_check(stat_mod=mod, sit_mod=sit_mod, shift=shift, risk=risk)
    outcome = result.outcome
    harm = rules.harm_for(outcome, risk)
    if harm and ch:
        htype = harm_type or ("vigor" if skill in ("fight", "endure") else "nerve")
        rules.apply_harm(ch, harm, htype)
        _persist_character(ch)
    db.execute(
        "INSERT INTO dicelog (id, campaign_id, ts, kind, skill, stat_mod, dice_json, total,"
        " difficulty, outcome, effect, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("dce"), cid, utcnow(), "check", skill, mod, jdumps(result.dice),
         result.total, 7 + shift, outcome, harm,
         (reason or "")[:120]),
    )
    db.log_event(cid, "dice_roll", {"skill": skill, "dice": result.dice, "total": result.total,
                                    "outcome": outcome, "reason": reason[:120], "risk": risk})
    roll = {
        "dice": result.dice,
        "mod": mod,
        "sit_mod": result.sit_mod,
        "total": result.total,
        "outcome": outcome,
        "text": result.text,
        "harm": harm,
        "harm_type": harm_type or ("vigor" if skill in ("fight", "endure") else "nerve"),
        "note": reason,
        "risk": risk,
    }
    if pending:
        # open the tactical window (Push / Resist) for engine-rolled checks
        legacy._set_pending_roll(cid, ch["id"], roll, skill, reason or "check")
        _check_death(cid, ch)
    return roll


def manual_check(cid: str, skill: str, hard: bool = False, risk: bool = False,
                 chid: str | None = None) -> dict:
    ch = get_character(cid, chid)
    if not ch:
        raise ValueError("no character")
    if skill not in VALID_SKILLS:
        raise ValueError(f"skill must be one of {VALID_SKILLS}")
    if ch_get(ch, "dead"):
        raise ValueError("This wanderer's story is concluded — begin a new voyage; the multiverse remembers.")
    if _campaign_ruleset(cid) == "dnd5e":
        return _dnd_roll(cid, ch, skill, hard=hard, risk=risk, reason="manual roll")
    shift = -1 if hard else 0
    sit = _consume_omen(ch, skill)
    roll = _roll_and_log(cid, ch, skill, shift=shift, sit_mod=sit, reason="manual roll", risk=risk)
    return roll


def _consume_omen(ch: dict, skill: str) -> int:
    """Consume a pending omen bonus/penalty that applies to this skill."""
    pending = ch_get(ch, "omen_bonus")
    if not isinstance(pending, dict):
        return 0
    if pending.get("skill") in (None, skill) or pending.get("skill") == "any":
        ch_set(ch, "omen_bonus", None)
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
    style = legacy.normalize_style(state)
    world_ctx = ""
    world_items = ""
    if str(campaign["location_id"]).startswith("w"):
        world = legacy.find_world_by_location(campaign["id"], campaign["location_id"])
        if world:
            ident = world["identity"]
            world_ctx = (
                f"\nCURRENT WORLD: {ident['name']} ({ident['archetype_label']}) — reached through an unstable door.\n"
                f"WORLD ATMOSPHERE: {ident['weather']}\n"
                f"WORLD TRUTHS: {' | '.join(ident.get('properties', []))}\n"
                f"VISITS: {world['visits']}. WORLD RECORD: {world['state'].get('flags', [])}\n"
            )
            world_items = "; ".join(f"{i['id']} ({i['name']})" for i in ident.get("items", []))
    cons = legacy.recent_consequences(campaign["id"], 3)
    cons_line = ""
    if cons:
        cons_line = ("\nCROSS-WORLD ECHOES (already true; reference naturally, never contradict):\n- "
                     + "\n- ".join(c["summary"] for c in cons))
    return f"""You are the Game Master of SATURDAY MULTIVERSE — an intimate tabletop roleplaying session for one player.

GAME MASTER PERSONA: {style['label']} — {style['prompt']}
WORLD PACK: {pack['name']} (v{pack.get('version', '1')})

LORE (the world's truth; never contradict it):
{_trim(worldpacks.lore_text(pack), 1400)}

PLAYER CHARACTER: {_trim(ch['name'], 40)}, {ch['archetype']} — stats {ch['attributes']}, skills {ch['skills']}, Vigor {ch['vigor']}/{ch['vigor_max']}, Nerve {ch['nerve']}/{ch['nerve_max']}.
TIDE: {tide}. WEATHER: {weather}. TURN: {campaign['turn'] + 1}.

ITEM CATALOG (valid item_ids): {_catalog_lines(pack)}{'; ' + world_items if world_items else ''}
NPCS (valid npc_ids): {_npc_lines(pack)}

RULES OF YOUR OFFICE:
1. Mechanics are the app's job. Never roll dice, never state outcomes of checks, never grant injuries or items in prose. If the story clearly needs an item moved, use inventory_request.
2. Never decide, say, or think anything for the player.
3. Stay inside this world pack's lore and the current world's truths. No other universes unless the records above establish them, no mention of dice, rules, models or this interface.
4. Keep horror atmospheric — dread and strangeness, not torture-porn. Nothing sexual. This is a game for adults but a kind one.
5. Hidden story information stays hidden (see memory.hidden_note).
6. The tide and weather above are facts; the shore's mood follows them.{cons_line}

{GM_JSON_CONTRACT.replace('NARRATION_WORDS', str(narration_words))}"""


def build_user_prompt(campaign: dict, pack: dict, ch: dict, state: dict, action: str) -> str:
    loc = _resolve_location(cid=campaign["id"], pack=pack, location_id=campaign["location_id"])[0] or {}
    beat = state.get("beat")
    scene = _resolve_adventure(cid=campaign["id"], pack=pack, adv_id=state.get("adventure_id") or "") or {}
    scene = (scene.get("scenes") or {}).get(beat) if beat else None
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

def run_turn(cid: str, action_text: str, chid: str | None = None) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    ch = get_character(cid, chid)
    if not ch:
        raise ValueError("campaign has no character")
    pack = worldpacks.load_pack(campaign["pack_id"])
    if not pack:
        raise ValueError("world pack missing")
    eff_loc = _effective_location(cid, ch, campaign)
    state0 = jloads(campaign["state_json"], {})
    beat_here = (not state0.get("beat")) or eff_loc == state0.get("beat_location", campaign["location_id"])
    if eff_loc != campaign["location_id"]:
        # a split-off character acts where they stand; the party's beat stays put
        campaign = {**campaign, "location_id": eff_loc}
    action_text = _trim(action_text, 800)
    if not action_text:
        raise ValueError("say what you do")

    state = jloads(campaign["state_json"], {})
    if ch_get(ch, "dead"):
        raise ValueError("This wanderer's story is concluded — begin a new voyage; the multiverse remembers.")
    db.execute("UPDATE campaigns SET turn=?, updated_at=? WHERE id=?",
               (campaign["turn"] + 1, utcnow(), cid))
    campaign["turn"] += 1
    advance_time(campaign, 1)
    legacy.check_washashore(cid, pack)
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    omen = None
    if beat_here and _campaign_ruleset(cid) != "dnd5e" \
            and state.get("deck_mode", "agent") == "agent" \
            and campaign["turn"] % DECK_CADENCE == 0:
        omen = _draw_omen(cid, pack, ch)

    cfg = ai.get_ai_config()
    meta = {"ai_used": False, "fallback_reason": None, "model": None, "latency_ms": None}
    contract = None
    director_note = ""
    try:
        director.observe(cid, pack)
        sugg = director.suggest(cid, pack)
        if sugg:
            director_note = ("\n\nLIVING DIRECTOR (optional pacing — ignore if the players "
                             "drive elsewhere; never force an event):\n" +
                             "\n".join(f"- {s['suggestion']}" for s in sugg[:2]))
    except Exception:
        director_note = ""
    if cfg.get("enabled"):
        user_prompt = build_user_prompt(campaign, pack, ch, state, action_text)
        user_prompt += director_note
        doc_id = pack.get("license", {}).get("library_doc_id") or pack.get("library_doc_id")
        if doc_id:
            try:
                from . import library as _library
                scene = worldpacks.get_scene(pack, state.get("adventure_id"), state.get("beat")) \
                    if hasattr(worldpacks, "get_scene") else None
                loc_row = db.query_one("SELECT location_id FROM campaigns WHERE id=?", (cid,))
                loc = worldpacks.get_location(pack, loc_row["location_id"]) if loc_row else None
                context = {
                    "action_text": action_text,
                    "scene_title": (scene or {}).get("title", ""),
                    "scene_brief": (scene or {}).get("brief", ""),
                    "location_name": (loc or {}).get("name", ""),
                    "npc_names": [n.get("name") for n in pack.get("npcs", [])
                                  if n.get("location") == (loc_row["location_id"] if loc_row else None)],
                    "quest_titles": [q.get("title") for q in pack.get("intro_quests", [])],
                    "horizon": state.get("source_horizon"),
                }
                passages = _library.retrieve_for_prompt(doc_id, context, k=4)
                if passages:
                    user_prompt += "\n\nSOURCE CONTEXT (passages retrieved from the book this world "
                    "is adapted from — stay consistent with them; never quote them verbatim; "
                    "do not reveal beyond what the party has discovered):\n"
                    user_prompt += "\n".join(f"- {p}" for p in passages)
            except Exception:
                pass  # retrieval must never break a turn
        messages = [
            {"role": "system", "content": build_system_prompt(
                pack, ch, campaign, state, int(cfg.get("narration_words", 220)))},
            *_history(cid),
            {"role": "user", "content": user_prompt},
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
            meta.update({
                "model": callmeta.get("model"),
                "latency_ms": callmeta.get("latency_ms"),
                "host": callmeta.get("host") or "",
                "tier": callmeta.get("tier") or "",
                "route_note": callmeta.get("route_note") or "",
            })
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
            if _campaign_ruleset(cid) == "dnd5e":
                dice = _dnd_roll(cid, ch, chk["skill"], hard=bool(chk.get("hard")),
                                 reason=str(chk.get("reason", ""))[:120])
            else:
                shift = -1 if chk.get("hard") else 0
                sit = _consume_omen(ch, chk["skill"])
                harm_type = chk.get("harm_type") if chk.get("harm_type") in ("vigor", "nerve") else ""
                dice = _roll_and_log(cid, ch, chk["skill"], shift=shift, sit_mod=sit,
                                     harm_type=harm_type, reason=str(chk.get("reason", ""))[:120])
            state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
            # Cinematic dice reaction: the result is authoritative; the GM
            # describes the moment (never re-decides it).
            outcome_line = _gm_outcome_narration(cid, pack, campaign, state, dice)
            if outcome_line:
                narration = f"{narration}\n\n{outcome_line}"
                meta["outcome_narrated"] = True
        # inventory request (validated against the pack catalog)
        inv_req = contract.get("inventory_request")
        if isinstance(inv_req, list):
            for req in inv_req[:2]:
                if not isinstance(req, dict):
                    continue
                item_id = str(req.get("item_id", ""))
                qty = int(req.get("qty", 1) or 1)
                if req.get("action") == "give" and worldpacks.get_item(pack, item_id):
                    if give_item(cid, pack, item_id, qty, chid=ch["id"]):
                        changes.append(f"Gained: {worldpacks.get_item(pack, item_id)['name']}.")
                elif req.get("action") == "take":
                    if take_item(cid, pack, item_id, qty, chid=ch["id"]):
                        changes.append(f"Lost: {item_id.replace('_', ' ')}.")
        # memory
        mem = contract.get("memory")
        if isinstance(mem, dict):
            for fact in (mem.get("facts") or [])[:3]:
                if isinstance(fact, str) and fact.strip():
                    f = _trim(fact, 300)
                    db.execute(
                        "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (new_id("fct"), cid, utcnow(), f, "visible", 2, "gm"),
                    )
                    # mirror into the NPC memory pool so gossip can ground it
                    legacy.remember(cid, "all", "event", f)
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
    routing.note_narration(bool(meta.get("ai_used")))

    # quick suggestions (AI only; the fallback offers none — the scene shows its own)
    choices = []
    if contract and isinstance(contract.get("choices"), list):
        choices = [_trim(str(c), 120) for c in contract["choices"][:3] if str(c).strip()]

    db.add_transcript(cid, "player", action_text)
    db.add_transcript(cid, "gm", narration, {"dice": dice, "changes": changes,
                                             "omen": omen, "scene_hint": scene_hint, **meta})
    summary = _trim(narration, 160)
    if not meta.get("ai_used"):
        summary = _trim("Offline Storyteller — " + narration, 160)
    db.execute("UPDATE campaigns SET summary=?, state_json=?, updated_at=? WHERE id=?",
               (summary, jdumps(state), utcnow(), cid))
    db.log_event(cid, "turn", {"ai_used": meta["ai_used"], "turn": campaign["turn"]})
    db.add_journal(cid, _trim(narration, 240), "auto")

    trace = _build_trace(cid, action_text, ch, dice, changes, meta, omen,
                         contract, campaign["turn"])
    return {
        "narration": narration,
        "scene_hint": scene_hint,
        "dice": dice,
        "changes": changes,
        "omen": omen,
        "choices": choices,
        "meta": meta,
        "trace": trace,
    }


def _build_trace(cid: str, action_text: str, ch: dict, dice: dict | None,
                 changes: list, meta: dict, omen: dict | None,
                 contract: dict | None, turn: int) -> dict:
    """Engine Trace — the rules behind one turn, from authoritative data only.
    Shows the action, the roll with modifiers and difficulty, the validated
    consequences, and the narration source. Never reveals GM-only knowledge
    or hidden future outcomes."""
    steps = [{"step": "action", "detail": action_text[:200]}]
    if dice:
        mods = []
        omen_note = ""
        if omen:
            omen_note = f" omen '{omen.get('title', '')}' ({omen.get('kind', '')})"
        if ch:
            bonus = ch_get(ch, "omen_bonus")
            if bonus:
                mods.append(f"omen {bonus.get('skill', 'any')} +{bonus.get('mod', 0)}")
        steps.append({
            "step": "roll",
            "rule": "2d6 + attribute (Undertow)" if "dnd" not in (ch or {}).get("data", {}) else
                    "d20 + modifier (SRD 5.1)",
            "dice": dice.get("dice", []),
            "mods": mods,
            "difficulty": dice.get("difficulty"),
            "result": dice.get("outcome"),
            "text": dice.get("text", ""),
            "omen": omen_note.strip(),
        })
    for c in changes[:8]:
        steps.append({"step": "engine_effect", "detail": c[:160]})
    steps.append({
        "step": "narration",
        "source": (("AI Game Master (" + str(meta.get("model") or "model")
                     + ((" on " + meta["host"]) if meta.get("host") else "") + ")")
                   if meta.get("ai_used") else "Offline Storyteller (built-in)"),
        "note": "narration never changes rules outcomes — the engine resolved "
                "the dice and effects above first",
    })
    return {"turn": turn, "steps": steps}


def _gm_outcome_narration(cid: str, pack: dict, campaign: dict, state: dict, dice: dict) -> str | None:
    """Cinematic dice reaction. The roll already happened; the GM describes
    the moment. With no model, the style's own outcome voice is used."""
    style = legacy.normalize_style(state)
    fallback = style["outcomes"].get(dice["outcome"]) or rules.BAND_TEXT[dice["outcome"]]
    if not ai.get_ai_config().get("enabled"):
        return fallback
    try:
        cfg = ai.get_ai_config()
        sys_p = (
            "You are the Game Master of SATURDAY MULTIVERSE. " + style["prompt"] + "\n"
            "The dice are DONE and the result below is authoritative. Describe ONLY the moment of "
            "that result, <=70 words, second person, present tense. Never contradict the result, "
            "never mention dice/numbers/mechanics, never grant items, injuries or decisions. "
            'Respond ONLY with JSON: {"narration": "..."}'
        )
        user_p = (
            f"AUTHORITATIVE RESULT — skill: {dice.get('skill')}, outcome band: {dice['outcome']}. "
            f"The band means: {rules.BAND_TEXT[dice['outcome']]} "
            f"Circumstance: {_trim(str(dice.get('note', '')), 120)}. "
            f"Narrate the moment of this outcome."
        )
        text, _ = ai.chat([{"role": "system", "content": sys_p},
                           {"role": "user", "content": user_p}], cfg)
        data = ai.extract_json(text)
        if data and isinstance(data.get("narration"), str) and len(data["narration"]) > 10:
            return _trim(data["narration"], 700)
    except ai.AiError:
        pass
    return fallback


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
    style = legacy.normalize_style(state)
    loc = _resolve_location(cid=campaign["id"], pack=pack, location_id=campaign["location_id"])[0] or {}
    scene = _resolve_adventure(cid=campaign["id"], pack=pack,
                               adv_id=state.get("adventure_id") or "")
    scene = (scene or {}).get("scenes", {}).get(state.get("beat") or "") if state.get("beat") else None
    flavor_pool = list((scene or {}).get("flavor") or loc.get("flavor")
                       or pack.get("fallback_flavor") or FALLBACK_OPENERS)
    flavor_pool += style.get("flavor", [])
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

def _draw_omen(cid: str, pack: dict, ch: dict) -> dict | None:
    """The tide draws for a specific character (deck keyed per character)."""
    cards = worldpacks.get_omens(pack)
    if not cards or not ch:
        return None
    deck_key = "omens:" + ch["id"]
    row = db.query_one("SELECT * FROM decks WHERE campaign_id=? AND deck_id=?", (cid, deck_key))
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
            " WHERE campaign_id=? AND deck_id=?",
            (jdumps(draw), jdumps(discard), jdumps(held), draws, cid, deck_key),
        )
    else:
        db.execute(
            "INSERT INTO decks (campaign_id, deck_id, draw_json, discard_json, held_json, draws)"
            " VALUES (?,?,?,?,?,?)",
            (cid, deck_key, jdumps(draw), jdumps(discard), jdumps(held), draws),
        )
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    state["last_omen"] = card
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
    if card.get("kind") == "edge" and card.get("boost"):
        ch_set(ch, "omen_bonus", {"skill": card.get("boost"), "mod": 1})
    elif card.get("kind") == "complication":
        ch_set(ch, "omen_bonus", {"skill": "any", "mod": -1})
        # the wrong gull keeps count of every complication the deck deals
        legacy.add_clue(cid, "wrong_gull",
                        f"Omen drawn: {card.get('title', '')} — a gull somewhere kept count.",
                        "omen")
    db.log_event(cid, "omen_draw", {"card_id": card.get("id"), "title": card.get("title"),
                                    "character_id": ch["id"]})
    return card


# ==========================================================================
# World-aware resolution helpers (generated worlds live in the worlds table)
# ==========================================================================

def _resolve_location(cid: str, pack: dict, location_id: str) -> tuple[dict | None, dict | None]:
    loc = worldpacks.get_location(pack, location_id)
    if loc:
        return loc, None
    world = legacy.find_world_by_location(cid, location_id)
    if world:
        for loc in world["identity"].get("locations", []):
            if loc["id"] == location_id:
                return loc, world
    return None, None


def _resolve_adventure(cid: str, pack: dict, adv_id: str) -> dict | None:
    adv = worldpacks.get_adventure(pack, adv_id)
    if adv:
        return adv
    for r in db.query("SELECT identity_json FROM worlds WHERE campaign_id=?", (cid,)):
        for a in jloads(r["identity_json"], {}).get("adventures", []):
            if a.get("id") == adv_id:
                return a
    return None


# ==========================================================================
# Scripted adventure beats
# ==========================================================================

def _choice_available(choice: dict, cid: str, state: dict,
                      chid: str | None = None) -> tuple[bool, str]:
    if choice.get("requires_flag") and choice["requires_flag"] not in state.get("flags", {}):
        return False, choice.get("locked_hint", "Something is missing.")
    if choice.get("forbid_flag") and choice["forbid_flag"] in state.get("flags", {}):
        return False, choice.get("locked_hint", "That path has closed.")
    if choice.get("requires_beads"):
        if legacy.get_beads(cid, chid) < int(choice["requires_beads"]):
            return False, choice.get("locked_hint",
                                     f"That costs {choice['requires_beads']} glassbeads, and your pockets are lighter.")
    if choice.get("requires_item"):
        row = db.query_one(
            "SELECT 1 FROM inventory WHERE campaign_id=? AND item_id=? AND (character_id=? OR character_id IS NULL)",
            (cid, choice["requires_item"], chid or ""),
        )
        if not row:
            return False, choice.get("locked_hint", "You lack what it requires.")
    return True, ""


def _effects_for(cid: str, pack: dict, effects: dict, chid: str | None = None) -> list[str]:
    changes: list[str] = []
    if effects:
        apply_effects(cid, pack, effects, changes, chid)
    return changes


def _set_beat(cid: str, state: dict, beat: str | None) -> None:
    state["beat"] = beat
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))


def choose(cid: str, choice_id: str, chid: str | None = None) -> dict:
    campaign = get_campaign(cid)
    ch0 = get_character(cid, chid)
    if ch0:
        eff0 = _effective_location(cid, ch0, campaign)
        state0 = jloads(campaign["state_json"], {})
        if state0.get("beat") and eff0 != state0.get("beat_location", campaign["location_id"]):
            raise ValueError("the story's thread is elsewhere — regroup with the party to rejoin it")
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    state = jloads(campaign["state_json"], {})
    ch = get_character(cid, chid)
    if ch and ch_get(ch, "dead"):
        raise ValueError("This wanderer's story is concluded — begin a new voyage; the multiverse remembers.")
    adv = _resolve_adventure(cid, pack, state.get("adventure_id") or "")
    if not adv or not state.get("beat"):
        raise ValueError("no active adventure scene")
    scene = adv["scenes"].get(state["beat"])
    if not scene:
        raise ValueError("scene missing from pack")
    choice = next((c for c in scene.get("choices", []) if c.get("id") == choice_id), None)
    if not choice:
        raise ValueError("unknown choice for this scene")
    ok, why = _choice_available(choice, cid, state, ch["id"] if ch else None)
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
        if _campaign_ruleset(cid) == "dnd5e":
            dice = _dnd_roll(cid, ch, skill, hard=bool(chk.get("hard")),
                             reason=choice.get("label", "")[:120])
        else:
            shift = -1 if chk.get("hard") else 0
            sit = _consume_omen(ch, skill)
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
        _advance_horizon(cid, state, 0.10, "scene progress")
    changes += _effects_for(cid, pack, branch.get("effects") or {}, ch["id"] if ch else None)

    # endings and epilogues
    ending_id = None
    epilogue = None
    offers = []
    eff = (branch.get("effects") or {})
    if eff.get("discover"):
        _advance_horizon(cid, state, 0.05, "discovery")
    if eff.get("ending"):
        ending_id = str(eff["ending"])
        ending = adv.get("endings", {}).get(ending_id, {})
        epilogue = ending.get("text", "")
        if ending_id not in state.setdefault("endings_seen", []):
            state["endings_seen"].append(ending_id)
        state["adventure_done"] = True
        state["beat"] = None
        _advance_horizon(cid, state, 1.0, "ending reached")
        ret = ending.get("return_location", pack.get("hub_location"))
        db.execute(
            "UPDATE campaigns SET location_id=?, scene_id='hub', state_json=?, updated_at=? WHERE id=?",
            (ret, jdumps(state), utcnow(), cid),
        )
        # Echo offers: this ending may seed a cross-campaign legacy.
        offers = legacy.echo_offers_for(adv, ending_id) or []
        for off in offers[:3]:
            try:
                legacy.create_echo(cid, off.get("kind", "achievement"),
                                   off.get("title", ""), off.get("detail", ""),
                                   off.get("data", {}))
            except ValueError:
                continue
        if offers:
            changes.append(f"Echo offered ({len(offers)} legacy options) — begin a new voyage to weave it in.")
        # Cross-world consequence, grounded in the recorded ending.
        if ending.get("consequence"):
            legacy.register_consequence(cid, f"ending:{adv['id']}:{ending_id}",
                                        str(ending["consequence"])[:200], {})
        # ending-level effects (rewards, clues) apply exactly once, here
        changes += _effects_for(cid, pack, ending.get("effects") or {}, ch["id"] if ch else None)
        legacy.record_event_memories(cid, "ending", "all",
                                     f"{adv.get('title', adv['id'])} ended: {ending_id}.")
        # the party remembers together (multiplayer sessions only)
        from . import mp as _mp
        _mp.record_party_moment(cid, adv.get("title", adv["id"]), ending_id,
                                [w["name"] for w in _mp.party_members(cid)])

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
            "ending": ending_id,
            "echo_offers": [{"kind": o.get("kind"), "title": o.get("title"),
                             "detail": o.get("detail")} for o in (offers or [])],
            "scene": goto, "meta": {"ai_used": bool(narration and ending_id is None and not epilogue)},
            "trace": {"turn": campaign["turn"], "steps": [
                {"step": "choice", "detail": str(choice.get("label") or choice.get("id", ""))[:160]},
                *[{"step": "engine_effect", "detail": c[:160]} for c in changes[:8]],
                {"step": "narration",
                 "source": "GM narration of an engine-resolved outcome",
                 "note": "effects above were validated by the engine before narrating"},
            ]}}


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

def travel(cid: str, location_id: str, chid: str | None = None) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    loc, world = _resolve_location(cid, pack, location_id)
    if not loc:
        raise ValueError("unknown location")
    state = jloads(campaign["state_json"], {})
    ch = get_character(cid, chid)
    if ch and ch_get(ch, "dead"):
        raise ValueError("This wanderer's story is concluded — begin a new voyage; the multiverse remembers.")

    # gating: tide
    req = loc.get("requires") or {}
    tide = tide_for(campaign["drift"])
    if req.get("tide") and req["tide"] != tide:
        raise ValueError(f"The {loc['name']} only shows itself at {req['tide']} tide (now: {tide}).")
    # gating: discovery (separate from first entry — rumors reveal a place
    # before the player ever walks into it)
    disc_row = db.query_one(
        "SELECT discovered, data_json FROM locations_state WHERE campaign_id=? AND location_id=?",
        (cid, location_id),
    )
    disc_data = jloads(disc_row["data_json"], {}) if disc_row else {}
    entered_before = bool(disc_data.get("entered"))
    discovered = bool(disc_row and disc_row["discovered"]) or loc.get("known", False)
    if req.get("discovered") and not discovered:
        raise ValueError("You haven't found the way there yet.")

    first_visit = not entered_before
    db.execute(
        "INSERT INTO locations_state (campaign_id, location_id, discovered, data_json)"
        " VALUES (?,?,1,?) ON CONFLICT(campaign_id, location_id) DO UPDATE"
        " SET discovered=1, data_json=?",
        (cid, location_id, jdumps({**disc_data, "entered": 1}),
         jdumps({**disc_data, "entered": 1})),
    )

    narration = None
    dice = None
    changes: list[str] = []
    event = "travel"
    # a location's on_enter effects fire once, on first actual entry —
    # whether or not the location opens an adventure
    if first_visit and not world:
        for eff in loc.get("on_enter", []):
            changes += _effects_for(cid, pack, eff, ch["id"] if ch else None)

    if world:
        # Generated world: track the visit, ground the arrival, tint the weather.
        legacy.note_world_visit(cid, world["id"])
        ident = world["identity"]
        state["world_id"] = world["id"]
        state["weather"] = {"key": ident.get("ambience", "world"), "desc": ident.get("weather", "")}
        if first_visit:
            for fact in ident.get("intro_facts", []):
                db.execute(
                    "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (new_id("fct"), cid, utcnow(), str(fact)[:300], "visible", 2, "world"),
                )
            legacy.record_event_memories(cid, "discovery", "all", f"First walked in {ident['name']}.")
            changes.append(f"Discovered: {ident['name']}.")
            db.log_event(cid, "world_visited_first", {"world_id": world["id"]})

    if loc.get("adventure"):
        adv = _resolve_adventure(cid, pack, loc["adventure"])
        if not adv:
            raise ValueError("adventure pack data missing")
        state["adventure_id"] = adv["id"]
        state["beat_location"] = loc["id"]
        _bind_source(cid, state, pack)
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
        # shared travel moves the whole party: clear split overrides
        db.execute("UPDATE characters SET location_id=NULL WHERE campaign_id=?", (cid,))
        try:
            from . import experience as _exp
            for _row in db.query("SELECT id FROM characters WHERE campaign_id=?", (cid,)):
                _exp.note_visit(cid, _row["id"], location_id)
        except Exception:
            pass
    else:
        db.execute(
            "UPDATE campaigns SET location_id=?, scene_id='hub', updated_at=? WHERE id=?",
            (location_id, utcnow(), cid),
        )
        if state.pop("world_id", None):
            # back on the Living Shore: shore weather resumes
            table = pack.get("weather") or [{"key": "mist", "weight": 1, "desc": "Sea mist."}]
            w = _pick_weighted(table)
            state["weather"] = {"key": w["key"], "desc": w.get("desc", w["key"])}
            db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(state), cid))
        narration = _trim(loc.get("desc", ""), 800)
        if ai.get_ai_config().get("enabled"):
            bridge = _gm_scene_bridge(cid, pack, campaign,
                                      {"label": f"traveled to {loc['name']}"}, loc)
            if bridge:
                narration = bridge
    db.add_transcript(cid, "player", f"[traveled] {loc['name']}")
    db.add_transcript(cid, "gm", narration, {"location_id": location_id, "event": event})
    db.add_journal(cid, f"{loc.get('name', location_id)}: {_trim(narration, 200)}", "travel")
    db.log_event(cid, event, {"location_id": location_id})
    advance_time(campaign, 1)
    return {"narration": narration, "changes": changes, "location": location_id,
            "tide": tide, "meta": {"ai_used": loc.get("adventure") is None}}


def rest(cid: str, chid: str | None = None) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    loc = worldpacks.get_location(pack, campaign["location_id"]) or {}
    rest_spec = loc.get("rest")
    if not rest_spec:
        raise ValueError("This is no place to rest.")
    ch = get_character(cid, chid)
    try:
        from . import experience as _exp
        _exp.note_visit(cid, chid, campaign["location_id"])
    except Exception:
        pass
    if _campaign_ruleset(cid) == "dnd5e":
        sheet = _dnd_sheet(ch)
        if not sheet:
            raise ValueError("this wanderer has no D&D sheet")
        healed = rules_dnd.long_rest(sheet)["healed"]
        ch["vigor"] = sheet["hp_max"]
        ch["nerve"] = ch["nerve_max"]
        _persist_character(ch)
        advance_time(campaign, 8)
        db.add_journal(cid, f"{ch['name']} keeps a long rest at {loc['name']}.", "rest")
        db.log_event(cid, "rest", {"healed": healed, "ruleset": "dnd5e", "character_id": ch["id"]})
        return {"narration": loc.get("rest_text", "You rest, and the shore allows it.")
                + " A long rest: wounds close, spells return.",
                "healed": {"vigor": max(0, sheet["hp_max"] - ch["vigor"] + healed), "nerve": 0}}
    owned = set(legacy.owned_upgrades(cid))
    dv = int(rest_spec.get("vigor", 2))
    dn = int(rest_spec.get("nerve", 2))
    loc_id = campaign["location_id"]
    if loc_id == "camp" and "camp_kettle" in owned:
        dv += 2
    if loc_id == "tavern" and "tavern_hammock" in owned:
        dv = ch["vigor_max"]
        dn = ch["nerve_max"]
    dv = min(dv, ch["vigor_max"] - ch["vigor"])
    dn = min(dn, ch["nerve_max"] - ch["nerve"])
    ch["vigor"] += max(0, dv)
    ch["nerve"] += max(0, dn)
    _persist_character(ch)
    # a rest refreshes the omen deck's generosity — and a befriended gull
    legacy.reset_omen_draws(cid, ch["id"])
    extra = ""
    if "gull_friend" in jloads(db.query_one(
            "SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {}).get("flags", []):
        ch_set(ch, "omen_bonus", {"skill": "notice", "mod": 1})
        extra = " The white gull lands near, and its round eye misses nothing on your behalf."
    if loc_id == "camp" and "camp_guestbook" in owned and secrets.randbelow(100) < 35:
        visitor = secrets.choice([
            "A door-tender's apprentice, in town to measure the Beam.",
            "A quiet cartographer buying accuracy with stories.",
            "A pilgrim of the Lantern Law, walking every fire on the shore.",
        ])
        mid = legacy.remember(cid, "tavern", "visitor", f"{visitor} signed Cardo's guestbook.")
        try:
            from . import experience as _exp
            _exp.note_heard(cid, ch["id"], "tavern")
            # hotfix 4: the resting character hears THIS visitor tale told at
            # the fire — a specific, authoritative acquisition
            if mid:
                _exp.note_memory(cid, ch["id"], mid)
        except Exception:
            pass
        extra += f" A visitor warms their hands at the fire: {visitor}"
    advance_time(campaign, 2)
    msg = loc.get("rest_text", "You rest, and the shore allows it.") + extra
    db.add_journal(cid, f"{ch['name']} rested at {loc['name']}.", "rest")
    db.log_event(cid, "rest", {"vigor": dv, "nerve": dn, "character_id": ch["id"]})
    return {"narration": msg, "healed": {"vigor": dv, "nerve": dn}}


def use_item(cid: str, item_id: str, chid: str | None = None) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    item = worldpacks.get_item(pack, item_id)
    if not item:
        raise ValueError("unknown item")
    ch = get_character(cid, chid)
    row = db.query_one(
        "SELECT id FROM inventory WHERE campaign_id=? AND item_id=? AND (character_id=? OR character_id IS NULL)",
        (cid, item_id, ch["id"] if ch else ""),
    )
    if not row:
        raise ValueError("You don't have that.")
    effects = item.get("use") or {}
    if not effects:
        return {"narration": item.get("desc", "It does nothing — yet."), "changes": []}
    changes: list[str] = []
    apply_effects(cid, pack, effects, changes, ch["id"] if ch else None)
    if effects.get("consume"):
        take_item(cid, pack, item_id, 1, chid=ch["id"] if ch else None)
        changes.append(f"Used up: {item['name']}.")
    narration = effects.get("text", f"You put the {item['name']} to use.")
    db.add_transcript(cid, "player", f"[used item] {item['name']}")
    db.add_transcript(cid, "gm", narration, {"item": item_id, "changes": changes})
    return {"narration": narration, "changes": changes}


# ==========================================================================
# Views / export
# ==========================================================================

def campaign_view(cid: str, chid: str | None = None) -> dict:
    campaign = get_campaign(cid)
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    state = jloads(campaign["state_json"], {})
    ch = get_character(cid, chid)
    if not ch:
        raise ValueError("campaign has no character")
    loc, world = _resolve_location(cid, pack, campaign["location_id"])
    loc = loc or {}
    adv = _resolve_adventure(cid, pack, state.get("adventure_id") or "") if state.get("adventure_id") else None
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
            "unstable": portal.get("unstable", False),
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
                    "available": _choice_available(c, cid, state, ch["id"])[0],
                    "locked_hint": _choice_available(c, cid, state, ch["id"])[1],
                }
                for c in ((scene or {}).get("choices", []))
            ],
            "hotspots": (scene or {}).get("hotspots") or loc.get("hotspots", []),
            "adventure_done": bool(state.get("adventure_done")),
        } if (adv or loc) else None,
        "tide": tide_for(campaign["drift"]),
        "tide_phase": legacy.tide_phase(campaign["drift"]),
        "weather": state.get("weather", {"key": "mist", "desc": "Sea mist."}),
        "turn": campaign["turn"],
        "drift": campaign["drift"],
        "beads": int(ch_get(ch, "beads", 0)),
        "upgrades_owned": legacy.owned_upgrades(cid),
        "omen_hand": legacy.omen_hand(cid, ch["id"]),
        "gm_style": (lambda s: {"id": s["id"], "label": s["label"]})(legacy.normalize_style(state)),
        "washashore": state.get("washashore"),
        "pending_roll": legacy.get_pending_roll(cid, ch["id"]),
        "dead": bool(ch_get(ch, "dead", False)),
        "character_id": ch["id"],
        "ruleset": _campaign_ruleset(cid),
        "dnd": (lambda s: {
            "class": s["class_name"], "species": s["species_name"],
            "background": s["background_name"], "level": s["level"],
            "xp": s["xp"], "xp_next": rules_dnd.XP_BY_LEVEL.get(s["level"] + 1, s["xp"]),
            "ac": s["ac"], "hp_max": s["hp_max"], "abilities": s["abilities"],
            "skills_prof": s["skills_prof"], "weapon": s["weapon"],
            "weapon_dmg": s["weapon_dmg"], "spells": s["spells"],
            "slots": s["slots"], "speed": s["speed"],
        })(_dnd_sheet(ch)) if _dnd_sheet(ch) else None,
        "world": ({
            "id": world["id"], "name": world["identity"].get("name", ""),
            "seed": world["seed"], "tint": world["identity"].get("tint", 0),
            "visits": world["visits"], "archetype": world["identity"].get("archetype_label", ""),
        } if world else None),
        "inventory": get_inventory(cid, ch["id"]),
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
