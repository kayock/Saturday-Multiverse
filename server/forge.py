"""Saturday Multiverse — The Campaign Forge.

Turns an imported library document into an engine-valid world pack. The
AI Game Master extracts and proposes; the Forge structures, validates and
installs. Nothing the model returns ever touches a live campaign — drafts
are edited and approved by a human first, and approval runs the same
validation the pack importer uses.

Pipeline:
  1. slice the document into bounded extraction windows
  2. one extraction call per window -> raw material (cast, places, events,
     items, plot, secrets)
  3. synthesis calls -> draft world pack in the exact pack schema
  4. deterministic validation + auto-repair (ids, gotos, hub, endings)
  5. human edit / regenerate sections / approve -> pack installed
"""
from __future__ import annotations

import json
import re
import shutil
import time

from . import ai, db, forge_ai, library
from .config import PACKS_DATA_DIR
from .db import jdumps, jloads, new_id, utcnow

MAX_WINDOWS = 6
WINDOW_CHUNKS = 12

VALID_EFFECT_KEYS = {"journal", "fact", "hidden_fact", "beads", "item_give", "item_take",
                     "flag", "quest_update", "npc_rel", "harm", "heal", "discover",
                     "adventure", "ending", "return_shore", "dnd_encounter"}
VALID_SKILLS = {"notice", "lore", "persuade", "fight", "endure", "bind"}
VALID_EFFECTS_META = {"goto", "on_pass", "on_fail", "effects"}


class ForgeError(ValueError):
    pass


# ==========================================================================
# Draft lifecycle
# ==========================================================================

def create_draft(doc_id: str, mode: str = "faithful", *, max_calls: int | None = None,
                 transmit_approved: bool = False) -> dict:
    """Run the extraction + synthesis pipeline for one library document."""
    doc = library.doc_view(doc_id)
    if mode not in ("faithful", "alternate", "expanded"):
        raise ForgeError("mode must be faithful, alternate, or expanded")
    try:
        cfg = forge_ai.resolve(transmit_approved=transmit_approved)
    except forge_ai.ForgeAiError as exc:
        raise ForgeError(str(exc)) from exc
    draft_id = new_id("fge")
    db.execute(
        "INSERT INTO forge_drafts (id, doc_id, mode, status, pack_json, profile_json,"
        " notes_json, created_at, updated_at) VALUES (?,?,?, 'drafting', '{}', '{}', '[]', ?, ?)",
        (draft_id, doc_id, mode, utcnow(), utcnow()),
    )
    profile, notes = _extract(doc, max_calls, cfg)
    db.execute("UPDATE forge_drafts SET profile_json=?, notes_json=? WHERE id=?",
               (jdumps(profile), jdumps(notes), draft_id))
    pack = _synthesize(draft_id, doc, profile, mode, notes, cfg)
    pack = _repair_pack(pack, doc)
    problems = validate_pack(pack)
    status = "draft" if not problems else "draft"
    db.execute(
        "UPDATE forge_drafts SET pack_json=?, notes_json=?, status='draft', updated_at=? WHERE id=?",
        (jdumps(pack), jdumps(notes + (["validation: " + "; ".join(problems)] if problems else [])),
         utcnow(), draft_id),
    )
    return draft_view(draft_id)


def _extract(doc: dict, max_calls: int | None, cfg: dict | None = None) -> tuple[dict, list[str]]:
    """Window-by-window extraction of raw story material."""
    n = doc["n_chunks"]
    window = WINDOW_CHUNKS
    starts = []
    i = 0
    while i < n and len(starts) < (max_calls or MAX_WINDOWS):
        starts.append(i)
        i += window
    profile: dict = {"characters": [], "locations": [], "factions": [],
                     "events": [], "items": [], "plot_points": [], "secrets": []}
    notes: list[str] = []
    for si, start in enumerate(starts):
        rows = db.query(
            "SELECT heading, text FROM library_chunks WHERE doc_id=? AND seq>=? AND seq<?"
            " ORDER BY seq LIMIT ?", (doc["id"], start, start + window, window),
        )
        passage = "\n".join(f"[{r['heading']}] {r['text'][:500]}" for r in rows)[:9000]
        messages = [
            {"role": "system", "content": FORGE_EXTRACT_SYSTEM},
            {"role": "user", "content": f"SOURCE EXCERPT (part {si + 1}):\n\n{passage}"},
        ]
        try:
            text, meta = ai.chat(messages, cfg or forge_ai.resolve())
            data = ai.extract_json(text)
        except ai.AiError as exc:
            notes.append(f"window {si + 1}: model unavailable ({exc.detail}); skipped")
            continue
        if not isinstance(data, dict):
            notes.append(f"window {si + 1}: model did not return the JSON contract; skipped")
            continue
        _merge_profile(profile, data)
        notes.append(f"window {si + 1}: extracted "
                     f"{len(data.get('characters', []))} characters, "
                     f"{len(data.get('locations', []))} places")
    return profile, notes


FORGE_EXTRACT_SYSTEM = """You are the Campaign Forge's analyst. From the excerpt, extract story
material as ONE JSON object (no markdown, no prose outside it):
{"characters": [{"name":"", "role":"", "desc":"<=60 words", "goals":""}],
 "locations": [{"name":"", "desc":"<=50 words"}],
 "factions": [{"name":"", "desc":"<=30 words"}],
 "events": [{"name":"", "when":"", "what":"<=40 words"}],
 "items": [{"name":"", "desc":"<=25 words"}],
 "plot_points": ["one-line beat"],
 "secrets": ["hidden truth the GM knows but players must discover"]}
Extract ONLY what the excerpt supports. Keep each person's name, motive, and place
consistent with this excerpt. Record when an event happens if the excerpt says so.
No invented content. Every list may be empty."""


def _merge_profile(profile: dict, data: dict) -> None:
    for key in ("characters", "locations", "factions", "events", "items",
                "plot_points", "secrets"):
        incoming = data.get(key) or []
        if key == "plot_points" or key == "secrets":
            for item in incoming:
                if isinstance(item, str) and item.strip() and item.strip() not in profile[key]:
                    profile[key].append(item.strip()[:200])
            continue
        for item in incoming:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            if any(e["name"].lower() == name.lower() for e in profile[key]):
                continue
            profile[key].append({k: str(v)[:300] for k, v in item.items() if isinstance(v, str)})
        profile[key] = profile[key][:40]


def _mode_line(mode: str) -> str:
    if mode == "faithful":
        return ("FAITHFUL ADAPTATION: keep the source's names, events, and outcomes. "
                "Players may still fail or deviate inside those events.")
    if mode == "expanded":
        return ("EXPANDED UNIVERSE: the book supplies the setting, cast, motives, and "
                "hidden facts. Create new adventures around that world. Do not rewrite "
                "the book's ending, and do not contradict established character motives.")
    return ("ALTERNATE HISTORY: the setting and cast come from the source. Mark "
            "[DIVERGENCE] where players can change an important event. NPC motives "
            "stay consistent with the book until a player changes them.")


def _synthesize(draft_id: str, doc: dict, profile: dict, mode: str,
                notes: list[str], cfg: dict | None = None) -> dict:
    """Two bounded synthesis calls -> a draft pack in the exact schema."""
    cfg = cfg or forge_ai.resolve()
    material = json.dumps(profile, ensure_ascii=False)[:14000]
    mode_line = _mode_line(mode)
    messages = [
        {"role": "system", "content": FORGE_WORLD_SYSTEM},
        {"role": "user", "content": f"SOURCE: {doc['title']} by {doc['author'] or 'unknown'}\n"
         f"MODE: {mode_line}\nEXTRACTED MATERIAL:\n{material}"},
    ]
    text, meta = ai.chat(messages, cfg)
    world = ai.extract_json(text)
    if not isinstance(world, dict):
        raise ForgeError("the model did not return the world JSON contract")
    notes.append(f"synthesis: world '{world.get('name', '?')}' "
                 f"({len(world.get('locations', []))} places, {len(world.get('npcs', []))} npcs)")

    adv_messages = [
        {"role": "system", "content": FORGE_ADVENTURE_SYSTEM},
        {"role": "user", "content": f"WORLD: {json.dumps(world, ensure_ascii=False)[:8000]}\n"
         f"MODE: {mode_line}\nMATERIAL PLOT:\n{json.dumps(profile.get('plot_points', [])[:20])}\n"
         f"SECRETS: {json.dumps(profile.get('secrets', [])[:12])}"},
    ]
    text2, meta2 = ai.chat(adv_messages, cfg)
    adventure = ai.extract_json(text2)
    if not isinstance(adventure, dict):
        raise ForgeError("the model did not return the adventure JSON contract")
    notes.append(f"synthesis: adventure '{adventure.get('title', '?')}' "
                 f"({len(adventure.get('scenes', []))} scenes)")

    pack = _assemble_pack(doc, world, adventure, mode)
    return pack


FORGE_WORLD_SYSTEM = """You are the Campaign Forge's world-builder. Return ONE JSON object (no
markdown, no prose) shaped exactly like this:
{"name":"", "summary":"<=40 words", "genre_tags":["",""], "gm_style":"one sentence of tone",
 "locations":[{"id":"snake_case","name":"","short":"<=12 words","desc":"<=70 words","known":true,
   "flavor":["<=15 words"], "rest":{"vigor":2,"nerve":2}}],
 "npcs":[{"id":"snake_case","name":"","role":"","location":"<a location id>","desc":"<=40 words",
   "greeting":"one spoken line","rumors":["<=20 words"]}],
 "items":[{"id":"snake_case","name":"","kind":"trinket|charm|relic|tool","desc":"<=20 words",
   "use":{"text":"<=20 words","heal":{"nerve":1},"consume":true}}],
 "omens":[{"id":"","kind":"edge|turn|complication","title":"","text":"<=25 words","boost":"notice"}],
 "intro_facts":["<=25 words each, things a newcomer would sense"]}
Use only material from the source. ids must be snake_case and unique. 4-7 locations, 4-7 npcs,
6-10 items, 6-10 omens, 4-8 intro facts. Omens kind edge/turn need boost/title; complications do not."""


def _assemble_pack(doc: dict, world: dict, adventure: dict, mode: str) -> dict:
    pack_id = "forge_" + _slug(world.get("name") or doc["title"])[:24] + "_" + doc["id"][-6:]
    theme = {
        "bg": "#0b0e14", "deep": "#141126", "purple": "#7c5cff", "glow": "#9b8cff",
        "teal": "#43e8d8", "gold": "#e8b46b", "text": "#e9e4f2",
    }
    hub = ""
    locs = []
    for i, loc in enumerate(world.get("locations", [])[:8]):
        lid = _slug(loc.get("id") or loc.get("name") or f"loc{i}")
        if i == 0:
            hub = lid
        locs.append({
            "id": lid, "name": loc.get("name", lid),
            "short": (loc.get("short") or loc.get("desc", ""))[:120],
            "desc": (loc.get("desc") or loc.get("short", ""))[:700],
            "known": True,
            "flavor": [f[:140] for f in (loc.get("flavor") or [])[:4]],
            "hotspots": [dict(h) for h in (loc.get("hotspots") or [])[:4]],
            **({"rest": loc["rest"]} if isinstance(loc.get("rest"), dict) else {}),
        })
    if not locs:
        locs = [{"id": "arrival", "name": "The Arrival", "short": "Where the story begins.",
                 "desc": "A place drawn from the source.", "known": True, "flavor": []}]
        hub = "arrival"
    npcs = []
    for npc in world.get("npcs", [])[:10]:
        npcs.append({
            "id": _slug(npc.get("id") or npc.get("name") or "npc"),
            "name": npc.get("name", ""), "role": npc.get("role", ""),
            "location": _slug(npc.get("location") or hub),
            "desc": npc.get("desc", "")[:400], "greeting": npc.get("greeting", ""),
            "rumors": [r[:160] for r in (npc.get("rumors") or [])[:4]],
        })
    items = []
    for it in world.get("items", [])[:12]:
        entry = {"id": _slug(it.get("id") or it.get("name") or "item"),
                 "name": it.get("name", ""), "kind": it.get("kind", "trinket"),
                 "desc": it.get("desc", "")[:220]}
        use = it.get("use")
        if isinstance(use, dict) and (use.get("text") or use.get("heal")):
            entry["use"] = {k: use[k] for k in ("text", "heal", "consume") if k in use}
        items.append(entry)
    omens = []
    for k, om in enumerate(world.get("omens", [])[:12]):
        omens.append({"id": f"om{k + 1}", "kind": om.get("kind", "edge"),
                      "title": om.get("title", "An Omen"), "text": om.get("text", "")[:200],
                      **({"boost": om.get("boost", "notice")} if om.get("kind") != "complication" else {})})
    if not omens:
        omens = [
            {"id": "om1", "kind": "edge", "title": "Second Sight", "text": "A pattern others miss is plain to you.", "boost": "notice"},
            {"id": "om2", "kind": "complication", "title": "Wrong Turn", "text": "The way back is not the way you came."},
            {"id": "om3", "kind": "turn", "title": "Steady Hand", "text": "For one moment, fate moves aside.", "boost": "endure"},
        ]
    # adventure -> schema (scenes/endings arrive as list or dict; normalize)
    scenes_in = adventure.get("scenes", [])
    if isinstance(scenes_in, dict):
        scenes_in = [{"id": k, **{kk: vv for kk, vv in v.items()}} for k, v in scenes_in.items()]
    endings_in = adventure.get("endings", {})
    if isinstance(endings_in, list):
        endings_in = {e.get("id", f"ending_{i}"): e for i, e in enumerate(endings_in)}
    scenes_map = {}
    for sc in scenes_in[:12]:
        sid = _slug(sc.get("id") or sc.get("title") or "scene")
        choices = []
        for c in sc.get("choices", [])[:4]:
            chk = c.get("check") if isinstance(c.get("check"), dict) else None
            entry = {"id": _slug(c.get("id") or c.get("label") or "choice"),
                     "label": c.get("label", "Act"), "hint": c.get("hint", "")[:120]}
            if chk and chk.get("skill") in VALID_SKILLS:
                entry["check"] = {"skill": chk["skill"],
                                  "hard": bool(chk.get("hard")),
                                  "riptide_counts_pass": bool(chk.get("riptide_counts_pass"))}
                for branch in ("on_pass", "on_fail"):
                    b = c.get(branch)
                    if isinstance(b, dict):
                        entry[branch] = {"goto": _slug(b.get("goto") or "") if b.get("goto") else None,
                                         "effects": _clean_effects(b.get("effects") or {})}
            else:
                entry["goto"] = _slug(c.get("goto") or "")
                entry["effects"] = _clean_effects(c.get("effects") or {})
            choices.append(entry)
        scenes_map[sid] = {
            "title": sc.get("title", sid), "brief": sc.get("brief", "")[:300],
            "gm_directive": sc.get("gm_directive", "")[:300],
            "intro": sc.get("intro", "")[:900],
            "flavor": [f[:140] for f in (sc.get("flavor") or [])[:4]],
            "choices": choices,
            "hotspots": [dict(h) for h in (sc.get("hotspots") or [])[:4]],
        }
    endings = {}
    for eid_key, e in list(endings_in.items())[:6]:
        eid = _slug(e.get("id") or eid_key)
        endings[eid] = {"text": e.get("text", "")[:900],
                        "return_location": _slug(e.get("return_location") or hub),
                        "effects": _clean_effects(e.get("effects") or {}),
                        "consequence": e.get("consequence", "")[:160]}
    entry_scene = _slug(adventure.get("entry") or (next(iter(scenes_map)) if scenes_map else "arrival"))
    if entry_scene not in scenes_map and scenes_map:
        entry_scene = next(iter(scenes_map))
    pack_adventure = {
        "id": _slug(adventure.get("id") or "main_quest"),
        "title": adventure.get("title", "The Main Quest"),
        "summary": adventure.get("summary", "")[:200],
        "genre": adventure.get("genre", doc.get("doc_type", "novel")),
        "entry": entry_scene,
        "scenes": scenes_map,
        "endings": endings,
        "on_enter": [],
        "portal_id": "door_library",
        "echo_offers": {eid: [{"kind": "achievement", "title": "Story-Walker",
                               "detail": f"Walked {world.get('name', 'a forged world')}'s road to an ending.",
                               "data": {"trait_skill": "lore", "trait_delta": 1}}]
                        for eid in endings},
    }
    # arriving at the hub opens the story: the adventure rides the hub
    for loc in locs:
        if loc["id"] == hub:
            loc["adventure"] = pack_adventure["id"]
    portal = [{"id": "door_library", "label": f"Door of {world.get('name', 'the Forged World')}",
               "target_location": hub, "door_index": 0,
               "hint": adventure.get("summary", "A forged story")[:120]}]
    pack = {
        "id": pack_id,
        "name": world.get("name", doc["title"])[:80],
        "summary": world.get("summary", "")[:220],
        "version": 1,
        "genre_tags": [str(t)[:30] for t in (world.get("genre_tags") or [])[:4]],
        "gm_style": world.get("gm_style", "Faithful to the source's tone.")[:220],
        "theme": theme,
        "hub_location": hub,
        "locations": locs,
        "archetypes": _archetypes_for(world),
        "npcs": npcs,
        "items": items,
        "omens": omens,
        "weather": [{"key": "settled", "weight": 3, "desc": "The world holds its breath."},
                    {"key": "omenful", "weight": 2, "desc": "Something in the air is paying attention."},
                    {"key": "storm", "weight": 1, "desc": "Weather from the source turns against you."}],
        "washashore": [
            {"id": "glass_beads", "kind": "beads", "label": "a scatter of glassbeads",
             "text": "Glassbeads, polished by the Beam. The shore pays for attention.",
             "effects": {"beads": 2}, "weight": 3},
            {"id": "page_scrap", "kind": "clue", "label": "a loose page from the book itself",
             "text": "A page torn from the very story you walk in.",
             "effects": {"fact": "A loose page from the source drifted ashore."}, "weight": 2},
        ],
        "portals": portal,
        "adventures": [pack_adventure],
        "intro_facts": [str(f)[:200] for f in (world.get("intro_facts") or [])[:8]],
        "intro_quests": [{"id": q.get("id", f"q{i}"), "title": q.get("title", "An open thread")}
                         for i, q in enumerate(adventure.get("quests", [])[:4])
                         if isinstance(q, dict) and q.get("title")],
        "gm_secrets": [str(s)[:240] for s in (adventure.get("gm_secrets") or [])[:10]],
        "license": {
            "source_title": doc["title"], "author": doc["author"],
            "source_url": doc["source_url"], "license": doc["license"],
            "attribution": doc["attribution"], "library_doc_id": doc["id"],
            "adaptation": f"Forged adaptation ({mode}) by Saturday Multiverse Campaign Forge.",
        },
        "library_doc_id": doc["id"],
        "forge_mode": mode,
    }
    return pack


def _archetypes_for(world: dict) -> list[dict]:
    """Themed archetypes using the standard Undertow stat vocabulary."""
    return [
        {"id": "seeker", "name": "Seeker", "blurb": "You came looking for the truth of this story.",
         "stats": {"wits": 2, "might": 0, "mettle": 1, "bind": 0}, "palette": "teal",
         "kit": ["grandmothers_journal"]},
        {"id": "warden", "name": "Warden", "blurb": "You protect the ones who cannot leave.",
         "stats": {"wits": 0, "might": 2, "mettle": 1, "bind": 0}, "palette": "gold",
         "kit": ["salt_charm"]},
        {"id": "medium", "name": "Medium", "blurb": "You hear what the story has not said yet.",
         "stats": {"wits": 1, "might": -1, "mettle": 1, "bind": 2}, "palette": "violet",
         "kit": ["chalk"]},
        {"id": "outcast", "name": "Outcast", "blurb": "You know this world's cruelty from the inside.",
         "stats": {"wits": 1, "might": 1, "mettle": 2, "bind": -1}, "palette": "ember",
         "kit": ["iron_lantern"]},
    ]


def _clean_effects(effects: dict) -> dict:
    out = {}
    for k, v in effects.items():
        if k not in VALID_EFFECT_KEYS:
            continue
        if k in ("journal", "fact", "hidden_fact") and isinstance(v, str):
            out[k] = v[:300]
        elif k == "beads" and isinstance(v, int):
            out[k] = max(-5, min(5, v))
        elif k == "item_give" and isinstance(v, str):
            out[k] = v
        elif k == "harm" and isinstance(v, dict):
            out[k] = {"amount": max(1, min(3, int(v.get("amount", 1)))),
                      "type": "nerve" if v.get("type") == "nerve" else "vigor"}
        elif k == "heal" and isinstance(v, dict):
            out[k] = v
        elif k == "flag" and isinstance(v, str):
            out[k] = _slug(v)
        elif k == "quest_update" and isinstance(v, dict):
            out[k] = v
        elif k == "discover" and isinstance(v, str):
            out[k] = v
        elif k == "adventure" and isinstance(v, str):
            out[k] = _slug(v)
        elif k == "ending" and isinstance(v, str):
            out[k] = _slug(v)
        elif k == "npc_rel" and isinstance(v, dict):
            out[k] = {str(k2)[:40]: max(-3, min(3, int(v2))) for k2, v2 in v.items()
                      if isinstance(v2, (int, float))}
    return out


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s[:40] or "x"


# ==========================================================================
# Validation + auto-repair
# ==========================================================================

def validate_pack(pack: dict) -> list[str]:
    """Deterministic validation; returns a list of problems (empty = valid)."""
    problems: list[str] = []
    for key in ("id", "name", "locations", "npcs", "items", "omens", "adventures", "hub_location"):
        if key not in pack:
            problems.append(f"missing required key: {key}")
    loc_ids = {l["id"] for l in pack.get("locations", [])}
    if pack.get("hub_location") not in loc_ids:
        problems.append(f"hub_location '{pack.get('hub_location')}' is not a known location")
    if pack.get("hub_location") not in loc_ids and locs_ok(pack, loc_ids):
        pack["hub_location"] = sorted(loc_ids)[0]
    npc_loc_ids = {n.get("location") for n in pack.get("npcs", [])}
    for nid in npc_loc_ids - loc_ids:
        problems.append(f"npc location '{nid}' is not a known location")
    for adv in pack.get("adventures", []):
        scenes = adv.get("scenes", {})
        sids = set(scenes.keys()) if isinstance(scenes, dict) else \
            {s["id"] for s in scenes}
        if isinstance(scenes, dict):
            pass
        if adv.get("entry") not in sids:
            problems.append(f"adventure '{adv.get('id')}' entry scene missing")
        for sid, sc in (scenes.items() if isinstance(scenes, dict) else
                        ((s["id"], s) for s in scenes)):
            for c in sc.get("choices", []):
                for dest in (c.get("goto"),
                             (c.get("on_pass") or {}).get("goto"),
                             (c.get("on_fail") or {}).get("goto")):
                    if dest and dest not in sids:
                        problems.append(f"scene '{sid}' choice '{c.get('id')}' -> unknown scene '{dest}'")
                for branch in (c.get("on_pass"), c.get("on_fail")):
                    if isinstance(branch, dict):
                        for k in branch.get("effects", {}):
                            if k not in VALID_EFFECT_KEYS:
                                problems.append(f"scene '{sid}': unknown effect key '{k}'")
        endings = adv.get("endings", {})
        eids = set(endings.keys()) if isinstance(endings, dict) else \
            {e["id"] for e in endings}
        for eid, e in (endings.items() if isinstance(endings, dict) else
                       ((e["id"], e) for e in endings)):
            ret = e.get("return_location")
            if ret and ret not in loc_ids:
                problems.append(f"ending '{eid}' returns to unknown location '{ret}'")
        if not eids:
            problems.append(f"adventure '{adv.get('id')}' has no endings")
    seen_ids = set()
    for it in pack.get("items", []):
        if it["id"] in seen_ids:
            problems.append(f"duplicate item id: {it['id']}")
        seen_ids.add(it["id"])
    return problems


def locs_ok(pack: dict, loc_ids: set) -> bool:
    return bool(loc_ids)


def _repair_pack(pack: dict, doc: dict) -> dict:
    """Deterministic fixes for common model mistakes."""
    loc_ids = {l["id"] for l in pack.get("locations", [])}
    if pack.get("hub_location") not in loc_ids and loc_ids:
        pack["hub_location"] = sorted(loc_ids)[0]
    for npc in pack.get("npcs", []):
        if npc.get("location") not in loc_ids:
            npc["location"] = pack["hub_location"]
    for adv in pack.get("adventures", []):
        scenes = adv.get("scenes", {})
        if isinstance(scenes, list):
            adv["scenes"] = {s["id"]: s for s in scenes}
        scenes = adv["scenes"]
        sids = set(scenes.keys())
        if adv.get("entry") not in sids and sids:
            adv["entry"] = sorted(sids)[0]
        endings = adv.get("endings", {})
        if isinstance(endings, list):
            adv["endings"] = {e["id"]: e for e in endings}
        endings = adv["endings"]
        for e in endings.values():
            if e.get("return_location") not in loc_ids:
                e["return_location"] = pack["hub_location"]
        for sc in scenes.values():
            for c in sc.get("choices", []):
                # models often route a choice straight to an ending id:
                # convert that into the schema's ending effect
                if c.get("goto") in endings:
                    c.setdefault("effects", {})["ending"] = c["goto"]
                    c["goto"] = None
                for branch in (c.get("on_pass"), c.get("on_fail")):
                    if isinstance(branch, dict) and branch.get("goto") in endings:
                        branch.setdefault("effects", {})["ending"] = branch["goto"]
                        branch["goto"] = None
                if not c.get("check") and not c.get("goto") \
                        and not c.get("effects", {}).get("ending"):
                    c["goto"] = adv["entry"]
                for branch in (c.get("on_pass"), c.get("on_fail")):
                    if isinstance(branch, dict) and branch.get("goto") and branch["goto"] not in sids:
                        branch["goto"] = None
                        if not branch.get("effects", {}).get("ending"):
                            branch.setdefault("effects", {})["ending"] = next(iter(endings), None)
                            branch["effects"]["ending"] = next(iter(endings))
        if not endings and sids:
            adv["endings"] = {"unresolved": {"text": "The story pauses, unresolved — the door home remains open.",
                                             "return_location": pack["hub_location"], "effects": {}}}
    if not pack.get("intro_quests"):
        pack["intro_quests"] = [{"id": "follow_the_story", "title": "Follow the story's thread"}]
    if not pack.get("intro_facts"):
        pack["intro_facts"] = [f"This world is forged from "
                               f"{(pack.get('license') or {}).get('source_title', 'its source')}."]
    pack.setdefault("license", {})
    return pack


# ==========================================================================
# Editor operations
# ==========================================================================

def draft_view(draft_id: str) -> dict:
    row = db.query_one("SELECT * FROM forge_drafts WHERE id=?", (draft_id,))
    if not row:
        raise ForgeError("no such draft")
    d = dict(row)
    d["pack"] = jloads(d.pop("pack_json"), {})
    d["profile"] = jloads(d.pop("profile_json"), {})
    d["notes"] = jloads(d.pop("notes_json"), [])
    return d


def list_drafts() -> list[dict]:
    rows = db.query("SELECT id, doc_id, mode, status, created_at, updated_at FROM forge_drafts"
                    " ORDER BY updated_at DESC")
    out = []
    for r in rows:
        d = dict(r)
        doc = db.query_one("SELECT title FROM library_docs WHERE id=?", (d["doc_id"],))
        d["doc_title"] = doc["title"] if doc else "(deleted document)"
        out.append(d)
    return out


def regenerate_section(draft_id: str, section: str, notes_text: str = "",
                       transmit_approved: bool = False) -> dict:
    """Regenerate one pack section from the profile + the editor's notes."""
    draft = draft_view(draft_id)
    if draft["status"] == "approved":
        raise ForgeError("this draft is already approved — duplicate the pack to iterate")
    try:
        cfg = forge_ai.resolve(transmit_approved=transmit_approved)
    except forge_ai.ForgeAiError as exc:
        raise ForgeError(str(exc)) from exc
    pack = draft["pack"]
    doc = library.doc_view(draft["doc_id"])
    profile = draft["profile"]
    if section == "world":
        pack = _synthesize(draft_id, doc, profile, draft["mode"],
                           draft["notes"] + [f"editor notes: {notes_text}"], cfg)
        pack = _repair_pack(pack, doc)
    elif section in ("adventure", "quests", "secrets"):
        adv_messages = [
            {"role": "system", "content": FORGE_ADVENTURE_SYSTEM +
             (f"\nEDITOR GUIDANCE (follow it): {notes_text[:400]}" if notes_text else "")},
            {"role": "user", "content": f"WORLD: {json.dumps(pack, ensure_ascii=False)[:8000]}\n"
             f"MODE: {_mode_line(draft['mode'])}\n"
             f"MATERIAL PLOT: {json.dumps(profile.get('plot_points', [])[:20])}\n"
             f"SECRETS: {json.dumps(profile.get('secrets', [])[:12])}"},
        ]
        text, meta = ai.chat(adv_messages, cfg)
        adventure = ai.extract_json(text)
        if not isinstance(adventure, dict):
            raise ForgeError("the model did not return the adventure JSON contract")
        rebuilt = _assemble_pack(doc, _world_from_pack(pack), adventure, draft["mode"])
        pack["adventures"] = rebuilt["adventures"]
        pack["intro_quests"] = rebuilt["intro_quests"]
        pack["gm_secrets"] = rebuilt["gm_secrets"]
        pack = _repair_pack(pack, doc)
    else:
        raise ForgeError("section must be 'world' or 'adventure'")
    notes = draft["notes"] + [f"regenerated {section}" + (f": {notes_text[:120]}" if notes_text else "")]
    db.execute("UPDATE forge_drafts SET pack_json=?, notes_json=?, updated_at=? WHERE id=?",
               (jdumps(pack), jdumps(notes), utcnow(), draft_id))
    return draft_view(draft_id)


def _world_from_pack(pack: dict) -> dict:
    return {"name": pack.get("name", ""), "summary": pack.get("summary", ""),
            "genre_tags": pack.get("genre_tags", []), "gm_style": pack.get("gm_style", ""),
            "locations": pack.get("locations", []), "npcs": pack.get("npcs", []),
            "items": pack.get("items", []), "omens": pack.get("omens", []),
            "intro_facts": pack.get("intro_facts", [])}


def approve_draft(draft_id: str) -> dict:
    """Validate and install the draft as a playable world pack."""
    draft = draft_view(draft_id)
    pack = draft["pack"]
    problems = validate_pack(pack)
    if problems:
        raise ForgeError("cannot approve — the draft still has problems: "
                         + "; ".join(problems[:6]))
    pack_dir = PACKS_DATA_DIR / pack["id"]
    pack_dir.mkdir(parents=True, exist_ok=True)
    path = pack_dir / "pack.json"
    path.write_text(jdumps(pack), encoding="utf-8")
    notes = draft["notes"] + [f"approved and installed as {pack['id']}"]
    db.execute("UPDATE forge_drafts SET status='approved', pack_json=?, notes_json=?, updated_at=?"
               " WHERE id=?", (jdumps(pack), jdumps(notes), utcnow(), draft_id))
    db.log_event("library", "forge_approved", {"pack_id": pack["id"], "doc_id": draft["doc_id"]})
    return {"pack_id": pack["id"], "path": str(path), "problems": []}


FORGE_ADVENTURE_SYSTEM = """You are the Campaign Forge's adventure-builder. Return ONE JSON object
(no markdown, no prose) shaped exactly like this:
{"title":"", "summary":"<=30 words", "entry":"<first scene id>",
 "quests":[{"id":"snake_case","title":"<=8 words"}],
 "gm_secrets":["hidden truths the GM holds; never stated openly"],
 "scenes":[{"id":"snake_case","title":"","brief":"<=30 words","gm_directive":"<=25 words",
   "intro":"<=90 words, second person, present tense","flavor":["<=14 words"],
   "choices":[{"id":"snake_case","label":"<=8 words","hint":"<=10 words",
     "check":{"skill":"notice|lore|persuade|fight|endure|bind","hard":false,"riptide_counts_pass":false},
     "on_pass":{"goto":"<scene id>","effects":{"journal":"","fact":"","beads":1}},
     "on_fail":{"goto":"<scene id>","effects":{"harm":{"amount":1,"type":"nerve"}}}}
     or without check: {"id":"", "label":"", "goto":"<scene id>", "effects":{}}],
   "hotspots":[{"id":"", "label":"", "x":50, "y":50, "text":"<=20 words"}]}],
 "endings":{"ending_id":{"text":"<=80 words","return_location":"<a location id>",
   "effects":{"ending":"ending_id"},"consequence":"<=15 words"}}}
Rules: 4-9 scenes forming a story with a beginning, a middle and at least two possible endings;
every goto must name an existing scene; every ending's effects must carry {"ending":"<its own id>"};
checks only use the six listed skills; effects only use journal/fact/hidden_fact/beads/item_give/
flag/quest_update/npc_rel/harm/heal/discover/ending. Use only material from the source."""


# ==========================================================================
# Milestone 3.6 — persistent conversion jobs, hierarchical full-book
# analysis, coverage metrics, manual editing and draft versioning.
# ==========================================================================

JOB_WINDOW_CHARS = 9000  # max characters per extraction window
JOB_SLICE_CHARS = 2500   # long chunks are sliced; every character is processed
JOB_STATUSES = ("queued", "analyzing", "bible", "generating", "validating",
                "review", "approved", "failed", "cancelled")
SCOPES = {
    "short": {"scenes": 6, "adventures": 1, "quests": 3, "endings": 3, "locations": 6},
    "multi_session": {"scenes": 10, "adventures": 2, "quests": 5, "endings": 4, "locations": 9},
    "extended": {"scenes": 16, "adventures": 3, "quests": 8, "endings": 5, "locations": 12},
}


class JobError(ValueError):
    pass


HEARTBEAT_SEC = 15       # lease touch cadence while a worker holds a job
LEASE_STALE_SEC = 90     # no heartbeat for this long -> the worker is lost


def _job_update(job_id: str, **fields) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE forge_jobs SET {sets}, updated_at=?, heartbeat=? WHERE id=?",
               (*fields.values(), utcnow(), utcnow(), job_id))


def job_view(job_id: str) -> dict:
    row = db.query_one("SELECT * FROM forge_jobs WHERE id=?", (job_id,))
    if not row:
        raise JobError("no such conversion job")
    d = dict(row)
    for k in ("coverage_json", "profile_json", "bible_json", "pack_json", "notes_json"):
        d[k.replace("_json", "")] = jloads(d.pop(k), {})
    return d


def list_jobs() -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT id, doc_id, mode, scope, status, stage, progress, error, draft_id,"
        " created_at, updated_at FROM forge_jobs ORDER BY updated_at DESC")]


def create_job(doc_id: str, mode: str = "faithful", scope: str = "short",
               transmit_approved: bool = False) -> dict:
    """Queue a conversion. One running job per document (duplicate guard)."""
    doc = library.doc_view(doc_id)
    if mode not in ("faithful", "rewrite", "expanded"):
        raise JobError("mode must be 'faithful', 'rewrite', or 'expanded'")
    try:
        target = forge_ai.resolve(transmit_approved=transmit_approved)
    except forge_ai.ForgeAiError as exc:
        raise JobError(str(exc)) from exc
    if scope not in SCOPES:
        raise JobError("scope must be short, multi_session or extended")
    running = db.query_one(
        "SELECT id FROM forge_jobs WHERE doc_id=? AND status IN"
        " ('queued','analyzing','bible','generating','validating')", (doc_id,))
    if running:
        raise JobError("that document already has a conversion in progress")
    job_id = new_id("job")
    now = utcnow()
    db.execute(
        "INSERT INTO forge_jobs (id, doc_id, mode, scope, status, stage, progress,"
        " created_at, updated_at) VALUES (?,?,?,?,'queued','queued',0,?,?)",
        (job_id, doc_id, mode, scope, now, now),
    )
    db.log_event("library", "forge_job_queued", {"job_id": job_id, "doc_id": doc_id,
                                                "model": target.get("model") or ""})
    forge_ai.pin_job(job_id, target)
    return job_view(job_id)


def cancel_job(job_id: str) -> dict:
    job_view(job_id)  # existence
    db.execute("UPDATE forge_jobs SET cancel=1 WHERE id=?", (job_id,))
    row = db.query_one("SELECT status FROM forge_jobs WHERE id=?", (job_id,))
    if row["status"] in ("queued", "analyzing", "bible", "generating", "validating"):
        _job_update(job_id, status="cancelled", stage="cancelled by the forge-master")
    return job_view(job_id)


def claim_next_job(worker: str) -> str | None:
    """Atomically claim the oldest queued job. The conditional UPDATE makes
    the lease single-winner: two workers can never hold the same job."""
    row = db.query_one(
        "SELECT id FROM forge_jobs WHERE status='queued' AND cancel=0"
        " ORDER BY created_at LIMIT 1")
    if not row:
        return None
    changed = db.execute_rc(
        "UPDATE forge_jobs SET status='running', owner=?, heartbeat=?,"
        " stage='claimed by worker', updated_at=? WHERE id=? AND status='queued'",
        (worker[:80], utcnow(), utcnow(), row["id"]),
    )
    if changed != 1:
        return None  # another worker won the lease
    return row["id"]


def _heartbeat_alive(job_id: str) -> bool:
    row = db.query_one("SELECT heartbeat FROM forge_jobs WHERE id=?", (job_id,))
    if not row or not row["heartbeat"]:
        return False
    from .mp import _iso_to_ts
    return (time.time() - _iso_to_ts(row["heartbeat"])) < LEASE_STALE_SEC


def recover_stale_jobs() -> int:
    """Detect interrupted conversions: a lease whose heartbeat expired (worker
    crashed or the process died). Completed artifacts are preserved — retry
    resumes from the last finished stage without re-reading the novel."""
    from .mp import _iso_to_ts
    rows = db.query(
        "SELECT id, heartbeat, updated_at FROM forge_jobs WHERE status='running'")
    recovered = 0
    for r in rows:
        stamp = r["heartbeat"] or r["updated_at"]
        stale = True
        if stamp:
            try:
                stale = (time.time() - _iso_to_ts(stamp)) > LEASE_STALE_SEC
            except Exception:
                stale = True
        if stale:
            _job_update(r["id"], status="failed",
                        stage="interrupted — retry to resume from the last completed stage",
                        error="worker lost (lease heartbeat expired); extracted work preserved")
            recovered += 1
    return recovered


def retry_job(job_id: str) -> dict:
    job = job_view(job_id)
    if job["status"] not in ("failed", "cancelled"):
        raise JobError("only failed or cancelled jobs can be retried")
    _job_update(job_id, status="queued", stage="queued", error=None, cancel=0,
                owner=None)
    return job_view(job_id)


def _check_cancel(job_id: str) -> None:
    row = db.query_one("SELECT cancel FROM forge_jobs WHERE id=?", (job_id,))
    if row and row["cancel"]:
        _job_update(job_id, status="cancelled", stage="cancelled")
        raise JobError("cancelled")


def _stage_structure(doc: dict) -> tuple[dict, dict]:
    """Stage A: document structure — chapters/sections and coverage counts."""
    rows = db.query("SELECT seq, heading FROM library_chunks WHERE doc_id=? ORDER BY seq",
                    (doc["id"],))
    chapters = []
    for r in rows:
        h = (r["heading"] or "").strip()
        if h and (chapters and h != chapters[-1]["heading"]):
            chapters.append({"heading": h[:120], "first_chunk": r["seq"], "last_chunk": r["seq"]})
        elif chapters:
            chapters[-1]["last_chunk"] = r["seq"]
        elif h:
            chapters.append({"heading": h[:120], "first_chunk": r["seq"], "last_chunk": r["seq"]})
    row = db.query_one("SELECT COALESCE(SUM(length(text)),0) AS s FROM library_chunks"
                       " WHERE doc_id=?", (doc["id"],))
    total_chars = int(row["s"] or 0)
    coverage = {
        "total_chunks": doc["n_chunks"],
        "total_characters": total_chars,
        "characters_processed": 0,
        "chapters": len(chapters),
        "chapter_list": [c["heading"] for c in chapters[:200]],
        "windows_planned": max(1, -(-total_chars // JOB_WINDOW_CHARS)),
        "calls_made": 0,
        "errors": 0,
    }
    return coverage, chapters


def _stage_extract(doc: dict, job_id: str, coverage: dict, notes: list[str],
                   cfg: dict) -> dict:
    """Stage B: local extraction over the ENTIRE document text — character-
    bounded windows, no prefix sampling. Long chapters are sliced across
    consecutive windows with nothing dropped; ordering is preserved; the
    consolidator deduplicates overlapping mentions. Coverage is reported
    honestly: chunks visited, characters processed, chapters fully analyzed,
    sections skipped (always 0), and failed windows."""
    profile: dict = {"characters": [], "locations": [], "factions": [],
                     "events": [], "items": [], "plot_points": [], "secrets": []}
    rows = db.query(
        "SELECT seq, heading, text, length(text) AS L FROM library_chunks"
        " WHERE doc_id=? ORDER BY seq", (doc["id"],))
    total_chars = sum(int(r["L"] or 0) for r in rows)
    heading_chars: dict[str, int] = {}
    heading_done: dict[str, int] = {}
    slices: list[dict] = []
    for r in rows:
        text = r["text"] or ""
        if not text:
            continue
        heading = (r["heading"] or f"chunk {r['seq']}")[:120]
        heading_chars[heading] = heading_chars.get(heading, 0) + len(text)
        n_slices = max(1, -(-len(text) // JOB_SLICE_CHARS))
        for i in range(n_slices):
            slices.append({
                "seq": r["seq"], "heading": heading,
                "part": f"{i + 1}/{n_slices}",
                "text": text[i * JOB_SLICE_CHARS:(i + 1) * JOB_SLICE_CHARS],
            })
    # group slices into character-bounded windows. A larger context may widen
    # a window; it never goes below the existing 9,000-character bound.
    window_limit = forge_ai.window_chars(cfg)
    windows: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    for s in slices:
        if cur and cur_chars + len(s["text"]) > window_limit:
            windows.append(cur)
            cur, cur_chars = [], 0
        cur.append(s)
        cur_chars += len(s["text"])
    if cur:
        windows.append(cur)
    coverage.update({
        "total_chunks": doc["n_chunks"],
        "chunks_visited": 0,
        "total_characters": total_chars,
        "characters_processed": 0,
        "windows_planned": len(windows),
        "windows_failed": 0,
        "failed_windows": [],
        "window_chars": window_limit,
        "extraction_successful": False,
        "sections_skipped": 0,
        "calls_made": 0,
        "errors": 0,
    })
    for wi, win in enumerate(windows, 1):
        _check_cancel(job_id)
        passage = "\n".join(
            f"[{s['heading']} (chunk {s['seq']}, part {s['part']})] {s['text']}"
            for s in win)
        ok = False
        try:
            text, meta = ai.chat([
                {"role": "system", "content": FORGE_EXTRACT_SYSTEM},
                {"role": "user", "content": f"SOURCE EXCERPT (part {wi} of "
                 f"{len(windows)}):\n\n{passage}"},
            ], cfg)
            data = ai.extract_json(text)
            if isinstance(data, dict):
                _merge_profile(profile, data)
                ok = True
                notes.append(f"window {wi}/{len(windows)}: extracted "
                             f"{len(data.get('characters', []))}c/{len(data.get('locations', []))}l")
            else:
                coverage["errors"] += 1
                reason = "model JSON contract missed; window kept raw"
                notes.append(f"window {wi}: {reason}")
                coverage["failed_windows"].append({"window": wi, "reason": reason})
        except Exception as exc:  # noqa: BLE001 — stage-level error reporting
            coverage["errors"] += 1
            reason = f"model unavailable ({str(exc)[:90]})"
            notes.append(f"window {wi}: {reason}")
            coverage["failed_windows"].append({"window": wi, "reason": reason[:160]})
            # the analysis continues; partial coverage is reported honestly
        coverage["calls_made"] += 1
        coverage["windows_failed"] = len(coverage["failed_windows"])
        for s in win:
            processed_chars = len(s["text"])
            coverage["characters_processed"] = coverage.get("characters_processed", 0) + processed_chars
            heading_done[s["heading"]] = heading_done.get(s["heading"], 0) + processed_chars
            if s["part"].split("/")[0] == "1" or True:
                pass
        coverage["chunks_visited"] = len({s["seq"] for w in windows[:wi] for s in w})
        _job_update(job_id, coverage_json=jdumps(coverage), profile_json=jdumps(profile),
                    stage=f"analyzing window {wi}/{len(windows)}",
                    progress=0.1 + 0.5 * (coverage["characters_processed"] / max(1, total_chars)),
                    notes_json=jdumps(notes[-40:]))
    chapters_full = sum(1 for h, tot in heading_chars.items()
                        if heading_done.get(h, 0) >= tot)
    coverage["chapters_fully_analyzed"] = chapters_full
    coverage["chapters"] = len(heading_chars)
    coverage["coverage_complete"] = (coverage["characters_processed"] >= total_chars
                                     and coverage["sections_skipped"] == 0)
    # A finished scan is not a successful extraction. Failed windows stay listed.
    coverage["extraction_successful"] = (coverage["windows_planned"] > 0
                                         and coverage["windows_failed"] == 0)
    _job_update(job_id, coverage_json=jdumps(coverage))
    return profile


def _windows_for(doc: dict, window_limit: int) -> list[list[dict]]:
    rows = db.query(
        "SELECT seq, heading, text FROM library_chunks WHERE doc_id=? ORDER BY seq",
        (doc["id"],))
    slices: list[dict] = []
    for r in rows:
        text = r["text"] or ""
        if not text:
            continue
        heading = (r["heading"] or f"chunk {r['seq']}")[:120]
        n_slices = max(1, -(-len(text) // JOB_SLICE_CHARS))
        for i in range(n_slices):
            slices.append({
                "seq": r["seq"], "heading": heading,
                "part": f"{i + 1}/{n_slices}",
                "text": text[i * JOB_SLICE_CHARS:(i + 1) * JOB_SLICE_CHARS],
            })
    windows: list[list[dict]] = []
    cur: list[dict] = []
    cur_chars = 0
    limit = max(JOB_WINDOW_CHARS, int(window_limit or JOB_WINDOW_CHARS))
    for s in slices:
        if cur and cur_chars + len(s["text"]) > limit:
            windows.append(cur)
            cur, cur_chars = [], 0
        cur.append(s)
        cur_chars += len(s["text"])
    if cur:
        windows.append(cur)
    return windows


def retry_failed_windows(job_id: str) -> dict:
    """Re-run only the extraction windows that failed. Successful windows stay."""
    job = job_view(job_id)
    if not job.get("profile"):
        raise JobError("there is no extracted profile yet — retry the whole job instead")
    coverage = dict(job.get("coverage") or {})
    failed = list(coverage.get("failed_windows") or [])
    if not failed:
        raise JobError("no failed extraction windows to retry")
    try:
        cfg = forge_ai.cfg_for_job(job_id)
    except forge_ai.ForgeAiError as exc:
        raise JobError(str(exc)) from exc
    doc = library.doc_view(job["doc_id"])
    windows = _windows_for(doc, int(coverage.get("window_chars") or JOB_WINDOW_CHARS))
    profile = job["profile"]
    for key in ("characters", "locations", "factions", "events", "items", "plot_points", "secrets"):
        profile.setdefault(key, [])
    notes = list(job.get("notes") or [])
    still = []
    for item in failed:
        wi = int(item.get("window") or 0)
        if wi < 1 or wi > len(windows):
            still.append({"window": wi, "reason": "window index no longer matches the document"})
            continue
        win = windows[wi - 1]
        passage = "\n".join(
            f"[{s['heading']} (chunk {s['seq']}, part {s['part']})] {s['text']}" for s in win)
        try:
            text, _meta = ai.chat([
                {"role": "system", "content": FORGE_EXTRACT_SYSTEM},
                {"role": "user", "content": f"SOURCE EXCERPT (part {wi} of {len(windows)}):\n\n{passage}"},
            ], cfg)
            data = ai.extract_json(text)
        except ai.AiError as exc:
            still.append({"window": wi, "reason": str(exc)[:160]})
            notes.append(f"retry window {wi}: still failed ({str(exc)[:80]})")
            continue
        if not isinstance(data, dict):
            still.append({"window": wi, "reason": "model JSON contract missed"})
            notes.append(f"retry window {wi}: model JSON contract missed")
            continue
        _merge_profile(profile, data)
        notes.append(f"retry window {wi}: extracted")
    coverage["failed_windows"] = still
    coverage["windows_failed"] = len(still)
    coverage["errors"] = len(still)
    coverage["extraction_successful"] = (coverage.get("windows_planned", 0) > 0 and not still)
    _job_update(job_id, coverage_json=jdumps(coverage), profile_json=jdumps(profile),
                notes_json=jdumps(notes[-40:]),
                stage=("extraction windows recovered" if not still
                       else f"{len(still)} extraction window(s) still failed"))
    return job_view(job_id)


_ALIAS_STOP = {"the", "a", "an", "of", "mr", "mrs", "ms", "dr", "count", "lady", "sir"}


def _stage_consolidate(profile: dict) -> dict:
    """Stage C: deduplicate entities, merge aliases, build chronology, flag
    contradictions. Deterministic — no model calls."""
    def norm(name: str) -> str:
        words = [w for w in re.split(r"\W+", (name or "").lower()) if w and w not in _ALIAS_STOP]
        return " ".join(words[-2:]) if words else (name or "").lower()

    def merge(key: str) -> dict:
        buckets: dict[str, dict] = {}
        aliases: dict[str, str] = {}
        merged: list[dict] = []
        for i, item in enumerate(profile.get(key, [])):
            nm = (item.get("name") or "").strip()
            if not nm:
                continue
            canon = norm(nm)
            if canon and canon not in buckets and any(canon in norm(b.get("name", "")) or norm(b.get("name", "")) in canon for b in buckets.values() if b.get("name")):
                # alias of an existing entity: attach
                target = next(k for k, b in buckets.items()
                              if canon in norm(b.get("name", "")) or norm(b.get("name", "")) in canon)
                aliases[nm] = buckets[target]["name"]
                continue
            if canon in buckets:
                b = buckets[canon]
                for f, v in item.items():
                    if v and f != "name" and not b.get(f):
                        b[f] = v
                b["seen_windows"] = sorted(set(b.get("seen_windows", [0]) + [i]))
                continue
            item = dict(item)
            item["seen_windows"] = [i]
            item["first_window"] = i
            buckets[canon] = item
            merged.append(item)
        profile[key] = merged
        profile[f"{key}_aliases"] = aliases
        return buckets

    for key in ("characters", "locations", "factions", "items"):
        merge(key)
    # chronology: plot points keep their window order; conflicts recorded
    conflicts = []
    seen_names: dict[str, set] = {}
    for c in profile.get("characters", []):
        nm = (c.get("name") or "").lower()
        role = (c.get("role") or "").lower()
        if nm in seen_names and role and role not in seen_names[nm]:
            conflicts.append(f"{c.get('name')}: described as both '{role}' and "
                             f"'{next(iter(seen_names[nm])) or 'something else'}' in the source")
        seen_names.setdefault(nm, set()).add(role)
    profile["contradictions"] = conflicts[:20]
    return profile


def _stage_bible(doc: dict, job_id: str, profile: dict, mode: str,
                 notes: list[str], cfg: dict) -> dict:
    """Stage D: the world bible — canonical facts, inferred material, secrets,
    relationships, chronology, and how the story ENDS (so endings are grounded)."""
    _check_cancel(job_id)
    material = json.dumps(profile, ensure_ascii=False)[:15000]
    messages = [
        {"role": "system", "content": FORGE_BIBLE_SYSTEM},
        {"role": "user", "content": f"SOURCE: {doc['title']} by {doc['author'] or 'unknown'}\n"
         f"MODE: {_mode_line(mode)}\n"
         f"CONSOLIDATED MATERIAL:\n{material}"},
    ]
    text, meta = ai.chat(messages, cfg)
    bible = ai.extract_json(text)
    if not isinstance(bible, dict):
        raise JobError("the model did not return the world-bible JSON contract")
    bible.setdefault("contradictions", profile.get("contradictions", []))
    notes.append(f"world bible: {len(bible.get('canonical_facts', []))} canonical facts, "
                 f"{len(bible.get('secrets', []))} secrets, "
                 f"ending grounded: {bool(bible.get('ending_summary'))}")
    _job_update(job_id, bible_json=jdumps(bible), notes_json=jdumps(notes[-40:]))
    return bible


FORGE_BIBLE_SYSTEM = """You are the Campaign Forge's analyst of record. Return ONE JSON object
(no markdown, no prose) shaped exactly like this:
{"setting": "<=60 words", "canonical_facts": ["things the source establishes beyond doubt"],
 "inferred_facts": ["reasonable inferences, marked as inferred"],
 "characters": [{"name":"", "role":"", "desc":"<=50 words", "arc":"", "status":"", "aliases":[]}],
 "relationships": [["A", "B", "<=12 words"]],
 "timeline": [{"when":"", "what":"<=25 words"}],
 "factions": [{"name":"", "goals":"<=25 words"}],
 "secrets": ["hidden truths a GM may hold"],
 "ending_summary": "<=60 words: how the source story ENDS",
 "divergence_points": ["where players could change the story"]}
Use ONLY the supplied material. The ending_summary is mandatory — a campaign that never
examined the ending of its source is invalid."""


def _stage_generate(doc: dict, job_id: str, profile: dict, bible: dict,
                    mode: str, scope: str, notes: list[str], cfg: dict) -> dict:
    """Stage E: campaign generation from the whole-source bible."""
    _check_cancel(job_id)
    _job_update(job_id, stage="generating world", progress=0.7)
    world = _world_from_bible(doc, bible, profile, scope)
    _check_cancel(job_id)
    _job_update(job_id, stage="generating adventure", progress=0.8)
    adventure = _adventure_from_bible(bible, profile, mode, scope, cfg, job_id)
    pack = _assemble_pack(doc, world, adventure, mode)
    pack["forge_scope"] = scope
    pack["source_coverage"] = {
        "chunks": _job_cov(job_id),
        "mode": mode,
    }
    if mode == "rewrite":
        pack["forge_mode"] = "rewrite"
        pack["rewrite_note"] = ("The original story is the starting point; "
                                "players' choices change its history.")
    elif mode == "expanded":
        pack["forge_mode"] = "expanded"
        pack["expanded_note"] = ("The book supplies the world. The adventures are new, "
                                 "and the source ending stays intact.")
    notes.append(f"generated '{pack.get('name')}' with "
                 f"{len(list(pack['adventures'][0]['scenes'].values()))} scenes")
    _job_update(job_id, notes_json=jdumps(notes[-40:]))
    return pack


def _job_cov(job_id: str) -> dict:
    row = db.query_one("SELECT coverage_json FROM forge_jobs WHERE id=?", (job_id,))
    return jloads(row["coverage_json"], {}) if row else {}


def _world_from_bible(doc: dict, bible: dict, profile: dict, scope: str) -> dict:
    lim = SCOPES[scope]["locations"]
    locs = []
    for i, loc in enumerate((bible.get("locations") or profile.get("locations", []))[:lim]):
        locs.append({"id": _slug(loc.get("id") or loc.get("name") or f"loc{i}"),
                     "name": loc.get("name", ""), "short": (loc.get("desc") or loc.get("short", ""))[:120],
                     "desc": (loc.get("desc") or loc.get("short", ""))[:700], "known": True,
                     "flavor": [], "rest": {"vigor": 2, "nerve": 2}})
    npcs = [{"id": _slug(c.get("id") or c.get("name") or "npc"), "name": c.get("name", ""),
             "role": c.get("role", ""), "location": _slug((profile.get("locations") or [{}])[0].get("name", "") or ""),
             "desc": (c.get("desc") or "")[:400], "arc": c.get("arc", ""),
             "greeting": "", "rumors": []}
            for c in (bible.get("characters") or profile.get("characters", []))[:10]]
    items = [{"id": _slug(i.get("id") or i.get("name") or "item"), "name": i.get("name", ""),
              "kind": "trinket", "desc": (i.get("desc") or "")[:220]}
             for i in profile.get("items", [])[:12]]
    omens = [
        {"id": "om1", "kind": "edge", "title": "The Pattern", "text": "Connections others miss are plain to you.", "boost": "notice"},
        {"id": "om2", "kind": "edge", "title": "Source-Bound", "text": "You sense when the story's current pulls.", "boost": "lore"},
        {"id": "om3", "kind": "turn", "title": "Steady Heart", "text": "For one moment, fate moves aside.", "boost": "endure"},
        {"id": "om4", "kind": "complication", "title": "Wrong Thread", "text": "The story resists your changes, briefly."},
    ]
    raw_name = (bible.get("setting", "").split(".")[0] or doc["title"])
    raw_name = " ".join(raw_name.split()[:6]) if len(raw_name.split()) > 8 else raw_name
    return {"name": (raw_name[:60] or doc["title"]),
            "summary": (bible.get("setting") or doc["title"])[:220],
            "genre_tags": ["forged", doc.get("doc_type", "novel")],
            "gm_style": "Grounded in the full source; the world bible rules continuity.",
            "locations": locs, "npcs": npcs, "items": items, "omens": omens,
            "intro_facts": (bible.get("canonical_facts") or [])[:8]}


def _adventure_from_bible(bible: dict, profile: dict, mode: str, scope: str,
                          cfg: dict, job_id: str) -> dict:
    _check_cancel(job_id)
    sc = SCOPES[scope]
    mode_line = _mode_line(mode)
    messages = [
        {"role": "system", "content": FORGE_ADVENTURE_SYSTEM +
         f"\nSCOPE: {sc['scenes']} scenes in {sc['adventures']} adventure(s), {sc['quests']} quests, "
         f"{sc['endings']} endings. Do not pad with filler scenes." +
         (f"\nEDITOR GUIDANCE: {_job_notes(job_id)[-1][:300]}" if False else "")},
        {"role": "user", "content": f"MODE: {mode_line}\n"
         f"WORLD BIBLE: {json.dumps(bible, ensure_ascii=False)[:9000]}\n"
         f"PLOT EVENTS: {json.dumps(profile.get('plot_points', [])[:30])}\n"
         f"SECRETS: {json.dumps(bible.get('secrets', profile.get('secrets', []))[:12])}\n"
         f"THE SOURCE ENDS LIKE THIS: {bible.get('ending_summary', 'unknown')}"},
    ]
    text, meta = ai.chat(messages, cfg)
    adventure = ai.extract_json(text)
    if not isinstance(adventure, dict):
        raise JobError("the model did not return the adventure JSON contract")
    return adventure


def _job_notes(job_id: str) -> list:
    row = db.query_one("SELECT notes_json FROM forge_jobs WHERE id=?", (job_id,))
    return jloads(row["notes_json"], []) if row else []


def run_job(job_id: str, worker: str = "manual") -> dict:
    """Execute (or resume) a conversion job under a worker lease. Resumable at
    stage granularity: completed artifacts (profile, bible) are kept and their
    stages skipped."""
    from . import ai as _ai
    row = db.query_one("SELECT status, owner, heartbeat FROM forge_jobs WHERE id=?",
                       (job_id,))
    if row and row["status"] == "queued":
        claimed = claim_next_job(worker)
        if claimed != job_id:
            return job_view(job_id)  # another worker won it
    elif row and row["status"] == "running":
        if _heartbeat_alive(job_id) and row["owner"] not in (None, "", worker):
            raise JobError("another worker holds the lease on this job")
        _job_update(job_id, owner=worker)  # adopt an abandoned lease
    import threading as _threading
    stop_beat = {"flag": False}

    def _beat():
        while not stop_beat["flag"]:
            if stop_beat["flag"]:
                break
            try:
                db.execute("UPDATE forge_jobs SET heartbeat=? WHERE id=? AND status='running'",
                           (utcnow(), job_id))
            except Exception:
                pass
            stop_beat["flag"] = stop_beat["flag"] or False
            _time.sleep(HEARTBEAT_SEC)

    import time as _time
    beat = _threading.Thread(target=_beat, name="sm-job-heartbeat", daemon=True)
    beat.start()
    try:
        return _run_job_inner(job_id, worker)
    finally:
        stop_beat["flag"] = True


def _run_job_inner(job_id: str, worker: str = "manual") -> dict:
    from . import ai as _ai
    job = job_view(job_id)
    doc = library.doc_view(job["doc_id"])
    try:
        cfg = forge_ai.cfg_for_job(job_id)
    except forge_ai.ForgeAiError as exc:
        _job_update(job_id, status="failed", stage="model unavailable", error=str(exc)[:400])
        return job_view(job_id)
    notes = job["notes"]
    try:
        coverage, _ = _stage_structure(doc)
        profile = job["profile"]
        if job["status"] in ("queued", "running") and not profile:
            _job_update(job_id, status="running", stage="mapping the document structure",
                        progress=0.05, coverage_json=jdumps(coverage))
        if not profile:
            profile = _stage_extract(doc, job_id, coverage, notes, cfg)
            _job_update(job_id, profile_json=jdumps(profile))
        else:
            notes.append("resume: extraction stage skipped (profile preserved)")
        _check_cancel(job_id)
        _job_update(job_id, stage="consolidating entities", progress=0.62)
        profile = _stage_consolidate(profile)
        _job_update(job_id, profile_json=jdumps(profile))
        bible = job["bible"]
        if not bible:
            _job_update(job_id, status="bible", stage="building the world bible",
                        progress=0.66)
            bible = _stage_bible(doc, job_id, profile, job["mode"], notes, cfg)
        else:
            notes.append("resume: bible stage skipped (bible preserved)")
        _check_cancel(job_id)
        _job_update(job_id, status="generating", stage="generating the campaign",
                    progress=0.7)
        pack = job["pack"]
        if not pack:
            pack = _stage_generate(doc, job_id, profile, bible, job["mode"],
                                   job["scope"], notes, cfg)
            _job_update(job_id, pack_json=jdumps(pack))
        _check_cancel(job_id)
        _job_update(job_id, status="validating", stage="validating the draft",
                    progress=0.92)
        pack = _repair_pack(pack, doc)
        problems = validate_pack(pack)
        _job_update(job_id, pack_json=jdumps(pack), status="review", stage="ready for review",
                    progress=1.0, error=None)
        if problems:
            _job_update(job_id, notes_json=jdumps(notes + ["validation: " + "; ".join(problems)]))
        flow = validate_flow(pack)
        _job_update(job_id, notes_json=jdumps((jloads(db.query_one(
            "SELECT notes_json FROM forge_jobs WHERE id=?", (job_id,))["notes_json"], []))
            + [f"flow: {len(flow)} structural findings"]))
    except JobError as exc:
        if "cancelled" in str(exc):
            return job_view(job_id)
        _job_update(job_id, status="failed", stage=str(exc)[:160], error=str(exc)[:400])
    except ai.AiError as exc:
        # keep completed stages; the job can be retried without redoing them
        _job_update(job_id, status="failed", stage=f"model unavailable at stage '{job['stage']}'",
                    error=str(exc)[:400])
    return job_view(job_id)


def approve_job(job_id: str) -> dict:
    job = job_view(job_id)
    if job["status"] != "review":
        raise JobError("only jobs that reached review can be approved")
    pack = job["pack"]
    problems = validate_pack(pack)
    if problems:
        raise JobError("cannot approve — the draft still has problems: " + "; ".join(problems[:6]))
    db.execute("INSERT INTO forge_drafts (id, doc_id, mode, status, pack_json, profile_json,"
               " notes_json, created_at, updated_at) VALUES (?,?,?, 'draft', ?, ?, ?, ?, ?)",
               (new_id("fge"), job["doc_id"], job["mode"], jdumps(pack),
                jdumps(job["profile"]), jdumps(["from job " + job_id]), utcnow(), utcnow()))
    draft_id = db.query_one("SELECT id FROM forge_drafts WHERE doc_id=? ORDER BY updated_at DESC"
                            " LIMIT 1", (job["doc_id"],))["id"]
    _save_revision(draft_id, "approved from job")
    res = approve_draft(draft_id)
    _job_update(job_id, status="approved", draft_id=draft_id, stage="approved and installed")
    return {**res, "draft_id": draft_id}


# ==========================================================================
# Draft editing, versioning, and the structural flow validator
# ==========================================================================

def _save_revision(draft_id: str, note: str) -> int:
    row = db.query_one("SELECT pack_json FROM forge_drafts WHERE id=?", (draft_id,))
    seq_row = db.query_one("SELECT COALESCE(MAX(seq),0)+1 AS s FROM forge_revisions WHERE draft_id=?",
                           (draft_id,))
    seq = int(seq_row["s"])
    db.execute("INSERT INTO forge_revisions (id, draft_id, seq, pack_json, note, created_at)"
               " VALUES (?,?,?,?,?,?)",
               (new_id("rev"), draft_id, seq, row["pack_json"], note[:160], utcnow()))
    return seq


def edit_draft(draft_id: str, ops: list[dict], note: str = "") -> dict:
    """Manual editing: deterministic path operations on the draft pack.
    Supported ops: set / add / update / remove. Every save records a revision."""
    draft = draft_view(draft_id)
    if draft["status"] == "approved":
        raise ForgeError("this draft is approved — duplicate it to iterate further")
    pack = json.loads(json.dumps(draft["pack"]))  # deep copy
    applied = 0
    for op in ops or []:
        kind = op.get("op")
        path = [p for p in str(op.get("path", "")).split(".") if p]
        value = op.get("value")
        if kind == "set" and path:
            _pack_set(pack, path, value)
            applied += 1
        elif kind == "add" and path:
            container = _pack_get(pack, path[:-1]) if len(path) > 1 else pack
            key = path[-1]
            if isinstance(container, list):
                container.append(value)
                applied += 1
            elif isinstance(container, dict):
                existing = container.get(key)
                if isinstance(existing, list):
                    existing.append(value)  # append into the collection
                else:
                    container[key] = value if existing is None else value
                applied += 1
        elif kind == "update" and path:
            target = _pack_get(pack, path)
            if isinstance(target, dict) and isinstance(value, dict):
                target.update(value)
                applied += 1
        elif kind == "remove" and path:
            container = _pack_get(pack, path[:-1]) if len(path) > 1 else pack
            key = path[-1]
            if isinstance(container, list):
                container = [x for x in container if json.dumps(x) != json.dumps(value)]
                _pack_set(pack, path[:-1], container)
                applied += 1
            elif isinstance(container, dict):
                container.pop(key, None)
                applied += 1
    if draft.get("doc_id"):
        doc = library.doc_view(draft["doc_id"])
    else:  # homebrew worlds are not bound to a library document
        doc = {"id": "", "title": pack.get("name", "homebrew"), "author": "",
               "doc_type": "original", "license": "Original work — the creators'"}
    pack = _repair_pack(pack, doc)
    problems = validate_pack(pack)
    db.execute("UPDATE forge_drafts SET pack_json=?, updated_at=? WHERE id=?",
               (jdumps(pack), utcnow(), draft_id))
    # the revision records the NEW state of the draft
    seq = _save_revision(draft_id, note or f"manual edit ({applied} ops)")
    return {**draft_view(draft_id), "applied": applied, "revision": seq,
            "problems": problems}


def _pack_get(pack: dict, path: list):
    cur = pack
    for p in path:
        if isinstance(cur, list):
            cur = cur[int(p)]
        elif isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _pack_set(pack: dict, path: list, value) -> None:
    cur = pack
    for p in path[:-1]:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            nxt = cur.get(p)
            if nxt is None and p.isdigit() is False:
                cur[p] = {}
            cur = cur[p] if p in cur else cur
    last = path[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def draft_history(draft_id: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT seq, note, created_at FROM forge_revisions WHERE draft_id=? ORDER BY seq",
        (draft_id,))]


def restore_revision(draft_id: str, seq: int) -> dict:
    rev = db.query_one("SELECT pack_json FROM forge_revisions WHERE draft_id=? AND seq=?",
                       (draft_id, seq))
    if not rev:
        raise ForgeError("no such revision")
    _save_revision(draft_id, f"restored revision {seq}")
    db.execute("UPDATE forge_drafts SET pack_json=?, updated_at=? WHERE id=?",
               (rev["pack_json"], utcnow(), draft_id))
    return draft_view(draft_id)


def compare_revisions(draft_id: str, a: int, b: int) -> dict:
    ra = db.query_one("SELECT pack_json FROM forge_revisions WHERE draft_id=? AND seq=?", (draft_id, a))
    rb = db.query_one("SELECT pack_json FROM forge_revisions WHERE draft_id=? AND seq=?", (draft_id, b))
    if not ra or not rb:
        raise ForgeError("no such revisions")
    pa, pb = jloads(ra["pack_json"], {}), jloads(rb["pack_json"], {})
    def keys(d, prefix=""):
        out = {}
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, (dict, list)):
                    out.update(keys(v, prefix + k + "."))
                else:
                    out[prefix + k] = v
        elif isinstance(d, list):
            for i, v in enumerate(d):
                out.update(keys(v, prefix + str(i) + "."))
        return out
    ka, kb = keys(pa), keys(pb)
    changed = [k for k in ka if k in kb and ka[k] != kb[k]]
    added = [k for k in kb if k not in ka]
    removed = [k for k in ka if k not in kb]
    return {"changed": changed[:60], "added": added[:60], "removed": removed[:60],
            "n_changed": len(changed), "n_added": len(added), "n_removed": len(removed)}


def duplicate_draft(draft_id: str) -> dict:
    draft = draft_view(draft_id)
    if draft["status"] == "approved":
        draft["pack"]["id"] = _slug(draft["pack"]["id"]) + "_copy_" + new_id("x")[-6:]
        draft["pack"]["name"] = draft["pack"].get("name", "") + " (copy)"
    new_id_ = new_id("fge")
    db.execute("INSERT INTO forge_drafts (id, doc_id, mode, status, pack_json, profile_json,"
               " notes_json, created_at, updated_at) VALUES (?,?,?,'draft',?,?,?,?,?)",
               (new_id_, draft["doc_id"], draft["mode"], jdumps(draft["pack"]),
                jdumps(draft["profile"]), jdumps(["duplicated from " + draft_id]),
                utcnow(), utcnow()))
    _save_revision(new_id_, "duplicated")
    return draft_view(new_id_)


def export_draft(draft_id: str) -> dict:
    draft = draft_view(draft_id)
    return {"draft_id": draft_id, "mode": draft["mode"], "pack": draft["pack"],
            "exported_at": utcnow()}


def validate_flow(pack: dict) -> list[str]:
    """Structural flow analysis: unreachable scenes, broken ending paths,
    circular deadlocks, missing items, invalid effects. Findings are advisory;
    hard errors still block approval through validate_pack."""
    findings: list[str] = []
    for adv in pack.get("adventures", []):
        scenes = adv.get("scenes", {})
        sids = list(scenes.keys())
        entry = adv.get("entry")
        edges: dict[str, list[str]] = {}
        ending_ids = set(adv.get("endings", {}).keys())
        for sid, sc in scenes.items():
            dests = []
            for c in sc.get("choices", []):
                for dest in (c.get("goto"), (c.get("on_pass") or {}).get("goto"),
                             (c.get("on_fail") or {}).get("goto")):
                    if dest:
                        if dest in sids:
                            dests.append(dest)
                        elif dest in ending_ids:
                            dests.append("__end__")
                        else:
                            findings.append(f"missing scene target '{dest}' from '{sid}'")
                eff = (c.get("effects") or {})
                for branch in (c.get("on_pass"), c.get("on_fail")):
                    if isinstance(branch, dict):
                        eff.update(branch.get("effects") or {})
                if eff.get("ending"):
                    dests.append("__end__")
                ig = eff.get("item_give")
                if ig and not any(it["id"] == ig for it in pack.get("items", [])):
                    findings.append(f"choice in '{sid}' grants unknown item '{ig}'")
            edges[sid] = sorted(set(dests))
        # reachability from entry
        seen = {entry}
        stack = [entry]
        while stack:
            node = stack.pop()
            for nxt in edges.get(node, []):
                if nxt == "__end__":
                    continue
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        for sid in sids:
            if sid not in seen:
                findings.append(f"scene '{sid}' is unreachable from the entry")
        # ending reachability: any path from entry to an ending?
        end_reachable = seen and any(
            "__end__" in edges.get(s, []) for s in seen)
        if not end_reachable:
            findings.append("no scene reachable from the entry leads to an ending")
        # circular deadlock: a strongly-connected component with no way out to
        # an ending or any scene outside it
        for sid in sids:
            comp = {sid}
            changed = True
            while changed:
                changed = False
                for s in list(comp):
                    for nxt in edges.get(s, []):
                        if nxt != "__end__" and nxt in comp:
                            continue
                changed = False  # single-node cycle check only (cheap + useful)
            if edges.get(sid) == [sid] and sid != entry:
                findings.append(f"scene '{sid}' only loops to itself — a deadlock")
    return findings


# ==========================================================================
# Milestone 3.6 (steering update) — collaborative worldbuilding on the SAME
# universal Forge. No separate homebrew system: original worlds are drafts
# like any other, validated by the same engine-authoritative gates, installed
# into the same Library. Identity comes from the existing multiplayer
# session; no new accounts, tokens, or access systems.
# ==========================================================================

HOME_SKELETON = {
    "id": "", "name": "", "summary": "", "genre_tags": ["homebrew"],
    "version": 1,
    "gm_style": "A world your table wrote together.",
    "archetypes": [
        {"id": "seeker", "name": "Seeker", "desc": "Drawn to what the world hides.",
         "attributes": {"lore": 3, "notice": 2, "bind": 1, "endure": 1, "fight": 1}},
        {"id": "warden", "name": "Warden", "desc": "Stands between the party and the dark.",
         "attributes": {"endure": 3, "fight": 2, "notice": 1, "bind": 1, "lore": 1}},
        {"id": "speaker", "name": "Speaker", "desc": "Words open doors that keys cannot.",
         "attributes": {"bind": 3, "lore": 2, "notice": 1, "endure": 1, "fight": 1}},
    ],
    "hub_location": "hub",
    "locations": [{"id": "hub", "name": "The Crossroads", "short": "Where every story meets.",
                   "desc": "A meeting place waiting for its world to grow around it.",
                   "known": True, "flavor": [], "rest": {"vigor": 2, "nerve": 2}}],
    "npcs": [], "items": [], "omens": [
        {"id": "om1", "kind": "edge", "title": "Maker's Eye", "text": "You see the seams of the story.", "boost": "notice"},
        {"id": "om2", "kind": "turn", "title": "Steady Heart", "text": "For one moment, fate moves aside.", "boost": "endure"},
        {"id": "om3", "kind": "complication", "title": "Loose Thread", "text": "The world resists, briefly."},
    ],
    "intro_quests": [], "gm_secrets": [], "secret_authors": {},
    "adventures": [{"id": "first_tale", "title": "The First Tale", "entry": "opening",
                    "scenes": {"opening": {"id": "opening", "title": "Opening", "brief": "Where the tale begins.",
                                           "intro": "The world opens before you.",
                                           "choices": [{"id": "set_out", "label": "Set out",
                                                        "goto": "crossroads_scene"}]},
                               "crossroads_scene": {"id": "crossroads_scene", "title": "At the Crossroads",
                                                    "brief": "A choice of roads.",
                                                    "intro": "Two roads diverge.",
                                                    "choices": [{"id": "return", "label": "Return to the hub",
                                                                 "effects": {"ending": "hub_ending"}}]}},
                    "endings": {"hub_ending": {"text": "You return to the Crossroads; the world remembers you.",
                                               "return_location": "hub",
                                               "effects": {"ending": "hub_ending"},
                                               "consequence": "The tale begins."}}}],
}


def create_collab(name: str, creator_id: str, creator_name: str,
                  from_campaign_id: str | None = None) -> dict:
    """Open a collaborative world draft. Same Forge, same packs, same gates.
    from_campaign_id seeds the draft from an existing campaign's pack
    (imported/private material stays private — it is never published)."""
    from . import gm as _gm, worldpacks as _wp
    import copy
    if not str(name or "").strip():
        raise ForgeError("the world needs a name")
    draft_id = new_id("fge")
    now = utcnow()
    if from_campaign_id:
        camp = _gm.get_campaign(from_campaign_id)
        if not camp:
            raise ForgeError("no such campaign to build from")
        pack = _wp.load_pack(camp["pack_id"])
        pack = json.loads(json.dumps(pack))
        pack["name"] = str(name).strip()[:60]
        pack["forge_mode"] = "homebrew"
        doc_id = ""
        lic = pack.get("license", {}) or {}
        private_source = bool(lic.get("private") or lic.get("doc_private"))
    else:
        pack = copy.deepcopy(HOME_SKELETON)
        pack["id"] = _slug(name) + "_" + new_id("h")[-6:]
        pack["name"] = str(name).strip()[:60]
        pack["summary"] = f"A collaborative world forged by {creator_name} and company."
        doc_id = ""
        private_source = False
    pack.setdefault("secret_authors", {})
    db.execute(
        "INSERT INTO forge_drafts (id, doc_id, mode, status, pack_json, profile_json,"
        " notes_json, owner, collab_json, created_at, updated_at)"
        " VALUES (?,?,'homebrew','draft',?, '[]', ?, ?, ?, ?, ?)",
        (draft_id, doc_id, jdumps(pack), jdumps(["collaborative world opened by " + creator_name]),
         creator_id, jdumps({"creator": creator_id, "creator_name": creator_name,
                             "from_campaign_id": from_campaign_id or None,
                             "private_source": private_source}),
         now, now),
    )
    _save_revision(draft_id, "world opened")
    return collab_view(draft_id, creator_id, is_creator=True)


def _head_rev(draft_id: str) -> int:
    row = db.query_one("SELECT COALESCE(MAX(seq),0) AS s FROM forge_revisions WHERE draft_id=?",
                       (draft_id,))
    return int(row["s"])


def _is_creator(draft_row, player_id: str) -> bool:
    collab = jloads(draft_row.get("collab_json") or "{}", {})
    return player_id and (player_id == draft_row.get("owner")
                          or player_id == collab.get("creator"))


def collab_view(draft_id: str, viewer_id: str = "", is_creator: bool | None = None) -> dict:
    """The workshop view. Spoiler boundary: collaborators see their own GM
    secrets and shared material — never another contributor's hidden work."""
    row = db.query_one("SELECT * FROM forge_drafts WHERE id=?", (draft_id,))
    if not row:
        raise ForgeError("no such collaborative draft")
    row = dict(row)
    creator = is_creator if is_creator is not None else _is_creator(row, viewer_id)
    pack = jloads(row["pack_json"], {})
    authors = pack.get("secret_authors", {}) or {}
    visible_secrets = []
    for s in pack.get("gm_secrets", []):
        # Secrets with unknown authorship stay creator-only. An absent
        # author is not evidence that the creator intended to share it.
        if creator or authors.get(s) in (viewer_id, "shared"):
            visible_secrets.append(s)
    pack = dict(pack)
    pack["gm_secrets"] = visible_secrets
    if not creator:
        pack.pop("secret_authors", None)
    props = []
    for p in db.query("SELECT * FROM forge_contrib WHERE draft_id=? ORDER BY created_at",
                      (draft_id,)):
        p = dict(p)
        ops = jloads(p["ops_json"], [])
        if not creator and p["author_id"] != viewer_id:
            # Redact BOTH the serialized and parsed operations. Previously
            # ops_json was replaced, but the response exposed the original
            # `ops` list; notes could also reveal a secret. Treat any nested
            # secret path as private, and hide the whole mixed proposal so a
            # neighbouring public operation cannot expose its private value.
            secret_fields = {"gm_secrets", "secret_authors"}
            touches_secret = any(
                isinstance(op, dict) and
                bool(set(str(op.get("path", "")).split(".")) & secret_fields)
                for op in ops
            )
            if touches_secret:
                ops = [{"op": "redacted", "path": "gm_secrets", "value": "[hidden]"}]
                p["note"] = "[hidden proposal — GM knowledge]"
        p["ops"] = ops
        p.pop("ops_json")
        p.pop("conflicts_json")
        p["conflicts"] = []
        props.append(p)
    return {"draft_id": draft_id, "status": row["status"], "mode": row["mode"],
            "pack": pack, "proposals": props, "head_rev": _head_rev(draft_id),
            "you_are_creator": bool(creator),
            "collab": jloads(row.get("collab_json") or "{}", {})}


def _touched_paths(ops: list[dict]) -> set:
    out = set()
    for op in ops or []:
        path = str(op.get("path", ""))
        out.add(path.split(".")[0])
    return out


def _changed_paths_between(draft_id: str, base_rev: int, head_rev: int) -> set:
    """Union of top-level paths changed across revisions after base_rev."""
    out = set()
    for seq in range(base_rev + 1, head_rev + 1):
        row = db.query_one("SELECT pack_json FROM forge_revisions WHERE draft_id=? AND seq=?",
                           (draft_id, seq))
        prev = db.query_one("SELECT pack_json FROM forge_revisions WHERE draft_id=? AND seq=?",
                            (draft_id, seq - 1))
        if not row or not prev:
            continue
        diff = compare_revisions(draft_id, seq - 1, seq) if False else None
        ka = set(_flatten_keys(jloads(prev["pack_json"], {})))
        kb = set(_flatten_keys(jloads(row["pack_json"], {})))
        out |= {k.split(".")[0] for k in (kb - ka) | (ka - kb)}
        out |= {k.split(".")[0] for k in ka & kb
                if _flat_get(jloads(prev["pack_json"], {}), k) != _flat_get(jloads(row["pack_json"], {}), k)}
    return out


def _flatten_keys(d, prefix=""):
    out = set()
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                out |= _flatten_keys(v, prefix + str(k) + ".")
            else:
                out.add(prefix + str(k))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out |= _flatten_keys(v, prefix + str(i) + ".")
    return out


def _flat_get(d, key):
    cur = d
    for p in key.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def contrib_propose(draft_id: str, author_id: str, author_name: str,
                    ops: list[dict], note: str = "", base_rev: int | None = None) -> dict:
    """A collaborator proposes changes. Proposals are recorded — never applied
    silently; the creator reviews, and conflicts are surfaced, not hidden."""
    row = db.query_one("SELECT * FROM forge_drafts WHERE id=?", (draft_id,))
    if not row:
        raise ForgeError("no such collaborative draft")
    if row["status"] == "approved":
        raise ForgeError("this world is published — duplicate it to iterate further")
    if not ops:
        raise ForgeError("an empty contribution says nothing")
    head = _head_rev(draft_id)
    base = int(base_rev) if base_rev else head
    conflicts = sorted(_touched_paths(ops) & _changed_paths_between(draft_id, base, head))
    cid_ = new_id("con")
    now = utcnow()
    db.execute(
        "INSERT INTO forge_contrib (id, draft_id, author_id, author_name, ops_json, note,"
        " base_rev, status, conflicts_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?, 'proposed', ?, ?, ?)",
        (cid_, draft_id, author_id or "local", (author_name or "a collaborator")[:40],
         jdumps(ops), (note or "")[:200], base, jdumps(conflicts), now, now),
    )
    return {"proposal_id": cid_, "base_rev": base, "head_rev": head,
            "conflicts": conflicts,
            "message": ("this touches areas changed since your draft began — "
                        "the creator will see the conflict and decide" if conflicts
                        else "proposed for review")}


def contrib_apply(draft_id: str, proposal_id: str, player_id: str, force: bool = False) -> dict:
    """Creator review: apply a proposal. Conflicting proposals are refused
    unless the creator explicitly forces them — nothing is silently
    overwritten."""
    row = dict(db.query_one("SELECT * FROM forge_drafts WHERE id=?", (draft_id,)) or {})
    if not row:
        raise ForgeError("no such collaborative draft")
    if not _is_creator(row, player_id):
        raise ForgeError("only the campaign creator reviews and applies contributions")
    prop = db.query_one("SELECT * FROM forge_contrib WHERE id=? AND draft_id=?",
                        (proposal_id, draft_id))
    if not prop:
        raise ForgeError("no such proposal")
    if prop["status"] != "proposed":
        raise ForgeError("that proposal was already " + prop["status"])
    # conflicts are recomputed at review time: the world may have moved on
    # since the proposal was written
    conflicts = sorted(_touched_paths(jloads(prop["ops_json"], [])) |
                       set(jloads(prop["conflicts_json"], [])))
    conflicts = sorted(set(conflicts) & _changed_paths_between(draft_id, prop["base_rev"],
                                                              _head_rev(draft_id)))
    if conflicts and not force:
        db.execute("UPDATE forge_contrib SET conflicts_json=?, updated_at=? WHERE id=?",
                   (jdumps(conflicts), utcnow(), proposal_id))
        raise ForgeError("conflict: " + ", ".join(conflicts) +
                         " — review and apply with force, or ask the author to rebase")
    ops = jloads(prop["ops_json"], [])
    res = edit_draft(draft_id, ops, f"contribution by {prop['author_name']}: {prop['note']}"[:150])
    # authoritative secret authorship: any GM secret added by this proposal is
    # stamped with its contributor's identity, so the spoiler boundary works
    # even if the contributor forgot to record themselves
    row = db.query_one("SELECT pack_json FROM forge_drafts WHERE id=?", (draft_id,))
    pack = jloads(row["pack_json"], {})
    before = None
    rev_row = db.query_one("SELECT pack_json FROM forge_revisions WHERE draft_id=? AND seq=?",
                           (draft_id, prop["base_rev"]))
    if rev_row:
        before = jloads(rev_row["pack_json"], {})
    old_secrets = set((before or {}).get("gm_secrets", []) or [])
    authors = pack.setdefault("secret_authors", {})
    changed = False
    for s in pack.get("gm_secrets", []) or []:
        if s not in old_secrets:
            # authoritative: identity is the player id, never a display name
            authors[s] = prop["author_id"]
            changed = True
    if changed:
        db.execute("UPDATE forge_drafts SET pack_json=?, updated_at=? WHERE id=?",
                   (jdumps(pack), utcnow(), draft_id))
    db.execute("UPDATE forge_contrib SET status='applied', applied_rev=?, updated_at=? WHERE id=?",
               (res.get("revision"), utcnow(), proposal_id))
    return {"applied": True, "revision": res.get("revision"), "problems": res.get("problems", [])}


def contrib_reject(draft_id: str, proposal_id: str, player_id: str) -> dict:
    row = dict(db.query_one("SELECT * FROM forge_drafts WHERE id=?", (draft_id,)) or {})
    if not row:
        raise ForgeError("no such collaborative draft")
    if not _is_creator(row, player_id):
        raise ForgeError("only the campaign creator reviews contributions")
    db.execute("UPDATE forge_contrib SET status='rejected', updated_at=? WHERE id=?",
               (utcnow(), proposal_id))
    return {"rejected": True}


SUGGEST_KINDS = ("npc", "location", "quest", "dialogue", "encounter", "lore", "branch")

FORGE_SUGGEST_SYSTEM = """You are the Campaign Forge's workshop assistant for a
collaboratively-built world. Return ONE JSON object (no markdown). Shape:
{"kind": "<requested kind>", "name": "", "fields": {}, "notes": "<=40 words"}.
Only material consistent with the supplied world context. You SUGGEST; you
never decide."""


def collab_suggest(draft_id: str, kind: str, prompt: str = "", cfg: dict | None = None) -> dict:
    """AI assistance for contributors. Suggestions are returned to the
    requester only — the engine never applies them, and they never overwrite
    another contributor's work."""
    if kind not in SUGGEST_KINDS:
        raise ForgeError("suggest one of: " + ", ".join(SUGGEST_KINDS))
    row = db.query_one("SELECT pack_json FROM forge_drafts WHERE id=?", (draft_id,))
    if not row:
        raise ForgeError("no such collaborative draft")
    pack = jloads(row["pack_json"], {})
    context = json.dumps({k: pack.get(k) for k in
                          ("name", "summary", "locations", "npcs", "intro_quests")},
                         ensure_ascii=False)[:4000]
    if cfg and cfg.get("enabled"):
        try:
            text, meta = ai.chat([
                {"role": "system", "content": FORGE_SUGGEST_SYSTEM},
                {"role": "user", "content": f"KIND: {kind}\nWORLD: {context}\nREQUEST: {prompt[:300]}"},
            ], cfg)
            data = ai.extract_json(text)
            if isinstance(data, dict):
                return {"kind": kind, "suggestion": data, "applied": False,
                        "source": "model", "note": "a suggestion only — nothing is applied until you propose it"}
        except ai.AiError:
            pass
    # offline fallback: deterministic template, clearly marked
    templates = {
        "npc": {"name": "Maren the Lantern-Keeper", "fields": {"role": "keeper of small truths",
                "desc": "Tends the lights where roads divide; trades rumors for honest work."},
                "notes": "template — edit freely before proposing"},
        "location": {"name": "The Sunken Bell", "fields": {"desc": "A bell beneath the ford that rings when no one pulls."},
                     "notes": "template — edit freely before proposing"},
        "quest": {"name": "Ring the Sunken Bell", "fields": {"title": "Ring the Sunken Bell"},
                  "notes": "template — edit freely before proposing"},
        "dialogue": {"name": "greeting", "fields": {"line": "You've the look of someone the road follows."},
                     "notes": "template"},
        "encounter": {"name": "Ford Ambush", "fields": {"monster": "goblin", "count": 2},
                      "notes": "template"},
        "lore": {"name": "The Bell's Oath", "fields": {"text": "It was cast to warn of the thing under the water."},
                 "notes": "template"},
        "branch": {"name": "The Other Road", "fields": {"goto": "crossroads_scene"},
                   "notes": "template"},
    }
    return {"kind": kind, "suggestion": templates.get(kind, templates["lore"]),
            "applied": False, "source": "offline-template",
            "note": "a suggestion only — nothing is applied until you propose it"}


def collab_approve(draft_id: str, player_id: str) -> dict:
    """The creator publishes the world into the LOCAL playable Library through
    the same engine-authoritative gates as every literary adaptation. Nothing
    is sent anywhere; imported/private sources remain private."""
    row = dict(db.query_one("SELECT * FROM forge_drafts WHERE id=?", (draft_id,)) or {})
    if not row:
        raise ForgeError("no such collaborative draft")
    if not _is_creator(row, player_id):
        raise ForgeError("only the campaign creator may approve the world")
    pack = jloads(row["pack_json"], {})
    problems = validate_pack(pack)
    if problems:
        raise ForgeError("cannot approve — the world still has problems: " + "; ".join(problems[:6]))
    flow = validate_flow(pack)
    hard = [f for f in flow if "missing scene target" in f or "no scene reachable" in f]
    if hard:
        raise ForgeError("cannot approve — broken adventure flow: " + "; ".join(hard[:4]))
    db.execute("UPDATE forge_drafts SET status='approved', updated_at=? WHERE id=?",
               (utcnow(), draft_id))
    res = approve_draft(draft_id)
    return {**res, "collab": True,
            "note": "installed into the local Library; private sources stay private"}


# ==========================================================================
# v0.4.0 — Workshop playtest portals
# ==========================================================================

def start_playtest(draft_id: str, name: str = "") -> dict:
    """Launch a draft world into an isolated test session. A real campaign is
    created from the DRAFT pack (no approval required); approved worlds and
    real saves are untouched. The creator can test, read a report, and stop."""
    from . import gm as _gm
    draft = draft_view(draft_id)
    pack = json.loads(json.dumps(draft["pack"]))  # deep copy
    pack["id"] = "playtest_" + _slug(pack.get("id", "world"))[:20] + "_" + new_id("x")[-6:]
    pack["name"] = (name or pack.get("name", "Playtest"))[:60] + " [playtest]"
    pack_dir = PACKS_DATA_DIR / pack["id"]
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(jdumps(pack), encoding="utf-8")
    cid = _gm.create_campaign("Playtest: " + (name or pack.get("name", ""))[:40],
                              pack["id"],
                              {"name": "The Playtester", "archetype": (
                                  pack.get("archetypes") or [{}])[0].get("id", "")})
    row = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))
    st = jloads(row["state_json"], {})
    st["playtest_of"] = draft_id
    st["playtest_pack"] = pack["id"]
    st["playtest_started_at"] = utcnow()
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (jdumps(st), cid))
    db.log_event("library", "playtest_started", {"draft_id": draft_id, "campaign_id": cid})
    return {"campaign_id": cid, "pack_id": pack["id"], "draft_id": draft_id,
            "note": "isolated test portal — real saves and approved worlds untouched"}


def stop_playtest(draft_id: str, campaign_id: str) -> dict:
    """End a playtest: archive the campaign and remove the temporary pack."""
    from . import gm as _gm
    row = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (campaign_id,))
    if not row:
        raise ForgeError("no such playtest campaign")
    st = jloads(row["state_json"], {})
    if st.get("playtest_of") != draft_id:
        raise ForgeError("that campaign is not a playtest of this draft")
    pack_id = st.get("playtest_pack")
    _gm.archive_campaign(campaign_id)
    if pack_id:
        pack_dir = PACKS_DATA_DIR / pack_id
        if pack_dir.exists():
            shutil.rmtree(pack_dir, ignore_errors=True)
    db.log_event("library", "playtest_stopped", {"draft_id": draft_id,
                                                 "campaign_id": campaign_id})
    return {"stopped": True, "campaign_id": campaign_id}


def playtest_report(draft_id: str, campaign_id: str = "") -> dict:
    """Actionable findings for the creator: structural validation, flow
    analysis, and (with a live playtest campaign) continuity warnings."""
    draft = draft_view(draft_id)
    pack = draft["pack"]
    problems = validate_pack(pack)
    flow = validate_flow(pack)
    report = {
        "draft_id": draft_id,
        "validation_problems": problems,
        "flow_findings": flow,
        "endings": list((pack.get("adventures", [{}])[0].get("endings") or {}).keys()),
        "scenes": len(list((pack.get("adventures", [{}])[0].get("scenes") or {}).values())),
        "items_missing": [],
    }
    # unknown item references
    item_ids = {i["id"] for i in pack.get("items", [])}
    for adv in pack.get("adventures", []):
        for sid, sc in (adv.get("scenes") or {}).items():
            for c in (sc.get("choices") or []):
                eff = dict(c.get("effects") or {})
                for br in (c.get("on_pass"), c.get("on_fail")):
                    if isinstance(br, dict):
                        eff.update(br.get("effects") or {})
                ig = eff.get("item_give")
                if ig and ig not in item_ids:
                    report["items_missing"].append(f"choice in '{sid}' grants unknown item '{ig}'")
    if campaign_id:
        from . import continuity as _cont
        try:
            report["continuity_findings"] = _cont.check(campaign_id)
            row = db.query_one("SELECT turn FROM campaigns WHERE id=?", (campaign_id,))
            report["playtest_turn"] = row["turn"] if row else 0
        except Exception:
            report["continuity_findings"] = []
    return report
