"""Saturday Multiverse — persistent, player-controlled D&D encounters.

Replaces the automatic multi-round resolver: encounters are created,
persisted in the database, and advance one turn at a time. Players choose
their own actions (attack, cast, defend, use an item, retreat, stabilize);
the engine resolves every outcome deterministically — the GM narrates and
never decides. Enemy turns are engine-resolved when the turn passes to
them. State survives server restarts; idle player turns are auto-dodged
by a bounded server-side sweep (lazy on access + an in-process watchdog).
"""
from __future__ import annotations

import time

from . import db, rules_dnd
from .db import jdumps, jloads, new_id, utcnow

TURN_TIMEOUT = 90  # seconds before an idle player turn is auto-dodged
MAX_ROUNDS = 20    # safety valve: stalemates end the encounter


class CombatError(ValueError):
    pass


def _active_row(cid: str):
    return db.query_one(
        "SELECT * FROM dnd_encounters WHERE campaign_id=? AND status='active'"
        " ORDER BY created_at DESC LIMIT 1", (cid,))


def _as_enc(row) -> dict:
    """A mutable working copy of the encounter row."""
    return {
        "id": row["id"], "campaign_id": row["campaign_id"],
        "status": row["status"], "round": row["round"],
        "turn_index": row["turn_index"], "state": jloads(row["state_json"], {}),
        "rewards_granted": row["rewards_granted"],
    }


def _save(enc: dict) -> None:
    db.execute(
        "UPDATE dnd_encounters SET state_json=?, status=?, round=?, turn_index=?,"
        " rewards_granted=?, updated_at=? WHERE id=?",
        (jdumps(enc["state"]), enc["status"], enc["round"], enc["turn_index"],
         enc["rewards_granted"], utcnow(), enc["id"]),
    )


def get_active(cid: str) -> dict | None:
    row = _active_row(cid)
    return _as_enc(row) if row else None


def start(cid: str, monster_key: str, count: int, chids: list[str] | None = None,
          location: str | None = None) -> dict:
    """Create a persistent encounter. Player HP starts from CURRENT sheet HP."""
    from . import gm
    if get_active(cid):
        raise CombatError("an encounter is already running in this campaign")
    monster = rules_dnd.MONSTERS.get(monster_key)
    if not monster:
        raise CombatError(f"unknown creature '{monster_key}'")
    count = max(1, min(6, int(count)))
    party = gm.list_characters(cid)
    if not party:
        raise CombatError("no characters in this campaign")
    if chids:
        wanted = set(chids)
        party = [c for c in party if c["id"] in wanted]
        if not party:
            raise CombatError("none of those characters exist here")
    participants, order = [], []
    for ch in party:
        sheet = gm.ch_get(ch, "dnd")
        if not sheet:
            raise CombatError(f"{ch['name']} has no D&D sheet — this is a D&D encounter")
        if int(sheet.get("hp", sheet["hp_max"])) <= 0:
            raise CombatError(f"{ch['name']} is downed and cannot enter combat")
        dex = sheet["ability_mods"]["dex"]
        p = {"kind": "player", "chid": ch["id"], "name": ch["name"],
             "init": rules_dnd._d(20) + dex,
             "hp": int(sheet.get("hp", sheet["hp_max"])),
             "hp_max": int(sheet["hp_max"]),
             "ac": int(sheet.get("ac", 10)), "joined_round": 1}
        participants.append(p)
        order.append({"slot": f"p:{ch['id']}", "name": ch["name"], "init": p["init"],
                      "kind": "player", "ref": ch["id"]})
    monsters = []
    for i in range(count):
        m = {"key": monster_key, "idx": i, "name": f"{monster['name']} {i + 1}",
             "init": rules_dnd._d(20) + 1, "hp": monster["hp"], "hp_max": monster["hp"],
             "ac": monster["ac"], "alive": True}
        monsters.append(m)
        order.append({"slot": f"m:{i}", "name": m["name"], "init": m["init"],
                      "kind": "monster", "ref": str(i), "mkey": monster_key})
    order.sort(key=lambda e: (-e["init"], 0 if e["kind"] == "player" else 1))
    levels = []
    for p in participants:
        ch = gm.get_character(cid, p["chid"])
        sheet = gm.ch_get(ch, "dnd") or {}
        levels.append(int(sheet.get("level", 1)))
    state = {
        "participants": participants, "monsters": monsters, "order": order,
        "turn_index": 0, "round": 1,
        "conditions": [], "concentration": None, "death_saves": {}, "threats": [],
        "log": [f"Combat begins: {count} x {monster['name']} "
                f"({rules_dnd.encounter_difficulty(levels, monster['xp'] * count)})."],
        "location": location, "outcome": None, "monster_name": monster["name"],
        "xp_pool": monster["xp"] * count,
    }
    enc_id = new_id("enc")
    now = utcnow()
    db.execute(
        "INSERT INTO dnd_encounters (id, campaign_id, status, round, turn_index,"
        " state_json, rewards_granted, created_at, updated_at) VALUES"
        " (?,?,'active',1,0,?,0,?,?)", (enc_id, cid, jdumps(state), now, now),
    )
    db.log_event(cid, "combat_start", {"encounter_id": enc_id, "monster": monster["name"],
                                       "count": count,
                                       "difficulty": rules_dnd.encounter_difficulty(levels, state["xp_pool"])})
    enc = get_active(cid)
    _resolve_until_player(enc)
    _save(enc)
    return view(cid)


# ------------------------------------------------------------------ views
def _hp_word(m: dict) -> str:
    if not m["alive"]:
        return "dead"
    ratio = m["hp"] / max(1, m["hp_max"])
    if ratio >= 1.0:
        return "unhurt"
    if ratio >= 0.5:
        return "wounded"
    if ratio > 0.15:
        return "bloodied"
    return "critical"


def view(cid: str, for_chid: str | None = None) -> dict | None:
    enc = get_active(cid)
    if not enc:
        return None
    from . import gm
    state = enc["state"]
    players = [{
        "chid": p["chid"], "name": p["name"], "init": p["init"], "hp": p["hp"],
        "hp_max": p.get("hp_max", p["hp"]), "ac": p["ac"],
        "conditions": [c["key"] for c in state["conditions"]
                       if c["target"] == f"p:{p['chid']}"],
        "is_me": (p["chid"] == for_chid) if for_chid else None,
    } for p in state["participants"]]
    monsters = [{
        "idx": m["idx"], "name": m["name"], "ac": m["ac"],
        "hp_word": _hp_word(m), "alive": m["alive"],
        "conditions": [c["key"] for c in state["conditions"] if c["target"] == f"m:{m['idx']}"],
    } for m in state["monsters"]]
    order = state["order"]
    ti = enc["turn_index"] % max(1, len(order))
    current = order[ti] if order else None
    ch = gm.get_character(cid, for_chid) if for_chid else None
    sheet = gm.ch_get(ch, "dnd") if ch else None
    my_turn = bool(current and current["kind"] == "player" and for_chid
                   and current["ref"] == for_chid and (not ch or not gm.ch_get(ch, "dead")))
    return {
        "encounter_id": enc["id"], "status": enc["status"], "round": enc["round"],
        "turn": current, "my_turn": my_turn, "monster_name": state["monster_name"],
        "players": players, "monsters": monsters,
        "conditions": state["conditions"],
        "concentration": state.get("concentration"),
        "log": state["log"][-14:], "outcome": state.get("outcome"),
        "xp_pool": state["xp_pool"],
        "actions_available": (["attack", "cast", "defend", "item", "retreat",
                               "stabilize", "second_wind", "breath_weapon"]
                              if my_turn and sheet and sheet.get("hp", 0) > 0 else []),
        "spells": sheet.get("spells", []) if sheet else [],
        "slots": sheet.get("slots", {}) if sheet else [],
    }


# ------------------------------------------------------------------ helpers
def _sync_player_hp(cid: str, enc: dict) -> None:
    """Persist every participant's current HP back to their character sheet."""
    from . import gm
    for p in enc["state"]["participants"]:
        ch = gm.get_character(cid, p["chid"])
        if not ch:
            continue
        sheet = gm.ch_get(ch, "dnd")
        if sheet:
            sheet["hp"] = max(0, int(p["hp"]))
            gm._persist_character(ch)


def _cond_of(state: dict, target: str, key: str) -> dict | None:
    return next((c for c in state["conditions"]
                 if c["target"] == target and c["key"] == key), None)


def _add_cond(state: dict, target: str, key: str, rounds: int) -> None:
    if not _cond_of(state, target, key):
        state["conditions"].append({"target": target, "key": key, "rounds": rounds})


def _clear_conds(state: dict, target: str, keys=None) -> None:
    state["conditions"] = [c for c in state["conditions"]
                           if not (c["target"] == target
                                   and (keys is None or c["key"] in keys))]


def _conscious_players(state: dict) -> list[dict]:
    out = []
    for p in state["participants"]:
        if p["hp"] <= 0:
            continue
        if _cond_of(state, f"p:{p['chid']}", "dead"):
            continue
        if _cond_of(state, f"p:{p['chid']}", "paralyzed"):
            continue
        out.append(p)
    return out


def _maybe_new_round(enc: dict) -> None:
    state = enc["state"]
    if enc["turn_index"] >= len(state["order"]):
        enc["turn_index"] = 0
        state["round"] += 1
        for c in state["conditions"]:
            if c["key"] in ("dodging", "poisoned", "paralyzed") and c["rounds"] < 900:
                c["rounds"] -= 1
        state["conditions"] = [c for c in state["conditions"] if c["rounds"] > 0]
        if state.get("concentration"):
            state["concentration"]["rounds_left"] = state["concentration"].get("rounds_left", 99) - 1
            if state["concentration"]["rounds_left"] <= 0:
                state["log"].append(f"Concentration on {state['concentration']['spell']} lapses.")
                state["concentration"] = None


def _damage_participant(cid: str, enc: dict, target: dict, dmg: int) -> dict:
    """Damage a participant honoring relentless endurance; a hit at 0 hp is an
    automatic death-save failure (SRD)."""
    from . import gm
    state = enc["state"]
    ch = gm.get_character(cid, target["chid"])
    sheet = gm.ch_get(ch, "dnd") or {}
    before = int(target["hp"])
    hp = before - dmg
    out = {"damage": min(before, dmg), "downed": False, "dead": False,
           "relentless_saved": False}
    if hp <= 0 and "relentless" in sheet.get("traits", []) and not sheet.get("relentless_used"):
        hp = 1
        sheet["relentless_used"] = True
        out["relentless_saved"] = True
        state["log"].append(f"{target['name']} refuses to fall (relentless endurance).")
    if hp <= 0:
        out["downed"] = True
        if before <= 0:
            out["dead"] = True
    target["hp"] = max(0, hp)
    if out["downed"]:
        _clear_conds(state, f"p:{target['chid']}")
        _add_cond(state, f"p:{target['chid']}", "dying", 999)
        state["log"].append(f"{target['name']} falls, dying.")
        if out["dead"]:
            _mark_dead(cid, enc, target)
    _sync_player_hp(cid, enc)
    return out


def _mark_dead(cid: str, enc: dict, target: dict) -> None:
    from . import gm
    state = enc["state"]
    _clear_conds(state, f"p:{target['chid']}")
    _add_cond(state, f"p:{target['chid']}", "dead", 999)
    ch = gm.get_character(cid, target["chid"])
    if ch:
        sheet = gm.ch_get(ch, "dnd") or {}
        sheet["hp"] = 0
        sheet["dead"] = True
        gm.ch_set(ch, "dead", True)
        gm._persist_character(ch)
    state["log"].append(f"{target['name']} dies.")
    db.log_event(cid, "combat_death", {"chid": target["chid"], "name": target["name"]})


def _death_save(enc: dict, cid: str, chid: str) -> None:
    """A dying player's turn: an engine-rolled death saving throw."""
    state = enc["state"]
    p = next((x for x in state["participants"] if x["chid"] == chid), None)
    if not p:
        enc["turn_index"] += 1
        return
    if _cond_of(state, f"p:{chid}", "stable") or _cond_of(state, f"p:{chid}", "dead"):
        # SRD: the stabilized don't roll; the dead don't act at all
        enc["turn_index"] += 1
        _maybe_new_round(enc)
        return
    saves = state.setdefault("death_saves", {}).setdefault(chid, {"success": 0, "fail": 0})
    raw = rules_dnd._d(20)
    if raw == 20:
        p["hp"] = 1
        state["death_saves"][chid] = {"success": 0, "fail": 0}
        _clear_conds(state, f"p:{chid}")
        state["log"].append(f"{p['name']} rolls a natural 20 on a death save and lurches upright!")
    elif raw == 1:
        saves["fail"] += 2
        state["log"].append(f"{p['name']} fails a death save badly (nat 1).")
    elif raw >= 10:
        saves["success"] += 1
        state["log"].append(f"{p['name']} survives a death save ({saves['success']}/3).")
    else:
        saves["fail"] += 1
        state["log"].append(f"{p['name']} fails a death save ({saves['fail']}/3).")
    if saves["success"] >= 3:
        _clear_conds(state, f"p:{chid}", {"dying"})
        _add_cond(state, f"p:{chid}", "stable", 999)
        state["log"].append(f"{p['name']} is stabilized — unconscious but alive.")
    if saves["fail"] >= 3:
        _mark_dead(cid, enc, p)
    enc["turn_index"] += 1
    _maybe_new_round(enc)


def _plain_save(ability: str, dc: int) -> dict:
    return rules_dnd.make_save({"ability_mods": {ability: 0}, "proficiency": 0,
                                "saves_prof": []}, ability, dc)


# ------------------------------------------------------------------ flow
def _resolve_until_player(enc: dict) -> None:
    """Advance through enemy/paralyzed/downed turns until a player must act,
    or the encounter ends. Enemy turns are engine-resolved, never AI-decided."""
    state = enc["state"]
    guard = 0
    while guard < 80:
        guard += 1
        order = state["order"]
        if all(not m["alive"] for m in state["monsters"]):
            _save(enc)
            _finish(enc, "victory")
            return
        alive_players = [p for p in state["participants"]
                         if not _cond_of(state, f"p:{p['chid']}", "dead")]
        if not alive_players:
            _save(enc)
            _finish(enc, "defeat")
            return
        if all(p["hp"] <= 0 and (_cond_of(state, f"p:{p['chid']}", "stable")
                                 or _cond_of(state, f"p:{p['chid']}", "dead"))
               for p in alive_players):
            _save(enc)
            _finish(enc, "defeat")
            return
        if state["round"] > MAX_ROUNDS:
            _save(enc)
            _finish(enc, "stalemate")
            return
        ti = enc["turn_index"] % len(order)
        cur = order[ti]
        if cur["kind"] == "player":
            p = next((x for x in state["participants"] if x["chid"] == cur["ref"]), None)
            if p and p["hp"] > 0 and not _cond_of(state, f"p:{cur['ref']}", "paralyzed"):
                return  # a live player must act
            _death_save(enc, enc["campaign_id"], cur["ref"])
            continue
        _enemy_turn(enc, cur)
    _save(enc)


def _enemy_turn(enc: dict, cur: dict) -> None:
    state = enc["state"]
    m = next((x for x in state["monsters"] if x["idx"] == int(cur["ref"])), None)
    if not m or not m["alive"]:
        enc["turn_index"] += 1
        _maybe_new_round(enc)
        return
    monster = rules_dnd.MONSTERS.get(cur.get("mkey") or m["key"],
                                     rules_dnd.MONSTERS["goblin"])
    if _cond_of(state, f"m:{m['idx']}", "paralyzed"):
        save = _plain_save("wis", 13)
        if save["success"]:
            _clear_conds(state, f"m:{m['idx']}", {"paralyzed"})
            state["log"].append(f"{m['name']} shakes off the paralysis.")
        else:
            state["log"].append(f"{m['name']} remains held.")
        enc["turn_index"] += 1
        _maybe_new_round(enc)
        return
    targets = _conscious_players(state)
    if not targets:
        dying = [p for p in state["participants"]
                 if p["hp"] <= 0 and _cond_of(state, f"p:{p['chid']}", "dying")]
        if dying and m["alive"]:
            # SRD practice: monsters finish the dying (auto-hit at 0 hp)
            target = dying[0]
            state["log"].append(f"{m['name']} turns on the fallen {target['name']}...")
            _damage_participant(enc["campaign_id"], enc, target, 1)
            enc["turn_index"] += 1
            _maybe_new_round(enc)
            return
        state["log"].append(f"{m['name']} stands over the fallen, waiting.")
        enc["turn_index"] += 1
        _maybe_new_round(enc)
        return
    # prefer whoever hurt this monster most recently, else the first conscious
    threats = [t for t in state.get("threats", []) if t["m"] == m["idx"]]
    target = targets[0]
    if threats:
        t = next((x for x in targets if x["chid"] == threats[-1]["chid"]), None)
        if t:
            target = t
    dodging = bool(_cond_of(state, f"p:{target['chid']}", "dodging"))
    nat = rules_dnd._d(20)
    if dodging:  # dodge: attackers roll with disadvantage
        nat = min(nat, rules_dnd._d(20))
    hit = nat == 20 or (nat != 1 and nat + 4 >= target["ac"])
    if not hit:
        state["log"].append(f"{m['name']} attacks {target['name']} and misses.")
    else:
        dmg, det = rules_dnd.roll_damage(monster["dmg"], crit=(nat == 20))
        if monster.get("poison"):
            pdmg, _pd = rules_dnd.roll_damage(monster["poison"])
            dmg += pdmg
            _add_cond(state, f"p:{target['chid']}", "poisoned", 2)
            state["log"].append(
                f"{m['name']} bites {target['name']} — venom courses ({det} +{pdmg} poison).")
        else:
            state["log"].append(f"{m['name']} hits {target['name']} ({det}).")
        _damage_participant(enc["campaign_id"], enc, target, dmg)
        if state.get("concentration") and state["concentration"]["chid"] == target["chid"]:
            save = _plain_save("con", 10)
            if save["success"]:
                state["log"].append(f"{target['name']} holds concentration.")
            else:
                state["log"].append(f"{target['name']}'s {state['concentration']['spell']} fizzles — concentration lost.")
                state["concentration"] = None
                state["conditions"] = [c for c in state["conditions"]
                                       if c["key"] not in ("blessed", "shielded")]
    enc["turn_index"] += 1
    _maybe_new_round(enc)


# ------------------------------------------------------------------ actions
def action(cid: str, enc_id: str, chid: str, act: dict) -> dict:
    """A player's chosen action on their own turn. Engine-authoritative."""
    from . import gm
    enc = get_active(cid)
    if not enc or enc["id"] != enc_id:
        raise CombatError("no such active encounter")
    state = enc["state"]
    order = state["order"]
    ti = enc["turn_index"] % max(1, len(order))
    cur = order[ti]
    if not cur or cur["kind"] != "player" or cur["ref"] != chid:
        raise CombatError("it is not that character's turn")
    p = next((x for x in state["participants"] if x["chid"] == chid), None)
    if not p or p["hp"] <= 0:
        raise CombatError("downed characters act only through death saves")
    ch = gm.get_character(cid, chid)
    sheet = gm.ch_get(ch, "dnd")
    kind = str(act.get("type", "")).lower()

    if kind == "attack":
        idx = int(act.get("target", -1))
        m = next((x for x in state["monsters"] if x["idx"] == idx and x["alive"]), None)
        if not m:
            raise CombatError("choose a living target")
        dis = bool(_cond_of(state, f"p:{chid}", "poisoned"))
        blessed = bool(_cond_of(state, f"p:{chid}", "blessed"))
        atk = rules_dnd.attack_roll(sheet, m["ac"], dis=dis)
        if blessed:
            atk["total"] += 1
            atk["hit"] = atk["nat"] == 20 or (atk["nat"] != 1 and atk["total"] >= m["ac"])
        if atk["hit"]:
            dmg, det = rules_dnd.roll_damage(sheet["weapon_dmg"], atk["crit"])
            m["hp"] -= dmg
            state.setdefault("threats", []).append({"m": m["idx"], "chid": chid})
            state["log"].append(f"{p['name']} strikes {m['name']} ({det}, {dmg} damage).")
            if m["hp"] <= 0:
                m["hp"] = 0
                m["alive"] = False
                state["log"].append(f"{m['name']} falls!")
        else:
            state["log"].append(f"{p['name']} attacks {m['name']} and misses ({atk['text']}).")

    elif kind == "cast":
        spell_id = str(act.get("spell", ""))
        spell = rules_dnd.SPELLS.get(spell_id)
        if not spell:
            raise CombatError("no such spell in the open rules")
        result = rules_dnd.cast_spell(sheet, spell_id)
        gm._persist_character(ch)  # slot consumption persisted
        _log = f"{p['name']} casts {spell['name']}."
        if spell.get("concentration"):
            if state.get("concentration"):
                state["log"].append(f"{state['concentration']['spell']} ends — concentration broken.")
            state["concentration"] = {"chid": chid, "spell": spell["name"], "rounds_left": 10}
        if spell.get("buff") == "attack":
            _add_cond(state, f"p:{chid}", "blessed", 10)
        if spell.get("buff") == "ac" and act.get("target"):
            _add_cond(state, f"p:{act['target']}", "shielded", 10)
        if spell.get("damage"):
            idx = int(act.get("target", -1))
            m = next((x for x in state["monsters"] if x["idx"] == idx and x["alive"]), None)
            if not m:
                raise CombatError("choose a living target for that spell")
            if spell.get("attack"):
                atk = rules_dnd.attack_roll(sheet, m["ac"])
                if atk["hit"]:
                    dmg, det = rules_dnd.roll_damage(spell["damage"], atk["crit"])
                    m["hp"] -= dmg
                    state["log"].append(f"{p['name']}'s {spell['name']} strikes {m['name']} ({det}).")
                else:
                    state["log"].append(f"{p['name']}'s {spell['name']} misses {m['name']}.")
            elif spell.get("auto"):
                dmg, det = rules_dnd.roll_damage(spell["damage"])
                m["hp"] -= dmg
                state["log"].append(f"{p['name']}'s {spell['name']} never misses {m['name']} ({det}).")
            else:  # save-based damage
                save = _plain_save(spell.get("save", "dex"), 13)
                dmg, det = rules_dnd.roll_damage(spell["damage"])
                if save["success"]:
                    dmg = dmg // 2
                m["hp"] -= dmg
                state["log"].append(f"{spell['name']} engulfs {m['name']} ({det}, "
                                    f"{'halved' if save['success'] else 'full damage'}).")
            state.setdefault("threats", []).append({"m": m["idx"], "chid": chid})
            if m["hp"] <= 0:
                m["hp"] = 0
                m["alive"] = False
                state["log"].append(f"{m['name']} falls!")
        if spell.get("paralyze_rounds"):
            idx = int(act.get("target", -1))
            m = next((x for x in state["monsters"] if x["idx"] == idx and x["alive"]), None)
            if not m:
                raise CombatError("choose a living target")
            save = _plain_save("wis", 13)
            if save["success"]:
                state["log"].append(f"{m['name']} resists {spell['name']}.")
            else:
                _add_cond(state, f"m:{m['idx']}", "paralyzed", spell["paralyze_rounds"])
                state["log"].append(f"{m['name']} is held in place!")
        if spell.get("heal"):
            tid = act.get("target") or chid
            tp = next((x for x in state["participants"] if x["chid"] == tid), None)
            if not tp:
                raise CombatError("choose a party member to heal")
            mod = max(0, sheet["ability_mods"][rules_dnd.CLASSES[sheet["class"]]["primary"]])
            amount, det = rules_dnd.roll_damage(spell["heal"].replace("ability", f"+{mod}"))
            before = tp["hp"]
            tp["hp"] = min(tp["hp"] + amount, tp.get("hp_max", tp["hp"] + amount))
            if before <= 0 and tp["hp"] > 0:
                _clear_conds(state, f"p:{tp['chid']}", {"dying", "stable"})
                state.get("death_saves", {}).pop(tp["chid"], None)
                state["log"].append(f"{tp['name']} is revived by {spell['name']}!")
            state["log"].append(f"{p['name']} heals {tp['name']} ({det}: +{tp['hp'] - before}).")
            _sync_player_hp(cid, enc)

    elif kind == "defend":
        _add_cond(state, f"p:{chid}", "dodging", 1)
        state["log"].append(f"{p['name']} takes a defensive stance.")

    elif kind == "second_wind":
        if sheet.get("second_wind_used") or sheet["class"] != "fighter":
            raise CombatError("second wind is a fighter feature, once per rest")
        heal, det = rules_dnd.roll_damage(f"1d10+{sheet['level']}")
        before = p["hp"]
        p["hp"] = min(p["hp"] + heal, p.get("hp_max", p["hp"] + heal))
        sheet["second_wind_used"] = True
        gm._persist_character(ch)
        if before <= 0 and p["hp"] > 0:
            _clear_conds(state, f"p:{chid}", {"dying", "stable"})
        state["log"].append(f"{p['name']} gathers a second wind (+{p['hp'] - before} hp).")
        _sync_player_hp(cid, enc)

    elif kind == "breath_weapon":
        if sheet.get("species") != "dragonborn" or sheet.get("breath_used"):
            raise CombatError("breath weapon is a dragonborn feature, once per rest")
        idx = int(act.get("target", -1))
        m = next((x for x in state["monsters"] if x["idx"] == idx and x["alive"]), None)
        if not m:
            raise CombatError("choose a living target")
        dmg, det = rules_dnd.roll_damage("2d6")
        m["hp"] -= dmg
        sheet["breath_used"] = True
        gm._persist_character(ch)
        state["log"].append(f"{p['name']} breathes fire on {m['name']} ({det}).")
        state.setdefault("threats", []).append({"m": m["idx"], "chid": chid})
        if m["hp"] <= 0:
            m["hp"] = 0
            m["alive"] = False
            state["log"].append(f"{m['name']} falls!")

    elif kind == "item":
        item_id = str(act.get("item", ""))
        heal = _use_inventory_item(cid, chid, item_id)
        before = p["hp"]
        p["hp"] = min(p["hp"] + heal, p.get("hp_max", p["hp"] + heal))
        if before <= 0 and p["hp"] > 0:
            _clear_conds(state, f"p:{chid}", {"dying", "stable"})
            state.get("death_saves", {}).pop(chid, None)
        state["log"].append(f"{p['name']} uses {item_id} (+{p['hp'] - before} hp).")
        _sync_player_hp(cid, enc)

    elif kind == "stabilize":
        target_id = str(act.get("target", ""))
        ally = next((x for x in state["participants"] if x["chid"] == target_id), None)
        if not ally or ally["hp"] > 0:
            raise CombatError("choose a downed ally")
        mod = sheet["ability_mods"]["wis"] + (sheet["proficiency"]
                                              if "medicine" in sheet.get("skills_prof", []) else 0)
        raw = rules_dnd._d(20)
        if raw + mod >= 10:
            ds = state.setdefault("death_saves", {}).setdefault(target_id,
                                                                {"success": 0, "fail": 0})
            ds["success"] += 1
            if ds["success"] >= 3:
                _clear_conds(state, f"p:{target_id}", {"dying"})
                _add_cond(state, f"p:{target_id}", "stable", 999)
                state["log"].append(f"{p['name']} steadies {ally['name']}: stabilized.")
            else:
                state["log"].append(f"{p['name']} aids {ally['name']}'s death save.")
        else:
            state["log"].append(f"{p['name']} fails to steady {ally['name']}.")

    elif kind == "retreat":
        mod = sheet["ability_mods"]["dex"] + (sheet["proficiency"]
                                              if ("athletics" in sheet.get("skills_prof", [])
                                                  or "acrobatics" in sheet.get("skills_prof", [])) else 0)
        raw = rules_dnd._d(20)
        dc = 10 + enc["round"]
        if raw + mod >= dc:
            state["log"].append(f"{p['name']} breaks away from the fight.")
            _save(enc)
            _finish(enc, "retreat", fleeing=p["name"])
            return view(cid, for_chid=chid)
        state["log"].append(f"{p['name']} tries to withdraw and fails — the enemy closes in.")
        _damage_participant(cid, enc, p, 2)

    else:
        raise CombatError("unknown action type")

    enc["turn_index"] += 1
    _maybe_new_round(enc)
    _save(enc)
    _resolve_until_player(enc)
    _save(enc)
    return view(cid, for_chid=chid)


def _use_inventory_item(cid: str, chid: str, item_id: str) -> int:
    from . import gm, worldpacks
    rows = gm.get_inventory(cid)
    row = None
    for r in rows:
        if r["item_id"] == item_id and r["character_id"] == chid and (r["qty"] or 1) > 0:
            row = r
            break
    if not row:
        raise CombatError("that character does not carry that item")
    pack = worldpacks.load_pack(gm.get_campaign(cid)["pack_id"])
    item = worldpacks.get_item(pack, item_id)
    use = (item or {}).get("use") or {}
    heal = int((use.get("heal") or {}).get("vigor", 0)) if isinstance(use.get("heal"), dict) else 0
    if heal <= 0:
        raise CombatError("that item does not restore health")
    if use.get("consume"):
        if (row["qty"] or 1) > 1:
            db.execute("UPDATE inventory SET qty=qty-1 WHERE rowid=?", (row["rowid"],))
        else:
            db.execute("DELETE FROM inventory WHERE rowid=?", (row["rowid"],))
    return heal


# ------------------------------------------------------------------ join/timeout/finish
def join(cid: str, enc_id: str, chid: str, location: str | None = None) -> dict:
    """A co-located character joins an encounter in progress (round 1 only)."""
    from . import gm
    enc = get_active(cid)
    if not enc or enc["id"] != enc_id:
        raise CombatError("no such active encounter")
    state = enc["state"]
    if state["round"] > 1:
        raise CombatError("reinforcements may join only in the first round")
    if any(x["chid"] == chid for x in state["participants"]):
        raise CombatError("already in this encounter")
    if location and state.get("location") and location != state["location"]:
        raise CombatError("that character cannot reach this encounter")
    ch = gm.get_character(cid, chid)
    sheet = gm.ch_get(ch, "dnd")
    if not sheet:
        raise CombatError("that character has no D&D sheet")
    if int(sheet.get("hp", sheet["hp_max"])) <= 0:
        raise CombatError("that character is downed")
    dex = sheet["ability_mods"]["dex"]
    p = {"kind": "player", "chid": chid, "name": ch["name"],
         "init": rules_dnd._d(20) + dex, "hp": int(sheet.get("hp", sheet["hp_max"])),
         "hp_max": int(sheet["hp_max"]), "ac": int(sheet.get("ac", 10)),
         "joined_round": state["round"]}
    state["participants"].append(p)
    entry = {"slot": f"p:{chid}", "name": ch["name"], "init": p["init"],
             "kind": "player", "ref": chid}
    pos = len(state["order"])
    for i, e in enumerate(state["order"]):
        if e["init"] < p["init"]:
            pos = i
            break
    state["order"].insert(pos, entry)
    state["log"].append(f"{ch['name']} joins the fight!")
    _save(enc)
    _resolve_until_player(enc)
    _save(enc)
    db.log_event(cid, "combat_join", {"encounter_id": enc_id, "chid": chid})
    return view(cid, for_chid=chid)


def last_view(cid: str) -> dict | None:
    """Public view of the most recent encounter (active or complete) — used
    when an action ends the fight and the active lookup comes up empty."""
    row = db.query_one(
        "SELECT * FROM dnd_encounters WHERE campaign_id=? ORDER BY updated_at DESC LIMIT 1",
        (cid,))
    if not row:
        return None
    enc = _as_enc(row)
    state = enc["state"]
    players = [{
        "chid": p["chid"], "name": p["name"], "init": p["init"], "hp": p["hp"],
        "hp_max": p.get("hp_max", p["hp"]), "ac": p["ac"],
        "conditions": [c["key"] for c in state["conditions"]
                       if c["target"] == f"p:{p['chid']}"],
    } for p in state["participants"]]
    monsters = [{
        "idx": m["idx"], "name": m["name"], "ac": m["ac"],
        "hp_word": _hp_word(m), "alive": m["alive"],
        "conditions": [c["key"] for c in state["conditions"] if c["target"] == f"m:{m['idx']}"],
    } for m in state["monsters"]]
    return {
        "encounter_id": enc["id"], "status": enc["status"], "round": enc["round"],
        "turn": None, "my_turn": False, "monster_name": state["monster_name"],
        "players": players, "monsters": monsters,
        "conditions": state["conditions"],
        "concentration": state.get("concentration"),
        "log": state["log"][-14:], "outcome": state.get("outcome"),
        "xp_pool": state["xp_pool"], "actions_available": [],
    }


def sweep_timeouts(cid: str | None = None) -> int:
    """Auto-dodge idle player turns. Bounded, server-side, idempotent."""
    from .mp import _iso_to_ts
    if cid:
        rows = db.query("SELECT * FROM dnd_encounters WHERE campaign_id=? AND status='active'", (cid,))
    else:
        rows = db.query("SELECT * FROM dnd_encounters WHERE status='active'")
    swept = 0
    for row in rows:
        enc = _as_enc(row)
        state = enc["state"]
        order = state.get("order", [])
        if not order:
            continue
        ti = enc["turn_index"] % len(order)
        cur = order[ti]
        if cur["kind"] != "player":
            continue
        started = _iso_to_ts(row["updated_at"])
        if time.time() - started <= TURN_TIMEOUT:
            continue
        p = next((x for x in state["participants"] if x["chid"] == cur["ref"]), None)
        if p and p["hp"] > 0:
            _add_cond(state, f"p:{p['chid']}", "dodging", 1)
            state["log"].append(f"{p['name']} hesitates — the moment passes (turn auto-defended).")
            enc["turn_index"] += 1
            _maybe_new_round(enc)
            _save(enc)
            _resolve_until_player(enc)
            _save(enc)
            swept += 1
            db.log_event(enc["campaign_id"], "combat_timeout", {"chid": cur["ref"]})
        elif p:
            _death_save(enc, enc["campaign_id"], cur["ref"])
            _save(enc)
            _resolve_until_player(enc)
            _save(enc)
            swept += 1
    return swept


def _finish(enc: dict, outcome: str, fleeing: str | None = None) -> dict:
    from . import gm, mp
    state = enc["state"]
    cid = enc["campaign_id"]
    state["outcome"] = outcome
    _sync_player_hp(cid, enc)
    lines = {
        "victory": f"The last enemy falls. Victory — {state['xp_pool']} experience is earned.",
        "defeat": "The party is overcome. Darkness takes the field.",
        "retreat": f"{fleeing or 'The party'} breaks away from the fight.",
        "stalemate": "The fight dissolves — neither side can press on.",
    }
    state["log"].append(lines[outcome])
    if outcome == "victory" and not enc["rewards_granted"]:
        enc["rewards_granted"] = 1
        for p in state["participants"]:
            ch = gm.get_character(cid, p["chid"])
            if not ch or gm.ch_get(ch, "dead"):
                continue
            sheet = gm.ch_get(ch, "dnd")
            if sheet:
                level = rules_dnd.gain_xp(sheet, state["xp_pool"])
                gm._persist_character(ch)
                if level:
                    db.log_event(cid, "level_up", {"chid": p["chid"], "level": level["level"]})
        db.log_event(cid, "combat_victory", {"xp": state["xp_pool"],
                                             "monster": state["monster_name"]})
        mp.remember(cid, "party", "combat",
                    f"The party won a fight against {state['monster_name']}.")
    elif outcome == "defeat":
        db.log_event(cid, "combat_defeat", {"monster": state["monster_name"]})
        mp.remember(cid, "party", "combat",
                    f"The party was defeated by {state['monster_name']} and left for dead.")
    enc["status"] = "complete"
    _save(enc)
    db.log_event(cid, "combat_end", {"encounter_id": enc["id"], "outcome": outcome})
    return {"outcome": outcome, "log": state["log"][-6:]}
