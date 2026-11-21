"""Saturday Multiverse — seeded portal generation.

A seed (a word, phrase, name, or short concept) deterministically produces a
world identity under a fixed generator version: name, archetype, atmosphere,
locations, NPCs, threats, mysteries, discoverable items, and a playable
signature scenario in the standard adventure format.

Guarantees:
- the same seed + generator version always yields the same world;
- canonical state lives in the `worlds` table, owned by the engine;
- the AI may enrich narration but never alters the generated structure.

Selection is pure integer arithmetic over SHA-256 bytes of the normalized
seed — no RNG, no time, no platform variance.
"""
from __future__ import annotations

import hashlib

GEN_VERSION = "living-multiverse.gen.v1"

# ---------------------------------------------------------------------------
# Wordbanks and archetypes (all original)
# ---------------------------------------------------------------------------

NAME_PREFIX = ["Hollow", "Drowned", "Last", "Quiet", "Umbral", "Salt", "Gilded",
               "Pale", "Wandering", "Fallow", "Cinder", "Tidal", "Lantern", "Veiled"]
NAME_CORE = ["Lighthouse", "Kingdom", "Orbit", "City", "Engine", "Garden", "Harbor",
             "Colony", "Cathedral", "Market", "Archive", "Foundry", "Meridian", "Verge"]
NAME_SUFFIX = ["of Ash", "Without Shadows", "of Small Hours", "Beneath the Beam",
               "of Quiet Bells", "at World's Edge", "of Salt and Glass",
               "That Remembers", "of the Long Ebb", "Where Maps End"]

ARCHETYPES = {
    "drowned_engine": {
        "label": "Drowned Engine",
        "vignette": "saltgrave",
        "tint": 210,
        "ambience": "shore",
        "weather": "Fog condenses on every metal surface; machinery breathes below.",
        "properties": ["The water is warm and faintly luminous.", "Clockwork chimes arrive through the flood.", "Oil sheen spells half-legible words on the surface."],
        "loc_templates": [
            {"suffix": "pump_hall", "name": "The Pump Hall", "desc": "A cathedral of brass and floodwater; nine valves keep a rhythm older than the town.",
             "hotspots": [{"id": "valves", "label": "the nine valves", "x": 55, "y": 45, "text": "Each valve is stamped with a name. One is stamped with yours, and warm."}]},
            {"suffix": "foreman_office", "name": "The Foreman's Office", "desc": "Ledgers swell with waterlogged hours; a chair still turns to greet visitors.",
             "hotspots": [{"id": "ledger", "label": "the waterlogged ledger", "x": 45, "y": 52, "text": "The last entry lists hours worked by someone who does not appear anywhere else in the book."}]},
            {"suffix": "flooded_stair", "name": "The Engine Stair", "desc": "Steps descend into green-lit water where the heart of the engine keeps its own time.",
             "hotspots": []},
        ],
        "npc_templates": [
            {"role": "the Valvist", "names": ["Brine-Warden Oss", "Valvist Corrin", "Warden Malla"],
             "greeting": "\"Mind the rhythm,\" they say. \"The engine counts everyone who hears it.\""},
            {"role": "a drowned supervisor", "names": ["The Quiet Foreman", "Foreman Halden", "The Under-Overseer"],
             "greeting": "It reviews you like an invoice, then nods once, water tapping from its hat brim."},
        ],
        "threats": ["Pressure ghosts that flatten doors", "A valve-rhythm you must not interrupt", "Rust that remembers being blood"],
        "mystery_titles": ["What the engine counts", "Who the ninth valve is for", "The hour that repeats"],
    },
    "ember_kingdom": {
        "label": "Ember Kingdom",
        "vignette": "umbral",
        "tint": 18,
        "ambience": "tavern",
        "weather": "Embers drift upward; every shadow leans toward the fire.",
        "properties": ["Ash falls gently, always upward.", "Fire here negotiates.", "Names burn a little when spoken."],
        "loc_templates": [
            {"suffix": "ember_court", "name": "The Ember Court", "desc": "A throne of slow coals where petitions are heard by light rather than voice.",
             "hotspots": [{"id": "coals", "label": "the petition coals", "x": 50, "y": 42, "text": "Write a want in ash and it glows: granted, priced, or unhearable."}]},
            {"suffix": "cinder_market", "name": "The Cinder Market", "desc": "Stalls of warm glass sell bargains that cool too quickly.",
             "hotspots": [{"id": "stall", "label": "the warm-glass stall", "x": 62, "y": 48, "text": "The merchant sells sight: one look at what you lost, one coin of breath."}]},
            {"suffix": "ash_stair", "name": "The Cinder Stair", "desc": "Steps of compacted ash climb to a door that only opens for the honest.",
             "hotspots": []},
        ],
        "npc_templates": [
            {"role": "the Ledger-Keeper", "names": ["Ledger-Keeper Vess", "The Ash Accountant", "Keeper Sable"],
             "greeting": "\"Everything warm is owed,\" the Keeper says, tapping a ledger bound in soot."},
            {"role": "a cinder herald", "names": ["Herald Kin", "The Small Fire", "Emberword"],
             "greeting": "It speaks in matches: one struck per sentence, never more."},
        ],
        "threats": ["Debts with teeth", "A fire that collects favors", "The unlit corridor"],
        "mystery_titles": ["Whom the coals favor", "The debt that predates you", "Why the embers rise"],
    },
    "quiet_colony": {
        "label": "Quiet Colony",
        "vignette": "tavern",
        "tint": 140,
        "ambience": "tavern",
        "weather": "Still air; the settlement holds its breath between signals.",
        "properties": ["Everyone waits for the same broadcast.", "Tea is a ceremony of survival.", "The quiet is administered, not natural."],
        "loc_templates": [
            {"suffix": "signal_room", "name": "The Signal Room", "desc": "Racks of patient receivers listen to a sky that stopped answering years ago.",
             "hotspots": [{"id": "receiver", "label": "the main receiver", "x": 48, "y": 44, "text": "Between static and static, a voice reads the same name list, slowly, kindly."}]},
            {"suffix": "tea_house", "name": "The Tea House", "desc": "Steam, chipped cups, and the colony's only unwritten rules.",
             "hotspots": [{"id": "cups", "label": "the reserved cup", "x": 60, "y": 50, "text": "One cup is always full. No one remembers pouring it. No one dares tip it."}]},
            {"suffix": "quiet_stair", "name": "The Listening Stair", "desc": "A stairwell built to carry sound up to the antenna field.",
             "hotspots": []},
        ],
        "npc_templates": [
            {"role": "the Signalmaster", "names": ["Signalmaster Etta", "Master Verity", "The Listener Prime"],
             "greeting": "\"You heard it too,\" they say. Not a question. \"Everyone who arrives heard it too.\""},
            {"role": "a caretaker", "names": ["Caretaker Fo", "Old Twenty-Two", "The Quiet Host"],
             "greeting": "They pour you tea without asking and watch the door while you drink."},
        ],
        "threats": ["The broadcast that must not be answered", "A silence with weight", "The reserved cup"],
        "mystery_titles": ["Who reads the name list", "The cup that never empties", "What ended the sky"],
    },
    "glass_wilderness": {
        "label": "Glass Wilderness",
        "vignette": "wreck",
        "tint": 285,
        "ambience": "shore",
        "weather": "Light refracts strangely; the horizon arrives early.",
        "properties": ["The ground rings faintly underfoot.", "Rain passes through things, sometimes.", "Distances are negotiable at dusk."],
        "loc_templates": [
            {"suffix": "prairie_glass", "name": "The Bell Prairie", "desc": "Glass reeds chime with every step, announcing you to whatever listens.",
             "hotspots": [{"id": "reed", "label": "the cracked reed", "x": 55, "y": 50, "text": "Inside the reed: a note that says the prairie rings in warning, not greeting."}]},
            {"suffix": "optician_shrine", "name": "The Lens Shrine", "desc": "Hundreds of borrowed lenses, each showing one honest thing.",
             "hotspots": [{"id": "lens", "label": "the borrowed lens", "x": 45, "y": 42, "text": "Through it you see the shore — briefly, from above, as a gull sees it."}]},
            {"suffix": "glass_stair", "name": "The Refraction Walk", "desc": "A causeway of prisms that bends your footsteps ahead of you.",
             "hotspots": []},
        ],
        "npc_templates": [
            {"role": "the Lenswright", "names": ["Lenswright Iso", "The Optician", "Wright Cass"],
             "greeting": "\"Careful which reflections you keep,\" they say. \"Some keep you back.\""},
            {"role": "a prairie walker", "names": ["Walker Ninn", "The Slow Chime", "Widow Peri"],
             "greeting": "They walk without ringing. That is the first strange thing about them."},
        ],
        "threats": ["The thing that rings in answer", "A reflection with plans", "Dusk arriving early"],
        "mystery_titles": ["What the prairie warns of", "The reflection that waves first", "Whose footsteps ring"],
    },
    "salt_cathedral": {
        "label": "Salt Cathedral",
        "vignette": "seacave",
        "tint": 165,
        "ambience": "shore",
        "weather": "Salt haze; every sound arrives pre-confessed.",
        "properties": ["Confession is architectural here.", "The tide keeps the vows.", "Tears are currency of the lowest kind."],
        "loc_templates": [
            {"suffix": "nave", "name": "The Brine Nave", "desc": "Columns of fused salt, and a font that reflects your face a moment late.",
             "hotspots": [{"id": "font", "label": "the confession font", "x": 50, "y": 46, "text": "The water remembers sins spoken into it, in order, forever."}]},
            {"suffix": "relic_vault", "name": "The Relic Vault", "desc": "Protected by a door that opens for grief, not keys.",
             "hotspots": [{"id": "vault", "label": "the reliquary", "x": 62, "y": 44, "text": "Each relic is labeled with the name of the person who gave it up."}]},
            {"suffix": "salt_stair", "name": "The Penitent Stair", "desc": "Steps carved by knees, worn smooth by descent.",
             "hotspots": []},
        ],
        "npc_templates": [
            {"role": "the Tidesister", "names": ["Tidesister Umbra", "Sister Callow", "The Brine Prioress"],
             "greeting": "\"You are early,\" she says. \"Or the tide is late. We no longer distinguish.\""},
            {"role": "a penitent", "names": ["Brotherless Cael", "The Kneeling One", "Penitent Rho"],
             "greeting": "They confess before you speak, in case your question was the sin."},
        ],
        "threats": ["A vow the tide enforces", "The font's memory", "Grief that opens doors"],
        "mystery_titles": ["Whose sins the font keeps", "The relic that gives itself up", "Why the tide confesses"],
    },
    "hollow_orbit": {
        "label": "The Hollow Orbit",
        "vignette": "lighthouse",
        "tint": 255,
        "ambience": "shore",
        "weather": "No sky worth naming; starlight arrives late and from below.",
        "properties": ["Down is a rumor.", "Ports open onto elsewhere.", "The dark is load-bearing."],
        "loc_templates": [
            {"suffix": "berth_ring", "name": "The Berth Ring", "desc": "Empty berths wait in a circle, patient as spiderwebs.",
             "hotspots": [{"id": "berth", "label": "the occupied berth", "x": 52, "y": 44, "text": "One berth is occupied by something the registry calls 'currently elsewhere.'"}]},
            {"suffix": "registry", "name": "The Registry", "desc": "A hall of ledgers indexing everything that ever docked, including you.",
             "hotspots": [{"id": "registry", "label": "your entry", "x": 44, "y": 52, "text": "Your arrival is already logged, in handwriting you almost recognize."}]},
            {"suffix": "orbit_stair", "name": "The Down Stair", "desc": "Stairs that descend politely into a dark labeled LOAD-BEARING.",
             "hotspots": []},
        ],
        "npc_templates": [
            {"role": "the Harbourmaster", "names": ["Harbourmaster Vell", "Master Ives", "The Berthkeeper"],
             "greeting": "\"Welcome back,\" they say. You have never been here. They check the ledger. \"Welcome ahead, then.\""},
            {"role": "a dark-tender", "names": ["Tender Mab", "The Load-Bearer", "Nightwright Osk"],
             "greeting": "They apologize for the dark's weight and offer to let you carry a little."},
        ],
        "threats": ["The berth's occupant", "A dark that bears load", "Elsewhere leaking in"],
        "mystery_titles": ["What docks at night", "The handwriting in your entry", "What the dark holds up"],
    },
}

RELIC_NOUNS = ["Compass", "Chime", "Coin", "Ledger", "Bell", "Key", "Lamp", "Mirror", "Glyph", "Seed"]
RELIC_MODS = ["Quiet", "Warm", "Borrowed", "Honest", "Patient", "Homesick", "Unspent", "Twice-Named"]
RELIC_TEXT = {
    "drowned_engine": "It hums at the frequency of floodwater and counts your heartbeats politely.",
    "ember_kingdom": "It is warm to the touch and slightly owed.",
    "quiet_colony": "It receives one soft broadcast per day, addressed to whoever holds it.",
    "glass_wilderness": "It rings once when a lie is told nearby.",
    "salt_cathedral": "It tastes of confession and forgives nothing itself.",
    "hollow_orbit": "It is heavier some hours than others, as if berthed elsewhere.",
}

HOOKS = [
    "The world's {focus} keeps a signal for someone who has not come home.",
    "A debt recorded in the {focus} has come due, and the collector is polite.",
    "Something in the {focus} is counting down, and the count is nearly done.",
    "The {focus} repeats a single hour, and only visitors notice.",
    "A relic in the {focus} wants to be returned to a shore that may not exist.",
]

SCENARIO = {
    "entry": "sig_arrival",
    "title": "The Signature of {world}",
    "on_enter": [
        {"quest_update": {"quest_id": "sig_{hash6}", "title": "The Signature of {world}", "status": "open",
                          "note": "The heart of the world asks something specific of you."}},
        {"fact": "In {world}: {hook_short}"},
    ],
    "scenes": {
        "sig_arrival": {
            "title": "Arrival",
            "brief": "The seed-world's focus location. The player approaches the heart of the mystery.",
            "gm_directive": "Let the world breathe before the ask. The scenario's request is concrete and small.",
            "intro": "You arrive where the world keeps its heart. {hook_short} The way in is ordinary, which is the most alarming thing about it.",
            "flavor": ["The air here agrees with itself.", "Your footfalls arrive on schedule.", "Something notes your name and does not explain."],
            "hotspots": [],
            "choices": [
                {"id": "approach", "label": "Approach the heart of the matter",
                 "hint": "Direct, honest, unwise.",
                 "goto": "sig_engage",
                 "effects": {"journal": "Approached the heart of {world} directly."}},
                {"id": "observe_first", "label": "Watch the rhythm before touching anything",
                 "hint": "Notice — learn one true thing first.",
                 "check": {"skill": "notice", "hard": False},
                 "on_pass": {"goto": "sig_engage",
                             "effects": {"fact": "In {world}: the rhythm skips whenever you are watched. The world is shy.",
                                         "journal": "Watched the rhythm of {world}. It skips when observed."}},
                 "on_fail": {"goto": "sig_engage",
                             "effects": {"journal": "Watched the rhythm of {world} and learned only that it does not like to be watched."}}},
            ],
        },
        "sig_engage": {
            "title": "The Ask",
            "brief": "The world makes its specific, small request. Resolve it: answer, refuse, or pay.",
            "gm_directive": "The request is concrete. Consequences are permanent and recorded.",
            "intro": "The ask, when it finally comes, is small the way a keyhole is small: it fits exactly one thing, and that thing is you. {ask_text}",
            "flavor": ["The world waits without impatience.", "Your shadow arrives a half-step early.", "Somewhere, the count resumes."],
            "hotspots": [],
            "choices": [
                {"id": "answer_call", "label": "Answer the world's request",
                 "hint": "Bind — give what is asked.",
                 "check": {"skill": "bind", "hard": True},
                 "on_pass": {"effects": {
                     "ending": "world_kept",
                     "quest_update": {"quest_id": "sig_{hash6}", "status": "done", "note": "Answered the world's request; it remembers your name kindly."},
                     "item_give": [{"item_id": "{relic_id}", "qty": 1}],
                     "fact": "{world} owes me a kindness, and worlds pay their debts.",
                     "beads": 3,
                     "journal": "Answered {world}'s request. It gave me {relic_name} and its regard."}},
                 "on_fail": {"effects": {
                     "ending": "world_owed",
                     "quest_update": {"quest_id": "sig_{hash6}", "status": "failed", "note": "The answer went wrong; the world keeps the difference."},
                     "harm": {"type": "nerve", "amount": 2},
                     "hidden_fact": "{world} holds a piece of my answer and will return it at a cost.",
                     "journal": "My answer went wrong in {world}. Something of it stayed there."}},
                },
                {"id": "refuse", "label": "Refuse, and close the matter politely",
                 "hint": "The world accepts refusals. Once.",
                 "effects": {
                     "ending": "world_refused",
                     "quest_update": {"quest_id": "sig_{hash6}", "status": "done", "note": "Refused the world's request. It marked the refusal and moved on."},
                     "fact": "{world} records refusals. Mine is on file.",
                     "journal": "Refused {world}'s request. The world thanked me for my honesty, which was somehow worse."}},
            ],
        },
    },
    "endings": {
        "world_kept": {"text": "The world's heart accepts your answer the way a lock accepts the only key it ever wanted. Something enormous and patient relaxes. It gives you {relic_name} — not as payment, but as recognition — and three glassbeads roll out of the seam of the world like small applause. The door home is already open.", "return_location": "tidegate", "consequence": "A visitor answered {world}'s signature, and the world has been quietly grateful ever since."},
        "world_owed": {"text": "Your answer goes wrong in the specific way worlds remember. Something of it stays behind, folded into the world's ledger, and the world marks the debt with something like tenderness. You leave carrying the weight of an unfinished sentence. The door home lets you out gently.", "return_location": "tidegate", "consequence": "{world} holds an unfinished answer and will mention it to anyone who asks."},
        "world_refused": {"text": "You decline, clearly and without cruelty, and the world records the refusal in its permanent archive of honest things. The pressure lifts. The ordinary returns. You leave with nothing but the strange comfort of having been taken seriously by a universe.", "return_location": "tidegate", "consequence": "{world} keeps a clean refusal on file, and respects it."},
    },
    "echo_offers": {
        "world_kept": [
            {"kind": "achievement", "title": "Worldtender", "detail": "Answered the heart-request of {world} and was recognized.",
             "data": {"trait_skill": "bind", "trait_delta": 1}},
            {"kind": "item", "title": "{relic_name}", "detail": "A relic carried home from {world}.", "data": {"item_id": "{relic_id}"}},
        ],
        "world_refused": [
            {"kind": "achievement", "title": "Honest Refusal", "detail": "Declined the request of {world}, and was archived for it.",
             "data": {"trait_skill": "endure", "trait_delta": 1}},
        ],
    },
}

ASK_TEXT = [
    "It wants the name of a shore you have walked, spoken into a listening shell.",
    "It wants one honest hour of your attention, spent standing still.",
    "It wants you to carry a small weight to the far side and leave it there, unfollowed.",
    "It wants you to tell it one thing you lost, so it can stop looking for its own.",
    "It wants the sound of a door opened from the outside.",
]


def normalize_seed(seed: str) -> str:
    return " ".join((seed or "").strip().lower().split())[:120]


def seed_hash(seed: str) -> str:
    return hashlib.sha256(f"{normalize_seed(seed)}|{GEN_VERSION}".encode("utf-8")).hexdigest()


def world_id(seed: str) -> str:
    return f"wld_{seed_hash(seed)[:10]}"


def _pick_byte(code: bytes, index: int, options: list):
    return options[code[index % len(code)] % len(options)]


def _pick_slice(code: bytes, start: int, n: int, options: list) -> list:
    return [options[(code[(start + i) % len(code)]) % len(options)] for i in range(n)]


def generate_world(seed: str) -> dict:
    """Deterministically build the full world identity for a seed."""
    norm = normalize_seed(seed)
    if not norm:
        raise ValueError("a seed needs at least one word")
    h = seed_hash(norm)
    code = bytes.fromhex(h)

    arch_key = _pick_byte(code, 0, list(ARCHETYPES.keys()))
    arch = ARCHETYPES[arch_key]
    hash6 = h[:6]

    name = f"The {_pick_byte(code, 1, NAME_PREFIX)} {_pick_byte(code, 2, NAME_CORE)} {_pick_byte(code, 3, NAME_SUFFIX)}"
    relic_id = f"{hash6}_relic"
    relic_name = f"The {_pick_byte(code, 4, RELIC_MODS)} {_pick_byte(code, 5, RELIC_NOUNS)}"
    hook_tpl = _pick_byte(code, 6, HOOKS)
    ask_text = _pick_byte(code, 7, ASK_TEXT)
    focus = arch["loc_templates"][0]["name"]

    hook_short = hook_tpl.format(focus=focus)
    world_name = name

    locations = []
    for tpl in arch["loc_templates"]:
        loc = {
            "id": f"w{hash6}_{tpl['suffix']}",
            "name": tpl["name"],
            "short": tpl["desc"].split(";")[0].split(".")[0] + ".",
            "desc": tpl["desc"],
            "known": False,
            "vignette": arch["vignette"],
            "flavor": arch["properties"],
            "hotspots": tpl["hotspots"],
        }
        locations.append(loc)
    entry_loc = locations[0]

    npcs = []
    for i, tpl in enumerate(arch["npc_templates"]):
        npcs.append({
            "id": f"n{hash6}_{i}",
            "name": _pick_byte(code, 10 + i, tpl["names"]),
            "role": tpl["role"],
            "desc": f"{tpl['role']} of {world_name}.",
            "greeting": tpl["greeting"],
            "rumors": arch["threats"],
        })

    mysteries = [
        {"id": f"m{hash6}_{i}", "title": title, "text": title + " — " + arch["properties"][i % len(arch["properties"])],
         "thread": f"gen_{hash6}"}
        for i, title in enumerate(_pick_slice(code, 14, 2, arch["mystery_titles"]))
    ]

    relic_item = {
        "id": relic_id,
        "name": relic_name,
        "kind": "relic",
        "desc": RELIC_TEXT[arch_key],
        "use": {"text": f"The {relic_name.lower()} settles, satisfied to be held."},
    }

    scenario = _build_scenario(hash6, world_name, relic_id, relic_name, hook_short, ask_text, entry_loc["id"])
    # stepping into the world's entry location begins its signature scenario
    entry_loc["adventure"] = scenario["id"]

    return {
        "gen_version": GEN_VERSION,
        "seed": norm,
        "seed_hash": h,
        "name": world_name,
        "archetype": arch_key,
        "archetype_label": arch["label"],
        "tint": arch["tint"],
        "ambience": arch["ambience"],
        "weather": arch["weather"],
        "properties": arch["properties"],
        "threats": arch["threats"],
        "vignette": arch["vignette"],
        "entry_location": entry_loc["id"],
        "locations": locations,
        "npcs": npcs,
        "mysteries": mysteries,
        "items": [relic_item],
        "hooks": [hook_short],
        "intro_facts": [
            f"Through an unstable door lies {world_name} ({arch['label']}).",
            arch["weather"],
            hook_short,
        ],
        "adventures": [scenario],
    }


def _build_scenario(hash6: str, world_name: str, relic_id: str, relic_name: str,
                    hook_short: str, ask_text: str, entry_loc_id: str) -> dict:
    """A playable 2-scene signature scenario in the standard pack format."""
    adv = {
        "id": f"sig_{hash6}",
        "title": f"The Signature of {world_name}",
        "genre": "seeded signature scenario",
        "portal_id": f"door_w{hash6}",
        "entry": "sig_arrival",
        "summary": f"The small, permanent request at the heart of {world_name}.",
        "on_enter": [],
        "scenes": {},
        "endings": {},
        "echo_offers": {},
        "_subst": {
            "{hash6}": hash6,
            "{world}": world_name,
            "{relic_id}": relic_id,
            "{relic_name}": relic_name,
            "{hook_short}": hook_short,
            "{ask_text}": ask_text,
            "{focus}": world_name,
        },
        "_entry_location": entry_loc_id,
    }
    import json as _json

    raw = _json.dumps(SCENARIO)
    for k, v in adv["_subst"].items():
        raw = raw.replace(k, v)
    built = _json.loads(raw)
    adv["on_enter"] = built["on_enter"]
    adv["scenes"] = built["scenes"]
    adv["endings"] = built["endings"]
    adv["echo_offers"] = built["echo_offers"]
    # make the arrival scene's first location link explicit for travel
    adv["scenes"]["sig_arrival"]["_location"] = entry_loc_id
    return adv


def suggest_seeds(count: int = 5) -> list[str]:
    """Cheap flavor suggestions for the seed gate (deterministic order)."""
    suggestions = [
        "The Last Lighthouse", "Clockwork Ocean", "Forgotten Kingdom",
        "Saturday Night", "A City Without Shadows", "The Patient Bell",
        "Glass Prairie", "Nine Quiet Radios", "The Debt Collector's Holiday",
        "A Shore That Misses You",
    ]
    return suggestions[: max(1, min(10, count))]
