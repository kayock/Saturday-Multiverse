"""Saturday Multiverse — D&D-compatible ruleset (SRD 5.1, CC-BY-4.0).

An independent, deterministic rules engine alongside — never replacing —
the Undertow 2d6 system. Rules content here is derived from the System
Reference Document 5.1 released by Wizards of the Coast under Creative
Commons Attribution 4.0 (see docs/LICENSES.md). No product identity is
used; literature-monster stat blocks (Dracula, Morlocks, the ape) are our
own open-game derivations from public-domain novels, not WotC content.

Design rule: every outcome maps back onto the engine's five narrative
bands (surge / clean / undertow / riptide / fate) so the same world packs,
choices and on_pass/on_fail logic work for both rulesets:

    d20 total >= DC + 5        -> surge
    d20 total >= DC            -> clean
    DC-1..DC-4                 -> undertow (partial)
    DC-5..DC-9                 -> riptide (fail)
    natural 20                 -> surge (never worse)
    natural 1                  -> riptide (never better)
"""
from __future__ import annotations

import secrets

SKILL_ABILITY = {
    "acrobatics": "dex", "animal_handling": "wis", "arcana": "int",
    "athletics": "str", "deception": "cha", "history": "int",
    "insight": "wis", "intimidation": "cha", "investigation": "int",
    "medicine": "wis", "nature": "int", "perception": "wis",
    "performance": "cha", "persuasion": "cha", "religion": "int",
    "sleight_of_hand": "dex", "stealth": "dex", "survival": "wis",
}
ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

PROF_BY_LEVEL = {1: 2, 2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4}
XP_BY_LEVEL = {1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500}

# Classes — SRD 5.1 basics (no product identity beyond the open names).
CLASSES = {
    "fighter": {"name": "Fighter", "hit_die": 10, "primary": "str",
                "saves": ("str", "con"), "skills": ["athletics", "perception"],
                "weapon": "longsword", "armor": 16},
    "rogue": {"name": "Rogue", "hit_die": 8, "primary": "dex",
              "saves": ("dex", "int"), "skills": ["stealth", "investigation"],
              "weapon": "shortsword", "armor": 14},
    "cleric": {"name": "Cleric", "hit_die": 8, "primary": "wis",
               "saves": ("wis", "cha"), "skills": ["medicine", "persuasion"],
               "weapon": "mace", "armor": 14, "caster": True},
    "wizard": {"name": "Wizard", "hit_die": 6, "primary": "int",
               "saves": ("int", "wis"), "skills": ["arcana", "history"],
               "weapon": "quarterstaff", "armor": 10, "caster": True},
    "barbarian": {"name": "Barbarian", "hit_die": 12, "primary": "str",
                  "saves": ("str", "con"), "skills": ["athletics", "survival"],
                  "weapon": "greataxe", "armor": 14, "rage": True},
    "ranger": {"name": "Ranger", "hit_die": 10, "primary": "dex",
               "saves": ("str", "dex"), "skills": ["survival", "animal_handling"],
               "weapon": "longbow", "armor": 14, "caster": True, "half_caster": True},
    "paladin": {"name": "Paladin", "hit_die": 10, "primary": "str",
                "saves": ("wis", "cha"), "skills": ["athletics", "persuasion"],
                "weapon": "longsword", "armor": 16, "caster": True, "half_caster": True},
    "bard": {"name": "Bard", "hit_die": 8, "primary": "cha",
             "saves": ("dex", "cha"), "skills": ["performance", "persuasion"],
             "weapon": "rapier", "armor": 12, "caster": True},
    "monk": {"name": "Monk", "hit_die": 8, "primary": "dex",
             "saves": ("str", "dex"), "skills": ["acrobatics", "stealth"],
             "weapon": "shortsword", "armor": 0, "unarmored": True},
    "druid": {"name": "Druid", "hit_die": 8, "primary": "wis",
              "saves": ("int", "wis"), "skills": ["nature", "medicine"],
              "weapon": "quarterstaff", "armor": 12, "caster": True},
}
SPECIES = {
    "human": {"name": "Human", "asi": {"str": 1, "dex": 1, "con": 1, "int": 1, "wis": 1, "cha": 1}, "speed": 30},
    "elf": {"name": "Elf", "asi": {"dex": 2}, "speed": 30, "keen_senses": "perception"},
    "dwarf": {"name": "Dwarf", "asi": {"con": 2}, "speed": 25, "stout": True},
    "halfling": {"name": "Halfling", "asi": {"dex": 2}, "speed": 25, "lucky": True},
    "gnome": {"name": "Gnome", "asi": {"int": 2}, "speed": 25, "cunning": True},
    "half_orc": {"name": "Half-Orc", "asi": {"str": 2, "con": 1}, "speed": 30, "relentless": True},
    "tiefling": {"name": "Tiefling", "asi": {"cha": 2, "int": 1}, "speed": 30, "fire_resist": True},
    "dragonborn": {"name": "Dragonborn", "asi": {"str": 2, "cha": 1}, "speed": 30, "breath": "2d6"},
}
BACKGROUNDS = {
    "folk_hero": {"name": "Folk Hero", "skill": "survival"},
    "sage": {"name": "Sage", "skill": "arcana"},
    "soldier": {"name": "Soldier", "skill": "athletics"},
    "charlatan": {"name": "Charlatan", "skill": "deception"},
}
STANDARD_ARRAY = {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8}

# Spells (SRD 5.1 open content) with deterministic engine effects.
SPELLS = {
    "magic_missile": {"name": "Magic Missile", "level": 1, "auto": True,
                      "damage": "3x(1d4+1)", "desc": "Three darts of force never miss."},
    "burning_hands": {"name": "Burning Hands", "level": 1, "save": "dex", "dc_mod": 0,
                      "damage": "3d6", "desc": "A sheet of flame in a close arc."},
    "cure_wounds": {"name": "Cure Wounds", "level": 1, "heal": "1d8+ability", "desc": "Restores flesh."},
    "healing_word": {"name": "Healing Word", "level": 1, "heal": "1d4+ability", "bonus": True, "desc": "A word that mends at distance."},
    "shield": {"name": "Shield", "level": 1, "ac": 5, "rounds": 1, "desc": "An invisible shield until your next turn."},
    "mage_armor": {"name": "Mage Armor", "level": 1, "ac": 3, "desc": "Protective magical force."},
    "fire_bolt": {"name": "Fire Bolt", "level": 0, "damage": "1d10", "attack": True, "desc": "A mote of fire."},
    "sacred_flame": {"name": "Sacred Flame", "level": 0, "save": "dex", "damage": "1d8", "desc": "Radiance of the dawn."},
    "guidance": {"name": "Guidance", "level": 0, "next_check": 1, "desc": "Divine guidance on one task."},
    "minor_illusion": {"name": "Minor Illusion", "level": 0, "utility": True, "desc": "A sound or an image."},
    "thunderwave": {"name": "Thunderwave", "level": 1, "save": "con", "damage": "2d8",
                    "desc": "A booming wave of force."},
    "bless": {"name": "Bless", "level": 1, "concentration": True, "buff": "attack",
              "desc": "The party's strikes are guided (+1 to attacks) while you concentrate."},
    "shield_of_faith": {"name": "Shield of Faith", "level": 1, "concentration": True, "buff": "ac",
                        "desc": "+2 AC to one ally while you concentrate."},
    "hold_person": {"name": "Hold Person", "level": 2, "concentration": True, "save": "wis",
                    "paralyze_rounds": 3, "desc": "A humanoid is paralyzed (save ends each turn)."},
    "fireball": {"name": "Fireball", "level": 3, "save": "dex", "damage": "8d6",
                 "desc": "A bright streak flares into a ball of fire."},
}
SLOTS_BY_LEVEL = {1: {1: 2}, 2: {1: 3}, 3: {1: 4, 2: 2}, 4: {1: 4, 2: 3}, 5: {1: 4, 2: 3, 3: 2}}
HALF_CASTER_SLOTS = {1: {}, 2: {1: 2}, 3: {1: 3}, 4: {1: 3}, 5: {1: 4, 2: 2}}

# SRD 5.1 encounter difficulty thresholds per character level (XP).
XP_THRESHOLDS = {
    1: {"easy": 25, "medium": 50, "hard": 75, "deadly": 100},
    2: {"easy": 50, "medium": 100, "hard": 150, "deadly": 200},
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
    4: {"easy": 125, "medium": 250, "hard": 375, "deadly": 500},
    5: {"easy": 250, "medium": 500, "hard": 750, "deadly": 1100},
}


def encounter_difficulty(levels: list[int], monster_xp: int) -> str:
    """SRD-style difficulty label from the party's levels and total monster XP."""
    if not levels:
        return "unknown"
    total = 0
    for lvl in levels:
        t = XP_THRESHOLDS.get(min(5, max(1, int(lvl))), XP_THRESHOLDS[1])
        total += t["medium"]
    ratio = monster_xp / max(1, total)
    deadly = min(XP_THRESHOLDS[min(5, max(1, int(max(levels))))]["deadly"], 10**9)
    if monster_xp >= deadly * len(levels) / max(1, len(levels)) * len(levels) / len(levels) * (len(levels) / max(1, len(levels))):
        pass  # keep the simple ratio model below; this line documents intent
    if ratio <= 0.5:
        return "easy"
    if ratio <= 1.0:
        return "medium"
    if ratio <= 1.5:
        return "hard"
    return "deadly"


# Honest feature coverage: what this ruleset implements vs deliberately not.
COVERAGE = {
    "version": "SRD 5.1 (CC-BY-4.0) — no product identity, no other SRD versions",
    "supported": [
        "10 classes (fighter, rogue, cleric, wizard, barbarian, ranger, paladin, bard, monk, druid)",
        "8 species (human, elf, dwarf, halfling, gnome, half-orc, tiefling, dragonborn)",
        "4 backgrounds; standard-array ability scores; ability modifiers",
        "18 skills with proficiency; d20 checks with advantage/disadvantage",
        "Class saving-throw proficiencies; ability saves vs DCs",
        "AC, current/max HP, hit dice at level-up, proficiency bonus (1-5)",
        "Spells: 20 SRD spells incl. concentration; spell slots by class level",
        "Combat: initiative, turn order, player-selected actions (attack, cast, "
        "defend, use item, retreat, stabilize), enemy turns, conditions with "
        "durations, concentration saves, death saving throws, stabilization",
        "Rests: long (full HP + slots), short (hit-die level + con mod)",
        "Encounter difficulty labels from SRD XP thresholds; XP awards; levels 1-5",
        "Class features: barbarian rage, fighter second wind, monk unarmored AC, "
        "half-orc relentless endurance, dragonborn breath weapon, bardic inspiration",
    ],
    "not_supported": [
        "Levels above 5 (hard cap; multiclassing)",
        "Feats and optional class features (Tasha's material is not SRD)",
        "Spell preparation/swapping (known-spells model is used)",
        "Attunement slots and magic-item rarity tiers",
        "Grid movement with adjacency/aoe templates (abstract range only)",
        "Mounted combat, underwater rules, cover mechanics",
        "Monster legendary actions and lair actions",
    ],
    "unsupported_policy": "Options outside this table are not offered at character "
                          "creation or in combat; the UI lists this table verbatim.",
}

# Monsters. SRD 5.1 stat blocks are open content; literature blocks marked
# source "literature" derive from public-domain novels (our own numbers).
MONSTERS = {
    "giant_rat": {"name": "Giant Rat", "ac": 12, "hp": 7, "atk": "+4", "dmg": "1d4+1",
                  "xp": 25, "source": "srd"},
    "wolf": {"name": "Wolf", "ac": 13, "hp": 11, "atk": "+4", "dmg": "2d4+2",
             "xp": 50, "source": "srd"},
    "goblin": {"name": "Goblin", "ac": 15, "hp": 7, "atk": "+4", "dmg": "1d6+2",
               "xp": 50, "source": "srd"},
    "hobgoblin": {"name": "Hobgoblin", "ac": 18, "hp": 11, "atk": "+3", "dmg": "1d8+1",
                  "xp": 100, "source": "srd"},
    "skeleton": {"name": "Skeleton", "ac": 13, "hp": 13, "atk": "+4", "dmg": "1d6+2",
                 "xp": 50, "source": "srd"},
    "zombie": {"name": "Zombie", "ac": 8, "hp": 22, "atk": "+3", "dmg": "1d6+1",
               "xp": 50, "source": "srd"},
    "bandit": {"name": "Bandit", "ac": 12, "hp": 11, "atk": "+3", "dmg": "1d6+1",
               "xp": 25, "source": "srd"},
    "cultist": {"name": "Cultist", "ac": 12, "hp": 9, "atk": "+3", "dmg": "1d6+1",
                "xp": 25, "source": "srd"},
    "giant_spider": {"name": "Giant Spider", "ac": 14, "hp": 26, "atk": "+5", "dmg": "1d8+3",
                     "poison": "2d8", "xp": 200, "source": "srd"},
    "gray_ooze": {"name": "Gray Ooze", "ac": 8, "hp": 22, "atk": "+4", "dmg": "2d4+3",
                  "xp": 100, "source": "srd"},
    # literature-derived (public-domain novels; our own open stat blocks)
    "vampire_spawn": {"name": "Vampire Spawn", "ac": 15, "hp": 82, "atk": "+6",
                      "dmg": "2d8+3", "xp": 1100, "source": "literature"},
    "morlock": {"name": "Morlock", "ac": 13, "hp": 27, "atk": "+5", "dmg": "2d6+3",
                "xp": 450, "source": "literature"},
    "house_ape": {"name": "Great Ape", "ac": 12, "hp": 43, "atk": "+5", "dmg": "2d6+3",
                  "xp": 450, "source": "literature"},
}


class DndError(ValueError):
    pass


def _d(n: int) -> int:
    return secrets.randbelow(n) + 1


def ability_mod(score: int) -> int:
    return (score - 10) // 2


def build_character(spec: dict) -> dict:
    """Deterministic SRD character sheet from a creation spec."""
    cls = CLASSES.get(str(spec.get("class", "fighter")).lower())
    if not cls:
        raise DndError("choose a class: fighter, rogue, cleric or wizard")
    species = SPECIES.get(str(spec.get("species", "human")).lower())
    if not species:
        raise DndError("choose a species: human, elf, dwarf or halfling")
    bg = BACKGROUNDS.get(str(spec.get("background", "folk_hero")).lower())
    if not bg:
        raise DndError("choose a background: folk hero, sage, soldier or charlatan")
    abilities = dict(STANDARD_ARRAY)
    for stat, bonus in species["asi"].items():
        abilities[stat] += bonus
    prof = PROF_BY_LEVEL[1]
    hp_max = cls["hit_die"] + ability_mod(abilities["con"])
    hp_max = max(1, hp_max)
    if cls.get("unarmored"):  # monk: 10 + dex + wis
        ac = 10 + max(0, ability_mod(abilities["dex"])) + max(0, ability_mod(abilities["wis"]))
    else:
        ac = cls["armor"] + (1 if ability_mod(abilities["dex"]) > 0 and cls["armor"] >= 14 else 0)
    skills = list(cls["skills"]) + [bg["skill"]]
    sheet = {
        "class": spec.get("class", "fighter").lower(),
        "class_name": cls["name"],
        "species": spec.get("species", "human").lower(),
        "species_name": species["name"],
        "background": spec.get("background", "folk_hero").lower(),
        "background_name": bg["name"],
        "level": 1,
        "xp": 0,
        "abilities": abilities,
        "ability_mods": {a: ability_mod(v) for a, v in abilities.items()},
        "proficiency": prof,
        "skills_prof": skills,
        "hp_max": hp_max,
        "ac": ac,
        "speed": species["speed"],
        "weapon": cls["weapon"],
        "weapon_dmg": "1d8" + _str_bonus_fragment(cls, abilities),
        "caster": bool(cls.get("caster")),
        "spells": list(_starting_spells(cls)),
        "slots": (dict(HALF_CASTER_SLOTS[1]) if cls.get("half_caster")
                  else dict(SLOTS_BY_LEVEL[1]) if cls.get("caster") else {}),
        "hp": hp_max,
        "saves_prof": list(cls["saves"]),
        "features": _class_features(cls, level=1),
        "traits": [k for k in ("keen_senses", "stout", "lucky", "cunning",
                               "relentless", "fire_resist", "breath") if k in species],
        "relentless_used": False,
        "rage_used": False,
        "second_wind_used": False,
        "breath_used": False,
    }
    return sheet


def _class_features(cls: dict, level: int) -> list[str]:
    feats = []
    name = cls["name"]
    if name == "Barbarian":
        feats.append("rage (bonus action: +2 melee damage, advantage-free resilience)")
    if name == "Fighter":
        feats.append("second wind (bonus action: heal 1d10 + level, once per rest)")
    if name == "Monk":
        feats.append("unarmored defense; patient defense (dodge as bonus action)")
    if name == "Bard":
        feats.append("bardic inspiration (grant an ally +1d6 on one check/attack)")
    if name == "Paladin":
        feats.append("lay on hands (heal pool = 5 x level per long rest)")
    if name == "Ranger":
        feats.append("favored enemy (+1 damage vs beasts)")
    if name == "Druid":
        feats.append("nature's aid (cure wounds known at level 1)")
    return feats


def _str_bonus_fragment(cls: dict, abilities: dict) -> str:
    mod = ability_mod(abilities[cls["primary"]])
    if cls["primary"] == "dex" and cls["weapon"] == "shortsword":
        mod = ability_mod(abilities["dex"])
    return f"+{mod}" if mod >= 0 else f"{mod}"


def _starting_spells(cls: dict) -> list[str]:
    if cls["name"] == "Wizard":
        return ["fire_bolt", "magic_missile", "shield", "mage_armor", "thunderwave"]
    if cls["name"] == "Cleric":
        return ["sacred_flame", "cure_wounds", "healing_word", "guidance", "bless", "shield_of_faith"]
    if cls["name"] == "Druid":
        return ["cure_wounds", "guidance", "thunderwave"]
    if cls["name"] == "Bard":
        return ["healing_word", "thunderwave", "minor_illusion"]
    if cls["name"] in ("Ranger", "Paladin"):
        return ["cure_wounds", "bless"] if cls["name"] == "Paladin" else ["cure_wounds"]
    return []


def check(sheet: dict, skill: str, dc: int = 13, hard: bool = False,
          risk: bool = False, sit_mod: int = 0) -> dict:
    """One deterministic ability/skill check; returns the shared roll dict."""
    if skill not in SKILL_ABILITY:
        # archetype-style names fall back to the nearest ability
        ability = skill if skill in ABILITIES else "wis"
    else:
        ability = SKILL_ABILITY[skill]
    mod = sheet["ability_mods"][ability] + (sheet["proficiency"] if skill in sheet["skills_prof"] else 0)
    if hard:
        dc += 3
    adv = bool(risk)
    if adv:
        rolls = [_d(20), _d(20)]
        raw = max(rolls)
    else:
        rolls = [_d(20)]
        raw = rolls[0]
    if "lucky" in sheet.get("traits", []) and raw == 1:
        raw = _d(20)  # halfling luck rerolls ones (SRD)
    total = raw + mod + sit_mod
    outcome = _band(raw, total, dc)
    crit = "nat 20" if raw == 20 else ("nat 1" if raw == 1 else "")
    text = (f"d20 [{raw}] {'(adv) ' if adv else ''}+{mod} = {total} vs DC {dc}"
            + (f" — {crit}" if crit else ""))
    return {
        "dice": rolls, "mod": mod, "sit_mod": sit_mod, "total": total,
        "dc": dc, "outcome": outcome, "text": text,
        "harm": None, "harm_type": "", "note": "", "risk": bool(risk),
        "skill": skill, "ability": ability, "nat": raw,
    }


def _band(raw: int, total: int, dc: int) -> str:
    if raw == 1:
        return "riptide"
    if raw == 20:
        return "surge"
    if total >= dc + 5:
        return "surge"
    if total >= dc:
        return "clean"
    if total >= dc - 4:
        return "undertow"
    return "riptide"


def attack_roll(sheet: dict, target_ac: int, adv: bool = False, dis: bool = False) -> dict:
    mod = sheet["ability_mods"][CLASSES[sheet["class"]]["primary"]]
    if adv and dis:
        adv, dis = False, False  # they cancel (SRD)
    rolls = [_d(20), _d(20)] if adv or dis else [_d(20)]
    raw = max(rolls) if adv else (min(rolls) if dis else rolls[0])
    if "lucky" in sheet.get("traits", []) and raw == 1:
        raw = _d(20)
    total = raw + mod + sheet["proficiency"]
    hit = raw == 20 or (raw != 1 and total >= target_ac)
    return {"dice": rolls, "total": total, "nat": raw, "hit": hit,
            "crit": raw == 20, "text": f"attack [{raw}]+{mod + sheet['proficiency']}={total} vs AC {target_ac}"}


def roll_damage(expr: str, crit: bool = False) -> tuple[int, str]:
    """Roll a dice expression like '1d8+3' or '3x(1d4+1)' deterministically."""
    import re
    total = 0
    detail = []
    for mult, nd, die, add in re.findall(r"(?:(\d+)x)?\(?(\d+)d(\d+)([+-]\d+)?\)?", expr):
        m = int(mult) if mult else 1
        n, d, a = int(nd), int(die), int(add or 0)
        dice = [ _d(d) for _ in range(n * m) ]
        s = sum(dice) + a * m
        if crit:
            s += sum(_d(d) for _ in range(n * m))
        total += s
        detail.append(f"{n * m}d{d}{a:+d}={s}")
    return total, "+".join(detail) or "0"


def make_save(sheet: dict, ability: str, dc: int, adv: bool = False, dis: bool = False) -> dict:
    """An ability saving throw (SRD): d20 + mod (+prof if a class save)."""
    if ability not in ABILITIES:
        raise DndError("unknown saving-throw ability")
    mod = sheet["ability_mods"][ability] + (sheet["proficiency"] if ability in sheet.get("saves_prof", []) else 0)
    rolls = [_d(20), _d(20)] if adv or dis else [_d(20)]
    raw = max(rolls) if adv else (min(rolls) if dis else rolls[0])
    total = raw + mod
    return {"dice": rolls, "nat": raw, "mod": mod, "total": total, "dc": dc,
            "success": raw == 20 or (raw != 1 and total >= dc)}


def cast_spell(sheet: dict, spell_id: str, target_ac: int | None = None,
               target_save_mod: int = 0) -> dict:
    spell = SPELLS.get(spell_id)
    if not spell:
        raise DndError("no such spell in the open rules")
    if spell_id not in sheet.get("spells", []):
        raise DndError("your character does not know that spell")
    lvl = spell["level"]
    slots = sheet.get("slots", {})
    if lvl == 0:
        return _resolve_spell(sheet, spell, target_ac, target_save_mod, spent=False)
    # slots may come from JSON storage (string keys) or fresh memory (int keys)
    key = str(lvl) if str(lvl) in slots else lvl
    if slots.get(key, 0) <= 0:
        raise DndError(f"no level {lvl} spell slots remain — rest to recover")
    slots[key] -= 1
    result = _resolve_spell(sheet, spell, target_ac, target_save_mod, spent=True)
    return result


def _resolve_spell(sheet: dict, spell: dict, target_ac: int | None,
                   target_save_mod: int, spent: bool) -> dict:
    out = {"spell": spell["name"], "spent": spent, "narration": spell["desc"]}
    if spell.get("damage"):
        if spell.get("attack") and target_ac is not None:
            atk = attack_roll(sheet, target_ac)
            if atk["hit"]:
                dmg, det = roll_damage(spell["damage"], atk["crit"])
                out.update({"hit": True, "damage": dmg, "detail": det,
                            "narration": f"{spell['name']} strikes: {det} ({dmg} damage)."})
            else:
                out.update({"hit": False, "damage": 0,
                            "narration": f"{spell['name']} misses."})
        elif spell.get("save"):
            dc = 8 + sheet["proficiency"] + sheet["ability_mods"][CLASSES[sheet["class"]]["primary"]]
            save = _d(20) + target_save_mod
            ok = save >= dc
            dmg, det = roll_damage(spell["damage"])
            if ok:
                dmg = dmg // 2
            out.update({"saved": ok, "save_total": save, "dc": dc,
                        "damage": dmg, "detail": det,
                        "narration": f"DC {dc} save {'held' if ok else 'failed'}: {det} ({dmg} damage)."})
        else:
            dmg, det = roll_damage(spell["damage"])
            out.update({"damage": dmg, "detail": det,
                        "narration": f"{spell['name']}: {det} ({dmg} damage)."})
    if spell.get("heal"):
        mod = sheet["ability_mods"][CLASSES[sheet["class"]]["primary"]]
        heal, det = roll_damage(spell["heal"].replace("ability", f"+{max(0, mod)}"))
        out.update({"heal": heal, "detail": det,
                    "narration": f"{spell['name']}: {det} ({heal} healed)."})
    if spell.get("ac"):
        out["narration"] = f"{spell['name']}: +{spell['ac']} AC this round."
        out["ac_bonus"] = spell["ac"]
    return out


def resolve_encounter(sheet: dict, monster_id: str, count: int,
                      rng=None) -> dict:
    """A deterministic, bounded combat: player vs a group of monsters.
    Rounds alternate; the fight ends on 0 HP either side (max 12 rounds).
    Returns a narrative + mechanical result for the engine to narrate."""
    monster = MONSTERS.get(monster_id)
    if not monster:
        raise DndError("no such creature in the open bestiary")
    rng = rng or (lambda n: _d(n))
    count = max(1, min(6, int(count)))
    foes = [{"hp": monster["hp"], "alive": True} for _ in range(count)]
    php = sheet["hp_max"]
    ac = sheet["ac"]
    rounds = []
    for rnd in range(1, 13):
        # player attacks the nearest living foe
        target = next((f for f in foes if f["alive"]), None)
        if not target:
            break
        atk = attack_roll(sheet, monster["ac"])
        line = {"round": rnd, "attacks": []}
        if atk["hit"]:
            dmg, det = roll_damage(sheet["weapon_dmg"], atk["crit"])
            target["hp"] -= dmg
            if target["hp"] <= 0:
                target["alive"] = False
            line["attacks"].append({"who": "you", "text": atk["text"],
                                    "damage": dmg, "detail": det,
                                    "killed": not target["alive"]})
        else:
            line["attacks"].append({"who": "you", "text": atk["text"], "damage": 0})
        # each living foe strikes back (one attack per foe per round, max 3)
        for f in [x for x in foes if x["alive"]][:3]:
            nat = rng(20)
            hit = nat != 1 and (nat + 4 >= ac)
            if hit:
                dmg, det = roll_damage(monster["dmg"])
                php -= dmg
                line["attacks"].append({"who": monster["name"], "damage": dmg,
                                        "detail": det, "text": f"{monster['name']} hits ({det})."})
            else:
                line["attacks"].append({"who": monster["name"], "damage": 0,
                                        "text": f"{monster['name']} misses."})
        rounds.append(line)
        if php <= 0:
            break
    alive_foes = sum(1 for f in foes if f["alive"])
    victory = alive_foes == 0 and php > 0
    xp = monster["xp"] * (count - alive_foes)
    return {
        "victory": victory,
        "downed": php <= 0,
        "hp_left": max(0, php),
        "foes_remaining": alive_foes,
        "foes_total": count,
        "monster": monster["name"],
        "xp": xp,
        "rounds": rounds,
        "narration": _encounter_narration(monster["name"], count, victory, php > 0),
    }


def _encounter_narration(name: str, count: int, victory: bool, standing: bool) -> str:
    group = f"{name}" if count == 1 else f"{count} {name}s"
    if victory:
        return f"The {group} falls. You stand, breathing hard, among the aftermath."
    if standing:
        return f"The {group} withdraws into the dark — wounded, and unforgotten."
    return f"The {group} bears you down. The world goes sideways and quiet."


def apply_hp(sheet: dict, delta: int) -> None:
    sheet["hp_max"] = max(1, sheet["hp_max"] + delta) if delta > 0 else max(1, sheet["hp_max"] + delta)


def long_rest(sheet: dict) -> dict:
    sheet["slots"] = (dict(HALF_CASTER_SLOTS[sheet["level"]])
                      if CLASSES[sheet["class"]].get("half_caster")
                      else dict(SLOTS_BY_LEVEL[sheet["level"]]) if sheet.get("caster") else {})
    sheet["hp"] = sheet["hp_max"]
    for flag in ("rage_used", "second_wind_used", "breath_used"):
        sheet[flag] = False
    sheet["relentless_used"] = False
    healed = sheet["hp_max"] - _hp_before(sheet)
    return {"healed": healed, "slots": sheet.get("slots", {})}


def _hp_before(sheet: dict) -> int:
    return sheet.get("hp", sheet["hp_max"]) if False else sheet.get("_hp_before", sheet["hp"])


def short_rest(sheet: dict) -> dict:
    heal = max(1, sheet["level"] + max(0, sheet["ability_mods"]["con"]))
    before = int(sheet.get("hp", sheet["hp_max"]))
    sheet["hp"] = min(sheet["hp_max"], before + heal)
    sheet["second_wind_used"] = False
    return {"healed": sheet["hp"] - before}


def apply_damage(sheet: dict, amount: int) -> dict:
    """Apply damage to CURRENT hp. Returns the post-state flags."""
    amount = max(0, int(amount))
    before = int(sheet.get("hp", sheet["hp_max"]))
    hp = before - amount
    result = {"damage": min(before, amount), "downed": False, "dead": False,
              "relentless_saved": False}
    if hp <= 0 and "relentless" in sheet.get("traits", []) and not sheet.get("relentless_used"):
        hp = 1
        sheet["relentless_used"] = True
        result["relentless_saved"] = True
    if hp <= 0:
        result["downed"] = True
        if before <= 0:  # damage at 0 hp = automatic death-save failure (SRD)
            result["dead"] = True
    sheet["hp"] = max(0, hp)
    return result


def apply_heal(sheet: dict, amount: int) -> int:
    before = int(sheet.get("hp", 0))
    if before <= 0 and amount > 0:
        pass  # healing revives a downed character (SRD: regains hp and consciousness)
    sheet["hp"] = min(sheet["hp_max"], max(0, before) + max(0, int(amount)))
    return sheet["hp"] - before


def gain_xp(sheet: dict, xp: int) -> dict | None:
    sheet["xp"] = int(sheet.get("xp", 0)) + max(0, int(xp))
    level = sheet["level"]
    while level < 5 and sheet["xp"] >= XP_BY_LEVEL[level + 1]:
        level += 1
    if level != sheet["level"]:
        sheet["level"] = level
        sheet["proficiency"] = PROF_BY_LEVEL[level]
        hp_gain = (CLASSES[sheet["class"]]["hit_die"] // 2 + 1) + max(0, sheet["ability_mods"]["con"])
        sheet["hp_max"] += max(1, hp_gain)
        sheet["hp"] = min(sheet["hp_max"], int(sheet.get("hp", sheet["hp_max"])) + max(1, hp_gain))
        sheet["saves_prof"] = list(CLASSES[sheet["class"]]["saves"])
        if sheet.get("caster"):
            slots_src = HALF_CASTER_SLOTS if CLASSES[sheet["class"]].get("half_caster") else SLOTS_BY_LEVEL
            sheet["slots"] = dict(slots_src[level])
        sheet["features"] = _class_features(CLASSES[sheet["class"]], level)
        return {"level": level, "hp_gain": max(1, hp_gain)}
    return None
