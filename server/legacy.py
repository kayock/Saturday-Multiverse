"""Saturday Multiverse — legacy systems module (Milestones 1.5, 2.0, 2.5).

Everything here is engine-owned and deterministic. The AI may narrate what
these systems produce but never decides them:

- GM personalities (style packs: prompt tone + fallback voices)
- tide clock, wash-ashore events (reproducible via seed hash)
- NPC structured memories and grounded, scoped gossip
- seeded worlds: generation registry, visits, persistent world state
- shore improvements: the glassbead economy and its catalog
- the player-controlled omen hand (draw/play under strict rules)
- echoes: endings become profile-level legacy; new campaigns weave them in
- cross-world consequences and foreshadowing clue threads with payoffs
- the Memory Ledger (structured view for the visual journal)
"""
from __future__ import annotations

import hashlib
import secrets

from . import ai, db, gen, rules, worldpacks
from .db import jdumps, jloads, new_id, utcnow

# ==========================================================================
# GM personalities
# ==========================================================================

GM_STYLES = {
    "classic": {
        "label": "Classic Fantasy",
        "prompt": (
            "Tone: warm classic fantasy. Vivid but grounded prose; noble melancholy; "
            "wonder undercut by weather. Speak of the sea as an old witness."
        ),
        "flavor": [
            "Lantern light steadies itself around you.",
            "The old magic in the dunes stirs without waking.",
            "A distant horn answers nothing, kindly.",
        ],
        "outcomes": {
            "surge": "The moment breaks your way like weather clearing — more than you dared arrange.",
            "clean": "It goes exactly as you meant it to.",
            "riptide": "You manage it, but the sea clips a coin from your purse on the way through.",
            "undertow": "The current takes hold of your plan and rearranges it.",
            "wipeout": "It goes wrong the way storms do: thoroughly, and with commentary.",
        },
    },
    "grimdark": {
        "label": "Grimdark",
        "prompt": (
            "Tone: grimdark. Cold, close detail; moral weight in every convenience; "
            "beauty that costs. Successes feel borrowed; failures feel earned."
        ),
        "flavor": [
            "Something rots sweetly beneath the salt.",
            "The dark here has chewed on better people.",
            "Kindness is a currency and you are poor tonight.",
        ],
        "outcomes": {
            "surge": "You win. It tastes like copper and everyone saw how.",
            "clean": "It works. That is not the same as it being fine.",
            "riptide": "You get through. You leave something of yourself in the gap.",
            "undertow": "It fails, and the failure has your name on it now.",
            "wipeout": "It collapses — and takes a piece of you with it as toll.",
        },
    },
    "cosmic": {
        "label": "Cosmic Horror",
        "prompt": (
            "Tone: cosmic horror. Vast, indifferent patterns glimpsed at the corner of "
            "understanding; geometry that apologizes; dread without cruelty. Never explain."
        ),
        "flavor": [
            "The stars are arranged, tonight, with intent.",
            "Your reflection lags by a decision.",
            "The tide obeys something older than the moon.",
        ],
        "outcomes": {
            "surge": "For one moment the pattern makes sense, and the mercy of that is worse than the pattern.",
            "clean": "It holds. Nothing acknowledges this, which is its own answer.",
            "riptide": "You succeed, and something adjusts to accommodate the success.",
            "undertow": "The current is not water. It notices you back.",
            "wipeout": "It comes apart — and behind it, briefly, is the thing the pattern was avoiding.",
        },
    },
    "noir": {
        "label": "Noir",
        "prompt": (
            "Tone: noir. Short sentences. Wet streets, owed favors, everyone guilty of "
            "something small. The narration keeps its coat on and its heart shut."
        ),
        "flavor": [
            "The fog works nights here, same as everyone.",
            "Somebody's lying. Statistically, everybody.",
            "The lamp overhead buzzes like a bad alibi.",
        ],
        "outcomes": {
            "surge": "A clean job. In this town that's a miracle with paperwork.",
            "clean": "It plays out the way you called it. Don't get used to it.",
            "riptide": "You get the goods. You also get a tail you didn't order.",
            "undertow": "The plan takes a dive off the pier.",
            "wipeout": "It goes bad in every direction at once. Even the rain is disappointed.",
        },
    },
    "whimsical": {
        "label": "Whimsical",
        "prompt": (
            "Tone: whimsical. Gentle absurdity, earnest odd animals, doors with opinions. "
            "The dread stays decorative; the heart stays sincere."
        ),
        "flavor": [
            "A crab philosophizes past your boots.",
            "The wind smells faintly of bedtime.",
            "A door politely clears its hinges.",
        ],
        "outcomes": {
            "surge": "It works so well that a small parade breaks out. Attendance: two gulls and a door.",
            "clean": "It goes right! Everyone pretends this is normal. The door curtsies.",
            "riptide": "You manage it, minus one sock, which the sea keeps for reasons.",
            "undertow": "It goes sideways, charmingly, like a cart with a mind of its own.",
            "wipeout": "Oh dear. It all goes wrong in an educational way.",
        },
    },
    "mythic": {
        "label": "Mythic",
        "prompt": (
            "Tone: mythic. Weight and lineage in every gesture; the personal inside the "
            "archetypal; rivers remember names. Long vowels, short mercies."
        ),
        "flavor": [
            "The shore remembers the first foot that ever broke it.",
            "Somewhere, a story is deciding you are in it.",
            "The beam above is older than the word for light.",
        ],
        "outcomes": {
            "surge": "It is done as deeds are done when songs decide to keep them.",
            "clean": "Your hand did not shake. The telling will say it never does.",
            "riptide": "You pass, and the passing is paid for; all crossings are.",
            "undertow": "The old current takes its due, as it has since before names.",
            "wipeout": "The hour turns against you as hours once turned against kings.",
        },
    },
}


def normalize_style(state: dict) -> dict:
    """Return the effective GM style for a campaign (defaults to classic)."""
    cfg = state.get("gm_style") or {}
    sid = cfg.get("id") if cfg.get("id") in GM_STYLES else "classic"
    if sid == "custom":
        return {
            "id": "custom",
            "label": "Custom",
            "prompt": f"Tone (player-authored): {str(cfg.get('custom_text', ''))[:400]}",
            "flavor": [],
            "outcomes": {},
        }
    style = dict(GM_STYLES[sid])
    style["id"] = sid
    return style


def set_style(cid: str, style_id: str, custom_text: str = "") -> dict:
    if style_id not in (*GM_STYLES.keys(), "custom"):
        raise ValueError("unknown GM style")
    custom_text = str(custom_text or "").strip()[:400]
    if style_id == "custom" and not custom_text:
        raise ValueError("a custom style needs a tone description")
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    state["gm_style"] = {"id": style_id, "custom_text": custom_text}
    db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
               (jdumps(state), utcnow(), cid))
    db.log_event(cid, "gm_style", {"style": style_id})
    return {"style_id": style_id, "label": "Custom" if style_id == "custom" else GM_STYLES[style_id]["label"]}


# ==========================================================================
# Tide clock & wash-ashore
# ==========================================================================

TIDE_CYCLE = 12
TIDE_LOW_FROM = 6


def tide_phase(drift: int) -> dict:
    pos = drift % TIDE_CYCLE
    low = pos >= TIDE_LOW_FROM
    cycle_pos = pos - TIDE_LOW_FROM if low else pos
    span = TIDE_CYCLE - TIDE_LOW_FROM if low else TIDE_LOW_FROM
    return {
        "tide": "low" if low else "high",
        "beats_to_change": span - cycle_pos,
        "progress": round(cycle_pos / span, 3),
    }


WASH_DEFAULTS = [
    {"id": "glass_beads", "kind": "beads", "label": "a scatter of glassbeads",
     "text": "Sea-glass beads, polished by the Beam, pooled in a drag-mark. The shore pays for attention.",
     "effects": {"beads": 2}, "weight": 3},
    {"id": "brine_script", "kind": "clue", "label": "a brine-scripted plank",
     "text": "A plank scored with brine-script: the same mark the lighthouse keeper logged. Thread of the ninth wave.",
     "effects": {"clue": {"thread_id": "ninth_wave", "text": "Brine-script plank: the ninth wave is counted, not awaited."}}, "weight": 2},
    {"id": "drift_flotsam", "kind": "item", "label": "a useful bit of flotsam",
     "text": "A sealed Bundle: dried kelp and a storm-lantern, lashed by careful hands.",
     "effects": {"item_give": [{"item_id": "dried_kelp", "qty": 1}, {"item_id": "storm_lantern", "qty": 1}]}, "weight": 2},
    {"id": "salt_charm_wash", "kind": "item", "label": "a salt-charm knot",
     "text": "A fresh salt-charm, still warm, tied by no one you can see.",
     "effects": {"item_give": [{"item_id": "salt_charm", "qty": 1}]}, "weight": 2},
    {"id": "wrong_gull_wash", "kind": "clue", "label": "a gull feather, wrong way round",
     "text": "A white feather whose shadow wears a hat. The wrong gull is counting things ashore.",
     "effects": {"clue": {"thread_id": "wrong_gull", "text": "Wash-ashore feather: the wrong gull is counting things on the shore."}}, "weight": 1},
]


def _hash_pair(cid: str, drift: int) -> bytes:
    return hashlib.sha256(f"{cid}|{drift}".encode()).digest()


def check_washashore(cid: str, pack: dict) -> dict | None:
    """Deterministic wash-ashore scheduling: appears on drift beats 4 and 11
    of each tide cycle if the beach is empty. Chosen by hash, not RNG, so a
    given campaign/drift always yields the same find."""
    row = db.query_one("SELECT drift, state_json FROM campaigns WHERE id=?", (cid,))
    state = jloads(row["state_json"], {})
    if state.get("washashore"):
        return state["washashore"]
    drift = row["drift"]
    pos = drift % TIDE_CYCLE
    if pos not in (4, 11) and drift > 0:
        return None
    if state.get("washashore_last_drift") == drift:
        return None  # this beat already gave something; never farm one beat
    table = [w for w in (pack.get("washashore") or WASH_DEFAULTS) if isinstance(w, dict) and w.get("kind")]
    if not table:
        return None
    code = _hash_pair(cid, drift)
    if code[0] % 100 >= 55:   # roughly half the eligible beats, reproducibly
        return None
    total = sum(w.get("weight", 1) for w in table)
    pick = code[1] % total
    obj = None
    for w in table:
        pick -= w.get("weight", 1)
        if pick < 0:
            obj = w
            break
    if not obj:
        return None
    state["washashore"] = {"def_id": obj["id"], "label": obj["label"], "text": obj["text"],
                           "kind": obj["kind"], "effects": obj.get("effects", {})}
    state["washashore_last_drift"] = drift
    db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
               (jdumps(state), utcnow(), cid))
    return state["washashore"]


def pick_washashore(cid: str, pack: dict, chid: str | None = None) -> dict:
    """Collect the thing on the beach. Exactly once (guarded), engine-applied."""
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    obj = state.get("washashore")
    if not obj:
        raise ValueError("the sand is bare")
    changes: list[str] = []
    from . import gm as _gm
    _gm.apply_effects(cid, pack, obj.get("effects", {}), changes, chid)
    remember(cid, "all", "discovery", f"Found {obj['label']} on the beach.")
    if obj.get("kind") == "clue":
        changes.append("A thread tightens.")
    state["washashore"] = None
    db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
               (jdumps(state), utcnow(), cid))
    db.log_event(cid, "washashore_picked", {"def_id": obj.get("def_id")})
    return {"narration": obj.get("text", "You gather it."), "changes": changes, "label": obj["label"]}


# ==========================================================================
# NPC structured memory & gossip
# ==========================================================================

SCOPE_MAP = {
    # npc_id -> which memory scopes it can hear
    "old_cardo": {"all", "camp", "doors"},
    "maren": {"all", "tavern"},
    "drowned_lampkeeper": {"all", "deep"},
}


def remember(cid: str, scope: str, kind: str, text: str) -> None:
    """Record a durable event into the NPC memory pool (engine-side only)."""
    db.execute(
        "INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
        " VALUES (?,?,?,?,?,?,?)",
        (new_id("mem"), cid, "*", utcnow(), kind[:20], scope[:20], text[:400]),
    )


def _memories_for(cid: str, npc_id: str, limit: int = 8) -> list[dict]:
    scopes = SCOPE_MAP.get(npc_id, {"all"})
    placeholders = ",".join("?" * len(scopes))
    rows = db.query(
        f"SELECT ts, kind, scope, text FROM npc_memories WHERE campaign_id=? "
        f"AND scope IN ({placeholders}) ORDER BY rowid DESC LIMIT ?",
        (cid, *scopes, limit),
    )
    return [dict(r) for r in reversed(rows)]


def _gossip_lines(cid: str, pack: dict, npc: dict, topic: str, memories: list[dict],
                  rel: int, state: dict, consequences: list[str]) -> list[str]:
    """Deterministic gossip lines, grounded in records. The AI may enrich
    these later; this fallback is the honest floor."""
    name = npc["name"]
    lines: list[str] = [npc.get("greeting", f"{name} looks up.")]
    topic_new = [m["text"] for m in memories if m["kind"] in ("event", "ending", "discovery")][:2]
    topic_mystery = [m["text"] for m in memories if m["kind"] == "mystery"][:1]
    rumors = npc.get("rumors", [])

    if topic == "rumors" and rumors:
        lines.append(secrets.choice(rumors))
    elif topic == "what's new" and topic_new:
        for t in topic_new:
            lines.append(f"\"{t}\" {name} says, like it happened nearer than it did.")
    elif topic == "the shore":
        drift_row = db.query_one("SELECT drift FROM campaigns WHERE id=?", (cid,))
        lines.append("\"Tide's " + tide_phase(int(drift_row["drift"]))["tide"]
                     + ". The shore keeps better time than people do.\"")
        if consequences:
            lines.append(f"\"{consequences[0]}\"")
    elif topic_mystery:
        lines.append(f"\"{topic_mystery[0]}\" A shrug. \"That one doesn't close.\"")
    else:
        if memories:
            lines.append(f"\"{memories[-1]['text']}\"")
        elif rumors:
            lines.append(secrets.choice(rumors))
        else:
            lines.append(f"\"{name} says little. The little is true.\"")

    if rel >= 3:
        lines.append("\"Good to see you again, friend.\" The warmth is specific.")
    elif rel <= -2:
        lines.append("A pause that is not quite friendly.")
    if state.get("gull_friend") and npc.get("id") == "old_cardo":
        lines.append("\"Your gull told me you were coming. Thing's useful.\"")
    return lines[:6]


def talk(cid: str, npc_id: str, topic: str = "the shore") -> dict:
    """Talk to a shore NPC. Grounded in npc_memories + records; AI enriches."""
    campaign = db.query_one("SELECT * FROM campaigns WHERE id=? AND status='active'", (cid,))
    if not campaign:
        raise ValueError("campaign not found")
    pack = worldpacks.load_pack(campaign["pack_id"])
    npc = worldpacks.get_npc(pack, npc_id)
    if not npc:
        raise ValueError("no such soul on this shore")
    # allow talking only where the NPC plausibly is
    if npc.get("location") and campaign["location_id"] != npc["location"]:
        raise ValueError(f"{npc['name']} is not here.")

    row = db.query_one("SELECT data_json FROM npcs WHERE campaign_id=? AND npc_id=?", (cid, npc_id))
    rel = jloads(row["data_json"], {}).get("rel", 0) if row else 0
    state = jloads(campaign["state_json"], {})
    memories = _memories_for(cid, npc_id)
    cons = [c["summary"] for c in recent_consequences(cid, 3)]
    lines = _gossip_lines(cid, pack, npc, (topic or "the shore").lower(), memories, rel, state, cons)

    meta = {"ai_used": False}
    if ai.get_ai_config().get("enabled"):
        try:
            ch = _gm_char(cid)
            sys_p = _gm_style_system(pack, ch, campaign, state, 120)
            mem_text = " | ".join(f"[{m['kind']}] {m['text']}" for m in memories) or "none"
            user_p = (
                f"You are {npc['name']} ({npc.get('role', '')}). Personality: {_trim(npc.get('desc', ''), 200)}. "
                f"The player asks about: {topic}. Ground each line in these records, stay in character, 2-4 short spoken lines:\n"
                f"RECORDS: {mem_text}\n"
                f"DETERMINISTIC DRAFT (you may polish, never contradict): {json_dumps_lines(lines)}\n"
                f"Respond ONLY with the JSON contract; put the spoken lines in npc_lines."
            )
            text, _m = ai.chat([{"role": "system", "content": sys_p},
                                {"role": "user", "content": user_p}], ai.get_ai_config())
            data = ai.extract_json(text)
            got = data.get("npc_lines") if isinstance(data, dict) else None
            if isinstance(got, list) and got:
                lines = [str(l.get("line", l))[:240] if isinstance(l, dict) else str(l)[:240]
                         for l in got][:5]
                meta = {"ai_used": True, "model": _m.get("model")}
        except ai.AiError:
            pass

    db.add_transcript(cid, "player", f"[talked to {npc['name']} about {topic}]")
    db.add_transcript(cid, "gm", "\n".join(lines), {"npc_id": npc_id, "topic": topic, **meta})
    _npc_meet(cid, npc_id, npc["name"])
    db.log_event(cid, "npc_talk", {"npc_id": npc_id, "topic": topic})
    return {"npc": {"id": npc_id, "name": npc["name"], "role": npc.get("role", ""), "rel": rel},
            "lines": lines, "memories": memories, "meta": meta}


def _npc_meet(cid: str, npc_id: str, name: str) -> None:
    row = db.query_one("SELECT id FROM npcs WHERE campaign_id=? AND npc_id=?", (cid, npc_id))
    if not row:
        db.execute(
            "INSERT INTO npcs (id, campaign_id, npc_id, name, data_json) VALUES (?,?,?,?,?)",
            (new_id("npc"), cid, npc_id, name, jdumps({"rel": 0, "facts": [], "met": True})),
        )


def record_event_memories(cid: str, kind: str, scope: str, text: str) -> None:
    remember(cid, scope, kind, text)


def json_dumps_lines(lines: list[str]) -> str:
    return jdumps(lines)


def _trim(text: str, n: int) -> str:
    return (text or "").strip()[:n]


def _gm_char(cid: str, chid: str | None = None):
    from . import gm as _gm
    return _gm.get_character(cid, chid)


def _gm_get_character(cid: str, chid: str | None = None):
    from . import gm as _gm
    return _gm.get_character(cid, chid)


def gm_ch_get(ch: dict, key: str, default=None):
    from . import gm as _gm
    return _gm.ch_get(ch, key, default)


def gm_ch_set(ch: dict, key: str, value) -> None:
    from . import gm as _gm
    _gm.ch_set(ch, key, value)


def _gm_persist(ch: dict) -> None:
    from . import gm as _gm
    _gm._persist_character(ch)


def _gm_style_system(pack: dict, ch: dict, campaign: dict, state: dict, words: int) -> str:
    from . import gm as _gm
    return _gm.build_system_prompt(pack, ch, campaign, state, words)


# ==========================================================================
# Seeded worlds (M2.0)
# ==========================================================================

def generate_and_store(cid: str, seed: str) -> dict:
    campaign = db.query_one("SELECT * FROM campaigns WHERE id=? AND status='active'", (cid,))
    if not campaign:
        raise ValueError("campaign not found")
    norm = gen.normalize_seed(seed)
    if not norm:
        raise ValueError("whisper an actual seed — a word or short phrase")
    wid = gen.world_id(norm)
    existing = db.query_one("SELECT * FROM worlds WHERE campaign_id=? AND seed_hash=?",
                            (cid, gen.seed_hash(norm)))
    if existing:
        w = dict(existing)
        w["identity"] = jloads(w.pop("identity_json"), {})
        w["state"] = jloads(w.pop("state_json"), {})
        w["existing"] = True
        return w
    identity = gen.generate_world(norm)
    ts = utcnow()
    db.execute(
        "INSERT INTO worlds (id, campaign_id, seed, seed_hash, generator_version, name,"
        " identity_json, state_json, discovered_at, visits) VALUES (?,?,?,?,?,?,?,?,?,0)",
        (wid, cid, norm, identity["seed_hash"], gen.GEN_VERSION, identity["name"],
         jdumps(identity), "{}", ts),
    )
    db.log_event(cid, "world_generated", {"world_id": wid, "seed": norm,
                                          "generator": gen.GEN_VERSION})
    remember(cid, "all", "discovery", f"An unstable door opened on {identity['name']}.")
    register_consequence(cid, f"world_discovered:{identity['archetype']}",
                         f"A door on the Beam now opens on {identity['name']}.",
                         {"world_id": wid})
    return {"id": wid, "identity": identity, "state": {}, "seed": norm, "name": identity["name"],
            "existing": False}


def list_worlds(cid: str) -> list[dict]:
    rows = db.query(
        "SELECT id, seed, name, discovered_at, visits, state_json, identity_json"
        " FROM worlds WHERE campaign_id=? ORDER BY discovered_at",
        (cid,),
    )
    out = []
    for r in rows:
        ident = jloads(r["identity_json"], {})
        out.append({
            "id": r["id"], "seed": r["seed"], "name": r["name"],
            "archetype": ident.get("archetype_label", ""),
            "visits": r["visits"], "discovered_at": r["discovered_at"],
            "state": jloads(r["state_json"], {}),
            "tint": ident.get("tint", 0), "vignette": ident.get("vignette", "saltgrave"),
            "hooks": ident.get("hooks", []),
        })
    return out


def get_world(cid: str, world_id: str) -> dict | None:
    row = db.query_one("SELECT * FROM worlds WHERE campaign_id=? AND id=?", (cid, world_id))
    if not row:
        return None
    w = dict(row)
    w["identity"] = jloads(w.pop("identity_json"), {})
    w["state"] = jloads(w.pop("state_json"), {})
    return w


def find_world_by_location(cid: str, location_id: str) -> dict | None:
    """Resolve which generated world owns a location id (w<hash6>_...)."""
    for w in db.query("SELECT * FROM worlds WHERE campaign_id=?", (cid,)):
        ident = jloads(w["identity_json"], {})
        for loc in ident.get("locations", []):
            if loc["id"] == location_id:
                d = dict(w)
                d["identity"] = ident
                d["state"] = jloads(d.pop("state_json"), {})
                d.pop("identity_json", None)
                return d
    return None


def note_world_visit(cid: str, world_id: str) -> None:
    db.execute("UPDATE worlds SET visits=visits+1 WHERE campaign_id=? AND id=?", (cid, world_id))


def world_state(cid: str, world_id: str) -> dict:
    row = db.query_one("SELECT state_json FROM worlds WHERE campaign_id=? AND id=?", (cid, world_id))
    return jloads(row["state_json"], {}) if row else {}


def set_world_state(cid: str, world_id: str, mutator) -> dict:
    w = get_world(cid, world_id)
    if not w:
        return {}
    state = mutator(w["state"] or {})
    db.execute("UPDATE worlds SET state_json=? WHERE campaign_id=? AND id=?",
               (jdumps(state), cid, world_id))
    return state


# ==========================================================================
# Shore improvements (M2.0) — glassbead economy
# ==========================================================================

UPGRADES = {
    "camp_kettle": {"name": "Camp Kettle", "cost": 2, "location": "camp",
                    "desc": "A dented kettle for Cardo's fire. Resting at camp restores +2 more Vigor."},
    "camp_guestbook": {"name": "Traveler's Guestbook", "cost": 3, "location": "camp",
                       "desc": "Cardo keeps a ledger of passers-by. Special visitors find the camp."},
    "tavern_mapwall": {"name": "Maren's Map Wall", "cost": 4, "location": "tavern",
                       "desc": "Charts and thread. Maren's rumors sharpen, and doors get easier to whisper open."},
    "tavern_hammock": {"name": "The Back Hammock", "cost": 3, "location": "tavern",
                       "desc": "Past the stove, a hammock that forgets your worries. Tavern rest restores fully."},
    "light_relamp": {"name": "Relamp the Skyless Light", "cost": 5, "location": "lighthouse",
                     "desc": "A new flame for the lamp room. The beam turns teal and whispers seed-words."},
    "light_lens": {"name": "Polished Lens Array", "cost": 4, "location": "lighthouse",
                   "desc": "Ground lenses catch what washes ashore. The beach yields more finds."},
}


def _resolve_ch(cid: str, chid: str | None = None):
    from . import gm as _gm
    ch = _gm.get_character(cid, chid)
    if not ch:
        raise ValueError("campaign has no character")
    return ch


def get_beads(cid: str, chid: str | None = None) -> int:
    """Glassbeads are personal — each wanderer carries their own purse."""
    ch = _resolve_ch(cid, chid)
    return int(gm_ch_get(ch, "beads", 0))


def owned_upgrades(cid: str) -> list[str]:
    return [r["upgrade_id"] for r in db.query(
        "SELECT upgrade_id FROM upgrades WHERE campaign_id=?", (cid,)
    )]


def list_upgrades(cid: str, chid: str | None = None) -> list[dict]:
    owned = set(owned_upgrades(cid))
    beads = get_beads(cid, chid)
    return [{
        "id": uid, **{k: u[k] for k in ("name", "cost", "location", "desc")},
        "owned": uid in owned, "affordable": beads >= u["cost"] and uid not in owned,
    } for uid, u in UPGRADES.items()]


def buy_upgrade(cid: str, upgrade_id: str, chid: str | None = None) -> dict:
    if upgrade_id not in UPGRADES:
        raise ValueError("no such improvement")
    if db.query_one("SELECT 1 FROM upgrades WHERE campaign_id=? AND upgrade_id=?", (cid, upgrade_id)):
        raise ValueError("already built")
    # must be at the upgrade's location to build it
    campaign = db.query_one("SELECT location_id FROM campaigns WHERE id=? AND status='active'", (cid,))
    if not campaign:
        raise ValueError("campaign not found")
    if UPGRADES[upgrade_id]["location"] != campaign["location_id"]:
        raise ValueError(f"you must be at the {UPGRADES[upgrade_id]['location']} to build that")
    ch = _resolve_ch(cid, chid)
    beads = get_beads(cid, ch["id"])
    cost = UPGRADES[upgrade_id]["cost"]
    if beads < cost:
        raise ValueError(f"not enough glassbeads ({beads} of {cost}) — the shore pays for adventure")
    gm_ch_set(ch, "beads", beads - cost)
    db.execute("INSERT INTO upgrades (campaign_id, upgrade_id, purchased_at) VALUES (?,?,?)",
               (cid, upgrade_id, utcnow()))
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    flags = set(state.get("flags", []))
    flags.add(f"up_{upgrade_id}")
    state["flags"] = sorted(flags)
    db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
               (jdumps(state), utcnow(), cid))
    db.log_event(cid, "upgrade", {"upgrade_id": upgrade_id, "cost": cost,
                                  "character_id": ch["id"]})
    remember(cid, "all", "event", f"The shore grew: {UPGRADES[upgrade_id]['name']} was built.")
    if upgrade_id == "tavern_mapwall":
        register_consequence(cid, "upgrade:tavern_mapwall",
                             "Maren's map wall went up; more doors whisper their seeds to her now.",
                             {})
    return {"upgrade_id": upgrade_id, "beads_left": get_beads(cid, ch["id"]),
            "narration": f"Built: {UPGRADES[upgrade_id]['name']}. {UPGRADES[upgrade_id]['desc']}"}


def _campaign_pack(cid: str) -> dict:
    row = db.query_one("SELECT pack_id FROM campaigns WHERE id=?", (cid,))
    return worldpacks.load_pack(row["pack_id"]) or {}


# ==========================================================================
# Omen hand (player-controlled draws under strict rules)
# ==========================================================================

HAND_MAX = 2
DRAWS_PER_REST = 2
DRAW_COST_NERVE = 1


def _deck_key(chid: str | None) -> str:
    return "omens:" + (chid or "")


def _deck_row(cid: str, chid: str | None = None):
    return db.query_one(
        "SELECT * FROM decks WHERE campaign_id=? AND deck_id=?", (cid, _deck_key(chid))
    )


def omen_hand(cid: str, chid: str | None = None) -> dict:
    ch = _resolve_ch(cid, chid)
    row = _deck_row(cid, ch["id"])
    hand = jloads(row["held_json"], []) if row else []
    used = int(gm_ch_get(ch, "omen_draws_used", 0))
    return {
        "hand": hand,
        "draws_used": used,
        "draws_left": max(0, DRAWS_PER_REST - used),
        "hand_max": HAND_MAX,
    }


def draw_to_hand(cid: str, chid: str | None = None) -> dict:
    """Player-initiated draw: costs 1 Nerve, needs hand space and a fresh rest."""
    pack = _campaign_pack(cid)
    cards = worldpacks.get_omens(pack)
    if not cards:
        raise ValueError("no omen deck in this pack")
    ch = _resolve_ch(cid, chid)
    row = _deck_row(cid, ch["id"])
    hand = jloads(row["held_json"], []) if row else []
    used = int(gm_ch_get(ch, "omen_draws_used", 0))
    if len(hand) >= HAND_MAX:
        raise ValueError(f"your hand holds {HAND_MAX} omens already — play one first")
    if used >= DRAWS_PER_REST:
        raise ValueError("the deck has given all it will until you rest")
    if ch["nerve"] <= DRAW_COST_NERVE - 1:
        raise ValueError("not enough Nerve to look (needs 1)")
    draw = jloads(row["draw_json"], []) if row else []
    discard = jloads(row["discard_json"], []) if row else []
    draws = row["draws"] if row else 0
    if not row or (not draw and not discard and not hand):
        # first interaction with this deck: build and shuffle it
        deck = list(cards)
        for i in range(len(deck) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        draw, discard, draws = deck, [], 0
        row = None
    card, draw, discard = rules.draw_from_deck(draw, discard)
    if not card:
        raise ValueError("the deck is spent")
    hand.append(card)
    ch["nerve"] -= DRAW_COST_NERVE
    gm_ch_set(ch, "omen_draws_used", used + 1)
    _gm_persist(ch)
    if row:
        db.execute("UPDATE decks SET draw_json=?, discard_json=?, held_json=?, draws=?"
                   " WHERE campaign_id=? AND deck_id=?",
                   (jdumps(draw), jdumps(discard), jdumps(hand), draws + 1, cid, _deck_key(ch["id"])))
    else:
        db.execute("INSERT INTO decks (campaign_id, deck_id, draw_json, discard_json, held_json, draws)"
                   " VALUES (?,?,?,?,?,?)",
                   (cid, _deck_key(ch["id"]), jdumps(draw), jdumps(discard), jdumps(hand), draws + 1))
    db.log_event(cid, "omen_hand_draw", {"card_id": card.get("id"), "cost": "1 nerve",
                                         "character_id": ch["id"]})
    return {"card": card, "hand": hand, "nerve": ch["nerve"],
            "narration": f"You pull {card['title']} from the deck. {card['text']} (1 Nerve paid.)"}


def play_omen(cid: str, card_id: str, chid: str | None = None) -> dict:
    """Play a held omen. Edges set a +1 on their skill until used; turns grant
    a small defined boon; complications cannot be played deliberately."""
    ch = _resolve_ch(cid, chid)
    row = _deck_row(cid, ch["id"])
    hand = jloads(row["held_json"], []) if row else []
    card = next((c for c in hand if c.get("id") == card_id), None)
    if not card:
        raise ValueError("that omen is not in your hand")
    if card.get("kind") == "complication":
        raise ValueError("complications play themselves — that is what complications are")
    if card.get("kind") == "edge":
        skill = card.get("boost", "any")
        gm_ch_set(ch, "omen_bonus", {"skill": skill, "mod": 1})
        msg = f"{card['title']} is in play: +1 to {skill} checks until it lands."
    else:  # turn card: a small defined boon
        ch["nerve"] = min(ch["nerve_max"], ch["nerve"] + 1)
        _gm_persist(ch)
        msg = f"{card['title']} plays out: the omen steadies you (Nerve +1)."
    hand = [c for c in hand if c.get("id") != card_id]
    discard = jloads(row["discard_json"], []) if row else []
    discard.append(card)
    db.execute("UPDATE decks SET held_json=?, discard_json=? WHERE campaign_id=? AND deck_id=?",
               (jdumps(hand), jdumps(discard), cid, _deck_key(ch["id"])))
    db.log_event(cid, "omen_played", {"card_id": card_id, "character_id": ch["id"]})
    return {"hand": hand, "narration": msg}


def reset_omen_draws(cid: str, chid: str | None = None) -> None:
    ch = _resolve_ch(cid, chid)
    gm_ch_set(ch, "omen_draws_used", 0)


# ==========================================================================
# Push / Resist windows (M2.0 tactical) — per character
# ==========================================================================

def _set_pending_roll(cid: str, chid: str, roll: dict, skill: str, context: str) -> None:
    ch = _resolve_ch(cid, chid)
    gm_ch_set(ch, "pending_roll", {
        "roll_id": new_id("rol"), "skill": skill, "outcome": roll["outcome"],
        "harm": roll["harm"], "harm_type": roll.get("harm_type") or "nerve",
        "pushed": False, "resisted": False, "context": context[:80],
        "risk": bool(roll.get("risk")),
    })


def get_pending_roll(cid: str, chid: str | None = None) -> dict | None:
    ch = _gm_get_character(cid, chid)
    if not ch:
        return None
    return gm_ch_get(ch, "pending_roll")


def _clear_pending(cid: str, chid: str | None = None) -> None:
    ch = _gm_get_character(cid, chid)
    if ch:
        gm_ch_set(ch, "pending_roll", None)


def push_roll(cid: str, chid: str | None = None) -> dict:
    """Spend 1 Vigor (floor 1) to bump a failed/partial band one step.
    Once per roll; never on crits; never from clean/surge."""
    ch = _resolve_ch(cid, chid)
    pending = get_pending_roll(cid, ch["id"])
    if not pending:
        raise ValueError("no roll awaits a decision")
    if pending["pushed"]:
        raise ValueError("you have already pushed this roll")
    new_outcome = rules.bump_band(pending["outcome"])
    if not new_outcome:
        raise ValueError("that roll cannot be pushed — clean, surge and fates are binding")
    if ch["vigor"] < 2:
        raise ValueError("pushing costs 1 Vigor, and you dare not go below 1")
    ch["vigor"] -= 1
    _gm_persist(ch)
    old_harm = rules.harm_for(pending["outcome"], pending.get("risk", False))
    new_harm = rules.harm_for(new_outcome, pending.get("risk", False))
    # settle the harm difference (a push can spare you the remainder)
    delta = new_harm - old_harm
    if delta:
        rules.apply_harm(ch, abs(delta), pending["harm_type"])
        _gm_persist(ch)
    pending.update({"pushed": True, "outcome": new_outcome, "harm": new_harm,
                    "text": f"Pushed: the band rises to {new_outcome} (1 Vigor paid)."})
    gm_ch_set(ch, "pending_roll", pending)
    db.log_event(cid, "roll_pushed", {"outcome": new_outcome, "skill": pending["skill"],
                                      "character_id": ch["id"]})
    remember(cid, "all", "decision", f"Pushed a {pending['skill']} roll to {new_outcome}.")
    return {"pending": pending, "narration": f"You dig deeper — 1 Vigor spent. The outcome rises to {new_outcome}.",
            "changes": [f"Vigor −1.", f"Outcome: {new_outcome}."], "character_id": ch["id"]}


def resist_roll(cid: str, chid: str | None = None) -> dict:
    """Spend 1 Nerve to halve pending harm (rounds down, 1 -> 0). Once."""
    ch = _resolve_ch(cid, chid)
    pending = get_pending_roll(cid, ch["id"])
    if not pending:
        raise ValueError("no roll awaits a decision")
    if pending["resisted"]:
        raise ValueError("you have already resisted this roll")
    harm = int(pending.get("harm") or 0)
    if harm <= 0:
        raise ValueError("nothing to resist — you took no harm")
    if ch["nerve"] < 1:
        raise ValueError("not enough Nerve to resist")
    reduced = rules.resist_harm(harm)
    ch["nerve"] -= 1
    # harm was already applied when the roll landed; refund the difference
    refund = harm - reduced
    if refund:
        if pending.get("harm_type") == "nerve":
            ch["nerve"] = min(ch["nerve_max"], ch["nerve"] + refund)
        else:
            ch["vigor"] = min(ch["vigor_max"], ch["vigor"] + refund)
    _gm_persist(ch)
    pending.update({"resisted": True, "harm": reduced,
                    "text": f"Resisted: harm {harm} → {reduced} (1 Nerve paid)."})
    gm_ch_set(ch, "pending_roll", pending)
    db.log_event(cid, "roll_resisted", {"harm": reduced, "skill": pending["skill"],
                                        "character_id": ch["id"]})
    return {"pending": pending, "narration": f"You brace — 1 Nerve spent. The harm eases to {reduced}.",
            "changes": [f"Harm {harm} → {reduced}."], "character_id": ch["id"]}


# ==========================================================================
# Consequences & clue threads (M2.5)
# ==========================================================================

def register_consequence(cid: str, trigger: str, summary: str, data: dict | None = None) -> None:
    """Record a cross-world consequence. Deduped by trigger."""
    row = db.query_one(
        "SELECT id FROM consequences WHERE campaign_id=? AND trigger=? AND summary=?",
        (cid, trigger[:80], summary[:200]),
    )
    if row:
        return
    db.execute(
        "INSERT INTO consequences (id, campaign_id, ts, trigger, summary, data_json)"
        " VALUES (?,?,?,?,?,?)",
        (new_id("cnq"), cid, utcnow(), trigger[:80], summary[:200], jdumps(data or {})),
    )
    remember(cid, "tavern", "event", summary[:200])


def recent_consequences(cid: str, limit: int = 6) -> list[dict]:
    rows = db.query(
        "SELECT ts, trigger, summary FROM consequences WHERE campaign_id=?"
        " ORDER BY rowid DESC LIMIT ?",
        (cid, limit),
    )
    return [dict(r) for r in reversed(rows)]


def add_clue(cid: str, thread_id: str, text: str, source: str = "event") -> dict:
    dedupe = db.query_one(
        "SELECT id FROM clues WHERE campaign_id=? AND thread_id=? AND text=?",
        (cid, thread_id[:60], text[:300]),
    )
    if dedupe:
        return None
    db.execute(
        "INSERT INTO clues (id, campaign_id, thread_id, ts, text, source) VALUES (?,?,?,?,?,?)",
        (new_id("clu"), cid, thread_id[:60], utcnow(), text[:300], source[:20]),
    )
    db.log_event(cid, "clue", {"thread": thread_id, "text": text[:120]})
    pack = _campaign_pack(cid)
    return check_thread_payoff(cid, pack, thread_id)


def thread_progress(cid: str) -> list[dict]:
    pack = _campaign_pack(cid)
    threads = pack.get("foreshadow_threads", [])
    rows = db.query(
        "SELECT thread_id, ts, text FROM clues WHERE campaign_id=? ORDER BY rowid",
        (cid,),
    )
    by_thread: dict[str, list] = {}
    for r in rows:
        by_thread.setdefault(r["thread_id"], []).append({"ts": r["ts"], "text": r["text"]})
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    paid = set(state.get("threads_paid", []))
    out = []
    for t in threads:
        clues = by_thread.get(t["id"], [])
        out.append({
            "id": t["id"], "title": t["title"], "threshold": t["threshold"],
            "clues": clues, "count": len(clues),
            "paid": t["id"] in paid,
            "payoff_title": t.get("payoff_title", ""),
        })
    return out


def check_thread_payoff(cid: str, pack: dict, thread_id: str) -> dict | None:
    """When a thread reaches its threshold and is unpaid, apply the payoff."""
    thread = next((t for t in pack.get("foreshadow_threads", []) if t["id"] == thread_id), None)
    if not thread:
        return None
    count = db.query_one(
        "SELECT COUNT(*) AS n FROM clues WHERE campaign_id=? AND thread_id=?", (cid, thread_id)
    )["n"]
    state = jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    paid = set(state.get("threads_paid", []))
    if count < thread["threshold"] or thread_id in paid:
        return None
    paid.add(thread_id)
    state["threads_paid"] = sorted(paid)
    changes: list[str] = []
    from . import gm as _gm
    _gm.apply_effects(cid, pack, thread.get("payoff_effects", {}), changes)
    if thread.get("flag"):
        flags = set(state.get("flags", []))
        flags.add(thread["flag"])
        state["flags"] = sorted(flags)
    db.execute("UPDATE campaigns SET state_json=?, updated_at=? WHERE id=?",
               (jdumps(state), utcnow(), cid))
    db.log_event(cid, "thread_payoff", {"thread": thread_id})
    remember(cid, "all", "mystery", f"The {thread['title']} thread paid off: {thread.get('payoff_title', '')}.")
    register_consequence(cid, f"thread:{thread_id}",
                         f"{thread.get('payoff_title', 'An old thread came due')}. The whole shore felt it.",
                         {"thread": thread_id})
    return {"thread": thread["title"], "changes": changes,
            "narration": thread.get("payoff_narration", "The thread pulls tight, and something long-promised comes true.")}


# ==========================================================================
# Echoes (M2.5)
# ==========================================================================

ECHO_KINDS = ("item", "trait", "achievement", "reputation", "decision", "portal", "event")


def echo_offers_for(adventure: dict, ending_id: str) -> list[dict]:
    return (adventure.get("echo_offers", {}) or {}).get(ending_id, [])


def create_echo(cid: str | None, kind: str, title: str, detail: str, data: dict | None = None) -> str:
    if kind not in ECHO_KINDS:
        raise ValueError("invalid echo kind")
    eid = new_id("ech")
    db.execute(
        "INSERT INTO echoes (id, campaign_id, created_at, kind, title, detail, data_json)"
        " VALUES (?,?,?,?,?,?,?)",
        (eid, cid, utcnow(), kind, title[:80], detail[:240], jdumps(data or {})),
    )
    if cid:
        db.log_event(cid, "echo_created", {"kind": kind, "title": title[:60]})
    return eid


def list_echoes(only_unused: bool = False) -> list[dict]:
    rows = db.query(
        "SELECT id, campaign_id, created_at, kind, title, detail, data_json, used_in"
        " FROM echoes ORDER BY created_at DESC"
    )
    out = []
    for r in rows:
        if only_unused and r["used_in"]:
            continue
        out.append({
            "id": r["id"], "campaign_id": r["campaign_id"], "kind": r["kind"],
            "title": r["title"], "detail": r["detail"],
            "data": jloads(r["data_json"], {}), "used_in": r["used_in"],
            "created_at": r["created_at"],
        })
    return out


def weave_echoes(cid: str, pack: dict, echo_ids: list[str]) -> list[str]:
    """Apply up to 2 unused echoes to a freshly created campaign. Each echo
    can be woven into only one campaign, ever."""
    changes: list[str] = []
    from . import gm as _gm
    for eid in (echo_ids or [])[:2]:
        row = db.query_one("SELECT * FROM echoes WHERE id=?", (eid,))
        if not row:
            raise ValueError(f"unknown echo {eid}")
        if row["used_in"]:
            raise ValueError("each echo can only be woven once")
        data = jloads(row["data_json"], {})
        if row["kind"] == "item" and data.get("item_id"):
            if _gm.give_item(cid, pack, str(data["item_id"])):
                changes.append(f"Echo of {row['title']}: the item carried over.")
        elif row["kind"] in ("trait", "achievement") and data.get("trait_skill"):
            skill = str(data["trait_skill"])
            if skill in ("notice", "lore", "persuade", "fight", "endure", "bind"):
                ch = _gm_char(cid)
                ch["skills"][skill] = int(ch["skills"].get(skill, 0)) + int(data.get("trait_delta", 1))
                _gm._persist_character(ch)
                changes.append(f"Echo of {row['title']}: +{data.get('trait_delta', 1)} {skill}, remembered in the muscle.")
        elif row["kind"] == "reputation" and data.get("npc_id"):
            db.execute(
                "INSERT INTO npcs (id, campaign_id, npc_id, name, data_json) VALUES (?,?,?,?,?)"
                " ON CONFLICT(campaign_id, npc_id) DO UPDATE SET"
                " data_json=json_patch(data_json, ?)",
                (new_id("npc"), cid, str(data["npc_id"])[:60], str(data.get("npc_name", data["npc_id"]))[:60],
                 jdumps({"rel": int(data.get("rel_delta", 1)), "facts": [], "met": False,
                         "reputation": True}),
                 jdumps({"rel": int(data.get("rel_delta", 1))})),
            )
            changes.append(f"Echo of {row['title']}: {data.get('npc_name', '')} has heard of you.")
        elif row["kind"] == "portal" and data.get("seed"):
            w = generate_and_store(cid, str(data["seed"]))
            changes.append(f"Echo of {row['title']}: the door to {w['name']} already stands open.")
        else:
            # decision/event echoes surface as tavern lore
            db.execute(
                "INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
                " VALUES (?,?,?,?,?,?,?)",
                (new_id("mem"), cid, "*", utcnow(), "event", "tavern",
                 f"{row['title']} — {row['detail']}"[:400]),
            )
            changes.append(f"Echo of {row['title']}: the tavern already tells this tale.")
        db.execute("UPDATE echoes SET used_in=? WHERE id=?", (cid, eid))
        db.log_event(cid, "echo_woven", {"echo_id": eid, "kind": row["kind"]})
    return changes


# ==========================================================================
# Memory Ledger (M2.5 visual journal backend)
# ==========================================================================

def ledger(cid: str, chid: str | None = None) -> dict:
    campaign = db.query_one("SELECT * FROM campaigns WHERE id=? AND status='active'", (cid,))
    if not campaign:
        raise ValueError("campaign not found")
    pack = _campaign_pack(cid)
    state = jloads(campaign["state_json"], {})

    worlds = list_worlds(cid)
    people = []
    for r in db.query("SELECT npc_id, name, data_json FROM npcs WHERE campaign_id=?", (cid,)):
        data = jloads(r["data_json"], {})
        people.append({"npc_id": r["npc_id"], "name": r["name"], "rel": data.get("rel", 0),
                       "met": bool(data.get("met")), "reputation": bool(data.get("reputation"))})
    memories = db.query(
        "SELECT ts, kind, scope, text FROM npc_memories WHERE campaign_id=? ORDER BY rowid DESC LIMIT 40",
        (cid,),
    )
    endings = [dict(r) | {"data": jloads(r["data_json"], {})} for r in db.query(
        "SELECT ts, type, data_json FROM events WHERE campaign_id=? AND type IN "
        "('adventure_ended','thread_payoff','campaign_created','world_generated')"
        " ORDER BY rowid DESC LIMIT 30", (cid,)
    )]
    threads = thread_progress(cid)
    cons = recent_consequences(cid, 12)
    echoes = list_echoes()
    open_quests = [q for q in db.query(
        "SELECT quest_id, title, status, notes_json FROM quests WHERE campaign_id=? AND status='open'",
        (cid,)
    )]
    party = party_history(cid)
    return {
        "worlds": worlds,
        "people": people,
        "threads": threads,
        "consequences": cons,
        "memories": [dict(r) for r in memories],
        "endings": endings,
        "echoes": echoes,
        "beads": get_beads(cid, chid),
        "upgrades": list_upgrades(cid, chid),
        "open_quests": [{"id": q["quest_id"], "title": q["title"]} for q in open_quests],
        "endings_seen": state.get("endings_seen", []),
        "party": party,
    }


def party_history(cid: str) -> dict:
    """Shared-shore memories: who sailed together, and what they did."""
    session = db.query_one("SELECT * FROM mp_sessions WHERE campaign_id=?", (cid,))
    members = []
    if session:
        for r in db.query(
            "SELECT display_name, character_id, is_host, status, joined_at FROM mp_players"
            " WHERE campaign_id=? AND status IN ('connected','offline') ORDER BY joined_at",
            (cid,),
        ):
            ch = db.query_one("SELECT name, archetype FROM characters WHERE id=?", (r["character_id"] or "",))
            members.append({
                "player": r["display_name"], "host": bool(r["is_host"]),
                "character": ch["name"] if ch else None,
                "archetype": ch["archetype"] if ch else None,
                "status": r["status"],
            })
    moments = db.query(
        "SELECT ts, trigger, summary FROM consequences WHERE campaign_id=?"
        " AND trigger LIKE 'party:%' ORDER BY rowid DESC LIMIT 20",
        (cid,),
    )
    return {"session": bool(session), "members": members,
            "moments": [dict(r) for r in reversed(moments)]}
