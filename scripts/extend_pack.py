#!/usr/bin/env python3
"""Extend the Living Shore pack with Milestone 1.5/2.0/2.5 content.

Idempotent: safe to run repeatedly (every change is additive and guarded).
Run:  python3 scripts/extend_pack.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "worldpacks" / "living_shore" / "pack.json"

pack = json.loads(PACK.read_text(encoding="utf-8"))
loc_by_id = {l["id"]: l for l in pack["locations"]}
item_ids = {i["id"] for i in pack["items"]}
portal_ids = {p["id"] for p in pack.get("portals", [])}
adv_ids = {a["id"] for a in pack.get("adventures", [])}


def item(d):
    if d["id"] not in item_ids:
        pack["items"].append(d)
        item_ids.add(d["id"])


def portal(d):
    if d["id"] not in portal_ids:
        pack["portals"].append(d)
        portal_ids.add(d["id"])


def adventure(d):
    """Insert or REPLACE an adventure (keeps the script idempotent and
    lets fixed content overwrite earlier versions)."""
    for i, a in enumerate(pack["adventures"]):
        if a["id"] == d["id"]:
            pack["adventures"][i] = d
            return
    pack["adventures"].append(d)
    adv_ids.add(d["id"])


# ---------------------------------------------------------------- portals
portal({
    "id": "door_unstable",
    "label": "Unstable Door",
    "unstable": True,
    "door_index": 3,
    "hint": "Whisper a seed — a word or short phrase — and somewhere new answers.",
})
if "An unstable door shimmers at the far end of the Beam, half-here: it opens for whispered seeds." \
        not in pack["intro_facts"]:
    pack["intro_facts"].append(
        "An unstable door shimmers at the far end of the Beam, half-here: it opens for whispered seeds.")

# ------------------------------------------------------- foreshadow threads
pack["foreshadow_threads"] = [
    {
        "id": "ninth_wave", "title": "The Ninth Wave", "threshold": 4,
        "payoff_title": "The Ninth Wave arrives",
        "payoff_narration": "A ninth wave comes up the beach and does not go back out. Where it stands, "
                            "wet and patient, a door of standing water opens on the shore.",
        "flag": "ninth_wave_open",
        "payoff_effects": {
            "discover": "ninth_wave",
            "fact": "The ninth wave came in and stayed. A door of standing water stands on the beach now.",
        },
    },
    {
        "id": "wrong_gull", "title": "The Wrong Gull", "threshold": 3,
        "payoff_title": "The white gull befriends you",
        "payoff_narration": "A white gull lands beside you, its shadow briefly wearing a hat, and decides — "
                            "with terrible solemnity — to be your friend.",
        "flag": "gull_friend",
        "payoff_effects": {"fact": "The wrong gull has decided to be my friend. Its eye misses nothing."},
    },
]

# ------------------------------------------------------------ wash-ashore
pack["washashore"] = [
    {"id": "glass_beads", "kind": "beads", "label": "a scatter of glassbeads",
     "text": "Sea-glass beads, polished by the Beam, pooled in a drag-mark. The shore pays for attention.",
     "effects": {"beads": 2}, "weight": 3},
    {"id": "brine_script", "kind": "clue", "label": "a brine-scripted plank",
     "text": "A plank scored with brine-script: the same mark the lighthouse keeper logged. The ninth wave is being counted.",
     "effects": {"clue": {"thread_id": "ninth_wave", "text": "Brine-script plank: the ninth wave is counted, not awaited."}},
     "weight": 2},
    {"id": "drift_bundle", "kind": "item", "label": "a lashed drift-bundle",
     "text": "A sealed bundle: dried kelp and a storm lantern, lashed by careful hands.",
     "effects": {"item_give": [{"item_id": "dried_kelp", "qty": 1}, {"item_id": "storm_lantern", "qty": 1}]},
     "weight": 2},
    {"id": "salt_charm_wash", "kind": "item", "label": "a salt-charm knot",
     "text": "A fresh salt-charm, still warm, tied by no one you can see.",
     "effects": {"item_give": [{"item_id": "salt_charm", "qty": 1}]}, "weight": 2},
    {"id": "wrong_feather", "kind": "clue", "label": "a gull feather, shadow-first",
     "text": "A white feather whose shadow wears a hat. The wrong gull is counting things ashore.",
     "effects": {"clue": {"thread_id": "wrong_gull", "text": "Wash-ashore feather: the wrong gull is counting things on the shore."}},
     "weight": 2},
    {"id": "single_bead", "kind": "beads", "label": "one perfect glassbead",
     "text": "One bead, blue as the Beam, warm as a held hand.",
     "effects": {"beads": 1}, "weight": 3},
]

# ------------------------------------------------------------------- items
item({
    "id": "umbral_token", "name": "Umbral token", "kind": "relic",
    "desc": "A coin of pressed shadow, warm on one side only.",
    "use": {"text": "The token's warm side swings toward the nearest door.",
            "fact": "The umbral token points, when held, toward whatever door is nearest."},
})
item({
    "id": "watchers_eye", "name": "The Watcher's Eye", "kind": "relic",
    "desc": "A lens that shows a room as the lighthouse once saw it.",
    "use": {"text": "Through the eye, the shore appears from above: patient, mapped, remembered.",
            "fact": "The Watcher's Eye shows the shore from above when held.", "flag": "eye_of_the_light"},
})
item({
    "id": "ninth_pearl", "name": "Ninth Wave pearl", "kind": "relic",
    "desc": "Cold, salt-clear, holding one wave's worth of ocean.",
    "use": {"text": "You drink the wave. It is restorative beyond reason.",
            "heal": {"vigor": 2, "nerve": 2}, "consume": True},
})

# ------------------------------------------------- lighthouse & umbral links
lh = loc_by_id["lighthouse"]
lh["adventure"] = "skyless_light"
lh_clue = {"clue": {"thread_id": "ninth_wave",
                    "text": "The keeper's log speaks of a signal asking for a name — the ninth wave's count."}}
if lh_clue not in lh.get("on_enter", []):
    lh.setdefault("on_enter", []).append(lh_clue)

um = loc_by_id["umbral_reach"]
um["adventure"] = "umbral_market"

# -------------------------------------------------------- the Ninth Wave
if "ninth_wave" not in loc_by_id:
    pack["locations"].append({
        "id": "ninth_wave",
        "name": "The Ninth Wave",
        "short": "A wave that came in once and never left.",
        "desc": "A ninth wave stands on the beach where it came ashore, a wall of held water with a "
                "door in it, and through the door: the under-side of the sea, lit by every lantern "
                "ever lost overboard.",
        "known": False,
        "vignette": "seacave",
        "flavor": [
            "The wave holds, and the foam at its crest moves in slow motion.",
            "Lost lanterns drift through the water-door like far-off streetlights.",
            "For one moment your reflection arrives before you.",
        ],
        "hotspots": [
            {"id": "water_door", "label": "the standing water", "x": 55, "y": 46,
             "text": "You look into the held wave and the held wave looks back, kindly, the way old "
                     "dogs do. Somewhere in there, the count goes on — nine, nine, nine."},
        ],
        "on_enter": [
            {"item_give": [{"item_id": "ninth_pearl", "qty": 1}]},
            {"beads": 2},
            {"fact": "I walked into the ninth wave and it gave me a pearl and two glassbeads, like a handshake."},
        ],
    })

# --------------------------------------------- saltgrave endings: legacy hooks
sg = next(a for a in pack["adventures"] if a["id"] == "salt_grave_signal")
sg_end = {
    "beacon_lit": {
        "consequence": "The drowned bay's signal has ended; the Salt door breathes slower now.",
        "clue": "The beacon ended the signal — and the count reached nine.",
        "echo_offers": [
            {"kind": "item", "title": "Keeper's lantern", "detail": "A lamp carried out of a finished story.",
             "data": {"item_id": "keepers_lantern"}},
            {"kind": "achievement", "title": "Beaconlighter", "detail": "Lit the beacon in the drowned bay.",
             "data": {"trait_skill": "endure", "trait_delta": 1}},
        ],
    },
    "pact": {
        "consequence": "Something enormous in the drowned bay knows a voice from the shore, and was pleased.",
        "echo_offers": [
            {"kind": "achievement", "title": "Namedfriend", "detail": "Answered the call and kept the leash.",
             "data": {"trait_skill": "bind", "trait_delta": 1}},
        ],
    },
    "taken": {
        "consequence": "A name was taken at the drowned bay; the Salt door whispers it sometimes.",
        "echo_offers": [
            {"kind": "achievement", "title": "Survivor of the Taking", "detail": "Came back from a namelessness.",
             "data": {"trait_skill": "endure", "trait_delta": 1}},
        ],
    },
    "sunk": {
        "consequence": "The signal tower in the drowned bay went dark — the bay keeps its silence.",
        "clue": "The tower sank with its count unfinished.",
        "echo_offers": [
            {"kind": "item", "title": "Marrow Bell shard", "detail": "Bronze that remembers one stubborn note.",
             "data": {"item_id": "marrow_bell_shard"}},
        ],
    },
}
for end_id, add in sg_end.items():
    end = sg["endings"].setdefault(end_id, {})
    if add.get("consequence"):
        end["consequence"] = add["consequence"]
    if add.get("clue"):
        effects = end.setdefault("effects", {})
        effects["clue"] = {"thread_id": "ninth_wave", "text": add["clue"]}
sg["echo_offers"] = {k: v["echo_offers"] for k, v in sg_end.items() if v.get("echo_offers")}

# =================================================== ADVENTURE: Umbral Market
adventure({
    "id": "umbral_market",
    "title": "The Umbral Market",
    "genre": "dark fantasy",
    "portal_id": "door_ash",
    "entry": "um_arrival",
    "summary": "A midnight market where everything has a price, and the Ledger-Keeper knows your page.",
    "on_enter": [
        {"quest_update": {"quest_id": "umbral_market", "title": "The Umbral Market", "status": "open",
                          "note": "The market trades in hours, favors, and one honest memory."}},
        {"fact": "Through the Door of Ash lies a market of little lights that is open after midnight, forever."},
    ],
    "scenes": {
        "um_arrival": {
            "title": "The Market of Little Lights",
            "brief": "Arrival in the Umbral Reach's night market. Stalls of warm bargains; the Ledger-Keeper's booth at the center.",
            "gm_directive": "The market is charming and dangerous in equal measure. Nothing here is free; everything here is fair.",
            "intro": "The Door of Ash lets you out between two waystones that disagree. Ahead, the market hums: "
                     "stalls of warm glass, a chiming prairie-sound underfoot, and at the center, a booth of "
                     "stacked ledgers where the Ledger-Keeper is already looking at your page. \"You again,\" "
                     "she says, kindly, though you have never been here. \"Or soon.\"",
            "flavor": [
                "A stall sells bottled noons. Another sells the feeling of being expected.",
                "The embers overhead arrange themselves into prices.",
                "Your shadow pays for something small and hurries back to you.",
            ],
            "hotspots": [
                {"id": "warm_stalls", "label": "the warm-glass stalls", "x": 62, "y": 44,
                 "text": "Bargains cool too quickly here. One jar contains a Tuesday, unlabeled."},
                {"id": "waystones", "label": "the disagreeing waystones", "x": 28, "y": 55,
                 "text": "Each points a different way home. Both are certain."},
            ],
            "choices": [
                {"id": "browse", "label": "Browse toward the Ledger-Keeper's booth",
                 "hint": "Everyone arrives at the ledger eventually.",
                 "goto": "um_ledger",
                 "effects": {"journal": "Walked the Umbral Market to the Ledger-Keeper's booth."}},
                {"id": "ask_about_market", "label": "Ask a vendor what the market actually sells",
                 "hint": "Lore — learn the market's true currency.",
                 "check": {"skill": "lore", "hard": False},
                 "on_pass": {"goto": "um_ledger",
                             "effects": {"fact": "The Umbral Market trades in hours, favors, and one honest memory.",
                                         "journal": "Learned the market's currency: hours, favors, one honest memory."}},
                 "on_fail": {"goto": "um_ledger",
                             "effects": {"fact": "The market's prices are fair, which is somehow worse.",
                                         "journal": "The vendor only smiled. Fair prices. Worse."}}},
            ],
        },
        "um_ledger": {
            "title": "The Ledger-Keeper's Booth",
            "brief": "Meet the Ledger-Keeper, who keeps a page with your name on it.",
            "gm_directive": "Vess is courteous, precise, and absolutely serious. The ledger does not lie; it smudges.",
            "intro": "The Ledger-Keeper's booth is a fortress of stacked ledgers, each spine labeled in ash. "
                     "She turns the great book to your page without asking your name. \"One unspent hour,\" "
                     "she says. \"Minted the night you first stood on your shore. The market would like it. "
                     "The market can pay.\"",
            "flavor": [
                "The ledgers exhale warmth like sleeping animals.",
                "Your page is warm to the touch.",
                "Somewhere in the stacks, a debt turns over in its sleep.",
            ],
            "hotspots": [
                {"id": "great_ledger", "label": "the great ledger", "x": 48, "y": 46,
                 "text": "Pages of names and prices. Yours is there. The column header reads: OWED, WILLING."},
            ],
            "choices": [
                {"id": "read_your_page", "label": "Read your page closely",
                 "hint": "Lore, hard — the ledger smudges for the unwary.",
                 "check": {"skill": "lore", "hard": True},
                 "on_pass": {"goto": "um_settle",
                             "effects": {"fact": "My market ledger page shows one unspent hour, minted my first night on the shore.",
                                         "journal": "Read my page: one unspent hour, minted my first night ashore."}},
                 "on_fail": {"goto": "um_settle",
                             "effects": {"fact": "Someone has been reading my ledger page. The smudge is fresh.",
                                         "journal": "My page is smudged. Someone has been reading ahead of me."}}},
                {"id": "compliment_the_stacks", "label": "Compliment her filing system",
                 "hint": "Persuade — flattery, sincerely meant.",
                 "check": {"skill": "persuade", "hard": False},
                 "on_pass": {"goto": "um_settle",
                             "effects": {"npc_rel": {"npc_id": "ledger_keeper", "delta": 1},
                                         "fact": "The Ledger-Keeper liked my compliment. She has filed it.",
                                         "journal": "The Ledger-Keeper accepted my compliment and filed it, alphabetically."}},
                 "on_fail": {"goto": "um_settle",
                             "effects": {"journal": "My compliment was filed under 'attempted'."}}},
            ],
        },
        "um_settle": {
            "title": "Settlement",
            "brief": "The market names its price for your unspent hour. Pay, bargain, or walk away clean.",
            "gm_directive": "Every option is fair. Consequences are permanent and recorded in ledgers.",
            "intro": "\"Here is the market's offer,\" says the Ledger-Keeper. \"Three glassbeads for the hour — "
                     "beads being hours the shore polished. Or bargain with me for something better and stranger. "
                     "Or refuse, and be refused nothing. The market respects a clean refusal.\"",
            "flavor": [
                "The embers overhead dim politely while you decide.",
                "The great ledger waits with the patience of arithmetic.",
                "A small light hovers by your shoulder, reading over it.",
            ],
            "hotspots": [],
            "choices": [
                {"id": "pay_beads", "label": "Pay three glassbeads for the hour",
                 "hint": "Clean, final, yours.",
                 "requires_beads": 3,
                 "locked_hint": "The market wants three glassbeads, and your pockets are lighter than that. "
                                "Adventures and the tide pay in beads.",
                 "effects": {"ending": "debt_paid", "beads": -3,
                             "item_give": [{"item_id": "umbral_token", "qty": 1}],
                             "quest_update": {"quest_id": "umbral_market", "status": "done",
                                              "note": "Paid three glassbeads for the unspent hour. Fair, clean, done."},
                             "fact": "I sold my unspent hour to the Umbral Market for three glassbeads. Fair.",
                             "clue": {"thread_id": "ninth_wave",
                                      "text": "The market's ledger mentions a ninth entry, still open."},
                             "journal": "Paid the market. It gave me an umbral token and its regard."}},
                {"id": "bargain", "label": "Bargain for something better and stranger",
                 "hint": "Bind, hard — the market bargains in true names.",
                 "check": {"skill": "bind", "hard": True},
                 "on_pass": {"effects": {"ending": "bargain_struck",
                                         "item_give": [{"item_id": "umbral_token", "qty": 1}],
                                         "npc_rel": {"npc_id": "ledger_keeper", "delta": 1},
                                         "hidden_fact": "The Ledger-Keeper knows my shore-name now, and keeps it between pages.",
                                         "fact": "I bargained with the Ledger-Keeper and came out ahead. She seemed glad.",
                                         "beads": 2,
                                         "quest_update": {"quest_id": "umbral_market", "status": "done",
                                                          "note": "Bargained well: kept the hour, gained the token and her favor."},
                                         "journal": "Bargained with Vess. Kept my hour, gained a token, two beads, and a strange new respect."}},
                 "on_fail": {"effects": {"ending": "debt_taken",
                                         "harm": {"type": "nerve", "amount": 3},
                                         "hidden_fact": "The market holds a lien on one of my Tuesdays.",
                                         "quest_update": {"quest_id": "umbral_market", "status": "failed",
                                                          "note": "The bargain went wrong. Something of mine is filed away."},
                                         "journal": "The bargain turned. The market filed away a piece of my week, politely."}}},
                {"id": "walk_away", "label": "Refuse cleanly and walk away",
                 "hint": "The market respects refusals. Once.",
                 "effects": {"ending": "walked_free",
                             "quest_update": {"quest_id": "umbral_market", "status": "done",
                                              "note": "Refused the market cleanly. It approved."},
                             "fact": "I refused the Umbral Market cleanly. It filed the refusal with respect.",
                             "clue": {"thread_id": "wrong_gull",
                                      "text": "A gull watched my refusal from the market's eaves, and approved."},
                             "journal": "Walked away from the market. Nothing followed. That was its own gift."}},
            ],
        },
    },
    "endings": {
        "debt_paid": {"text": "The Ledger-Keeper closes your page with two fingers, gently, the way one closes "
                              "an eye. Three glassbeads click into the market's till, and something minted the "
                              "night you first stood on your shore is spent at last. She gives you an umbral "
                              "token — 'for the doorways, they like being pointed at' — and the market's little "
                              "lights dip once, in respect. The Door of Ash is behind you. It was always behind you.",
                       "return_location": "tidegate",
                       "consequence": "The Umbral Market closed one account, and the Door of Ash burns warmer."},
        "bargain_struck": {"text": "You bargain the way the tide bargains: patiently, with the whole shore behind "
                                   "you. The Ledger-Keeper's smile arrives in three installments, and when the "
                                   "deal closes she is holding your hour in her open palm and giving it back. "
                                   "\"Well kept,\" she says, and means your name. Two glassbeads and a warm-sided "
                                   "token are your change. The market approves of you now. That is a kind of debt too.",
                            "return_location": "tidegate",
                            "consequence": "The Ledger-Keeper of the Umbral Market keeps someone's shore-name between her pages, fondly."},
        "debt_taken": {"text": "The bargain turns in the specific way ledgers turn: quietly, precisely, with "
                               "your signature already in the margin. Something of your week is filed away — "
                               "you will notice the gap on a Tuesday and not know which one. The market is "
                               "gentle about it. The market is always gentle about it. You leave lighter.",
                        "return_location": "tidegate",
                        "consequence": "The Umbral Market holds a lien from a shore-walker, and collects it politely."},
        "walked_free": {"text": "You say no clearly, without cruelty, and the market does the rarest thing a "
                                "market can do: it agrees. The Ledger-Keeper marks the refusal in a column you "
                                "suspect is rarer than gold. \"Clean,\" she says. The little lights part for you "
                                "all the way back to the waystones. You leave the Umbral Market with nothing, "
                                "which the market considers the most valuable thing of all.",
                         "return_location": "tidegate",
                         "consequence": "A clean refusal is on file at the Umbral Market, and eases its doors."},
    },
    "echo_offers": {
        "debt_paid": [{"kind": "item", "title": "Umbral token", "detail": "Bought fair, kept warm.",
                       "data": {"item_id": "umbral_token"}},
                      {"kind": "achievement", "title": "Fair Dealer", "detail": "Paid the market what was asked.",
                       "data": {"trait_skill": "persuade", "trait_delta": 1}}],
        "bargain_struck": [{"kind": "achievement", "title": "Loud Bargainer", "detail": "Out-bargained a ledger.",
                            "data": {"trait_skill": "bind", "trait_delta": 1}}],
        "walked_free": [{"kind": "achievement", "title": "Clean Refusal", "detail": "Walked away owing nothing.",
                         "data": {"trait_skill": "endure", "trait_delta": 1}}],
        "debt_taken": [{"kind": "achievement", "title": "Polite Debtor", "detail": "Owed the market something, and smiled anyway.",
                        "data": {"trait_skill": "endure", "trait_delta": 1}}],
    },
})

# add the Ledger-Keeper NPC (gossip-capable)
if not any(n["id"] == "ledger_keeper" for n in pack["npcs"]):
    pack["npcs"].append({
        "id": "ledger_keeper",
        "name": "Vess, Ledger-Keeper",
        "role": "keeper of the Umbral Market's great ledger",
        "location": "umbral_reach",
        "desc": "Precise, courteous, absolutely serious. Every warm thing is owed, and she keeps the sums.",
        "greeting": "\"You again,\" she says, kindly, though you have never been here. \"Or soon.\"",
        "rumors": [
            "\"The ninth entry in every ledger stays open. Ours is no exception.\"",
            "\"Your shore pays in glassbeads. Beads are hours, polished. Spend them like time.\"",
        ],
    })

# ================================================= ADVENTURE: Skyless Light
adventure({
    "id": "skyless_light",
    "title": "The Skyless Light",
    "genre": "supernatural mystery",
    "portal_id": None,
    "entry": "sl_lamp_room",
    "summary": "The lighthouse casts a beam that casts no shadow. Someone is doing the casting.",
    "on_enter": [
        {"quest_update": {"quest_id": "skyless_light", "title": "The Skyless Light", "status": "open",
                          "note": "Something casts the lighthouse beam, and it wants a keeper's name."}},
    ],
    "scenes": {
        "sl_lamp_room": {
            "title": "The Empty Lamp Room",
            "brief": "The lamp room is empty, yet on storm nights the beam sweeps the water. Find the caster.",
            "gm_directive": "Cold and methodical dread. The mystery is administrative: ledgers, logs, a keeper who never left.",
            "intro": "The lamp room is empty. The great lens waits under dust, the wick-holder dry, the oil "
                     "cans sealed for years — and yet out over the water, sweeping patient circles, goes the "
                     "beam that casts no shadow. Something is doing the casting. It has been doing the "
                     "casting for a very long time, and it is good at it.",
            "flavor": [
                "The dust on the floor is undisturbed except by light.",
                "The lens is warm on one side only.",
                "Through the glass, the beam ignores the moon entirely.",
            ],
            "hotspots": [
                {"id": "cold_lens", "label": "the cold lens", "x": 50, "y": 40,
                 "text": "Looking through the lens from inside, the sea is counted — each wave tagged with a small cold numeral."},
                {"id": "oil_cans", "label": "the sealed oil cans", "x": 68, "y": 55,
                 "text": "Sealed with wax, thumb-printed. The thumb is small, like a child's, or like something wearing a child's thumb."},
            ],
            "choices": [
                {"id": "relamp", "label": "Set a new flame in the lamp",
                 "hint": "Requires the Relamp upgrade — a lit lantern is a promise.",
                 "requires_flag": "up_light_relamp",
                 "locked_hint": "The lamp needs a new flame, and the shore would have to fund one. "
                                "Build 'Relamp the Skyless Light' while standing here.",
                 "goto": "sl_ledger_names",
                 "effects": {"flag": "light_relit",
                             "fact": "I relit the Skyless Light. The beam turned teal, and it looks at me kindly now.",
                             "clue": {"thread_id": "ninth_wave",
                                      "text": "The relit beam counted nine waves and stopped, waiting."},
                             "journal": "Set a flame in the empty lamp. The beam went teal and grateful."}},
                {"id": "climb_dark", "label": "Work by feel in the dark stairwell",
                 "hint": "Endure — the dark here is load-bearing.",
                 "check": {"skill": "endure", "hard": False},
                 "on_pass": {"goto": "sl_ledger_names",
                             "effects": {"journal": "Climb the dark stair by feel. The dark allows it, politely."}},
                 "on_fail": {"goto": "sl_ledger_names",
                             "effects": {"harm": {"type": "vigor", "amount": 2},
                                         "fact": "Something in the stairwell counted my steps back down as well as up.",
                                         "journal": "The stairwell counted my steps. I counted the bruises."}}},
                {"id": "step_out", "label": "Step back outside",
                 "hint": "The beam will still be here. It is very patient.",
                 "effects": {"return_shore": True,
                             "journal": "Stepped back out of the Skyless Light. The beam swept on without me."}},
            ],
        },
        "sl_ledger_names": {
            "title": "The Keeper's Name-Ledger",
            "brief": "A ledger of keepers' names. Yours is in it, in the keepers' column.",
            "gm_directive": "The revelation is quiet and enormous: the player has been entered as a keeper.",
            "intro": "Behind the lens hangs the keeper's ledger — names, dates, a column headed 'held the light.' "
                     "The last keeper's entry stops mid-word. And beneath it, in fresh ink that dries as you "
                     "watch, a new entry has been started. It is your name. It is in the keepers' column.",
            "flavor": [
                "The ink is wet and smells of the sea at night.",
                "The ledger's spine is worn soft by hands.",
                "Every entry in the keepers' column is crossed out except yours.",
            ],
            "hotspots": [
                {"id": "your_entry", "label": "your entry", "x": 46, "y": 50,
                 "text": "Your name, the date you first stood on your shore, and a job title: KEEPER, PROVISIONAL."},
            ],
            "choices": [
                {"id": "read_aloud", "label": "Read your entry aloud",
                 "hint": "Bind — names have weight here.",
                 "check": {"skill": "bind", "hard": False},
                 "on_pass": {"goto": "sl_watcher",
                             "effects": {"fact": "Read aloud, my ledger entry answered: 'noted, Keeper.' The voice was the beam.",
                                         "journal": "I read my entry aloud and the beam said 'noted, Keeper.'"}},
                 "on_fail": {"goto": "sl_watcher",
                             "effects": {"fact": "The ledger smudged as I read, as if embarrassed for me.",
                                         "journal": "The ledger smudged my reading. It was almost kind about it."}}},
                {"id": "burn_page", "label": "Tear out and burn your page",
                 "hint": "Might — refuse the appointment by force.",
                 "check": {"skill": "fight", "hard": False},
                 "on_pass": {"effects": {"ending": "page_burned", "beads": 3,
                                         "quest_update": {"quest_id": "skyless_light", "status": "done",
                                                          "note": "Burned the provisional keeper's page. The beam went dim and free."},
                                         "fact": "I burned my page in the keeper's ledger. The beam dimmed, freer.",
                                         "clue": {"thread_id": "ninth_wave",
                                                  "text": "The burned page's smoke spelled a nine before it scattered."},
                                         "journal": "Burned the page. Three beads of melted brass rolled out of the binding."}},
                 "on_fail": {"goto": "sl_watcher",
                             "effects": {"harm": {"type": "vigor", "amount": 2},
                                         "fact": "The page would not tear. The ledger held onto my name like a tide holds a boot.",
                                         "journal": "The page refused to tear. It knows my name better than paper should."}}},
            ],
        },
        "sl_watcher": {
            "title": "The Watcher Below",
            "brief": "The caster of the beam shows itself. Share the light, give the name, or shutter the beam.",
            "gm_directive": "The Watcher is not a monster. It is a duty that outlived its keeper. Let the player feel the weight of three doors.",
            "intro": "It rises through the floor of the lamp room like a note through water: a figure of "
                     "kept-light, a keeper's coat grown with lantern-glass instead of weed. It has been "
                     "holding the beam since its keeper stopped holding it, and it is so tired. It shows you "
                     "three things in order: the flame it cannot light, the name it cannot say, and the "
                     "switch it cannot leave.",
            "flavor": [
                "The Watcher's lantern-glass coat chimes when it breathes.",
                "Its shadow falls behind it, which is the wrong way around.",
                "It looks at your hands, appraising a keeper's hands.",
            ],
            "hotspots": [
                {"id": "kept_light", "label": "the kept-light figure", "x": 52, "y": 44,
                 "text": "Where its face should be: a lens. Through it, you see the shore, from above, watched over for years."},
            ],
            "choices": [
                {"id": "share_flame", "label": "Share your flame with the Watcher",
                 "hint": "Requires having relit the lamp — you carry a lit lantern's promise.",
                 "requires_flag": "light_relit",
                 "locked_hint": "You have no flame of your own to share. Light the lamp first.",
                 "effects": {"ending": "light_shared",
                             "item_give": [{"item_id": "watchers_eye", "qty": 1}],
                             "quest_update": {"quest_id": "skyless_light", "status": "done",
                                              "note": "Shared the flame. The Watcher stood down; the light is shared now, not kept."},
                             "fact": "I shared my flame with the Watcher of the Skyless Light. It stood down, free.",
                             "clue": {"thread_id": "ninth_wave",
                                      "text": "The freed Watcher counted nine waves aloud, and rested."},
                             "npc_rel": {"npc_id": "drowned_lampkeeper", "delta": 1},
                             "journal": "Shared the flame. The beam is shared now — mine, the Watcher's, the shore's."}},
                {"id": "give_name", "label": "Give the Watcher the name it cannot say",
                 "hint": "Bind, hard — a name freely given is a lantern freely lit.",
                 "check": {"skill": "bind", "hard": True},
                 "on_pass": {"effects": {"ending": "name_given", "beads": 2,
                                         "quest_update": {"quest_id": "skyless_light", "status": "done",
                                                          "note": "Gave the Watcher its own name. It said it, and stood down."},
                                         "fact": "The Watcher's name was Brinehold. I gave it back, and it remembered itself.",
                                         "hidden_fact": "Brinehold owes a keeper's shift to whoever freed it. The debt is real and will be honored.",
                                         "clue": {"thread_id": "ninth_wave",
                                                  "text": "Brinehold said: 'the ninth wave is the door. I kept count all my life.'"},
                                         "journal": "Gave the Watcher its name back. Brinehold stood down, humming."}},
                 "on_fail": {"effects": {"ending": "shadow_taken",
                                         "harm": {"type": "nerve", "amount": 3},
                                         "quest_update": {"quest_id": "skyless_light", "status": "failed",
                                                          "note": "The name-giving failed. My shadow keeps the light now, part-time."},
                                         "hidden_fact": "My shadow took a part-time shift holding the beam. It comes home tired.",
                                         "journal": "The name went wrong. My shadow works the light now, evenings."}}},
                {"id": "shutter_beam", "label": "Shutter the beam and end the watching",
                 "hint": "Might, hard — the duty will not go quietly.",
                 "check": {"skill": "fight", "hard": True},
                 "on_pass": {"effects": {"ending": "beam_shuttered", "beads": 2,
                                         "quest_update": {"quest_id": "skyless_light", "status": "done",
                                                          "note": "Shuttered the beam. The watching stopped; the water keeps its own lookouts now."},
                                         "fact": "I shuttered the beam. The water keeps its own lookouts now.",
                                         "clue": {"thread_id": "ninth_wave",
                                                  "text": "When the beam shut, the sea counted out loud: nine, and stopped."},
                                         "journal": "Shuttered the beam. The Watcher bowed, relieved, and fell into rest."}},
                 "on_fail": {"goto": "sl_ledger_names",
                             "effects": {"harm": {"type": "vigor", "amount": 2},
                                         "fact": "The shutter jammed. The beam is stronger than steel and older than hinges.",
                                         "journal": "The shutter refused. The beam carried on, patient as arithmetic."}}},
            ],
        },
    },
    "endings": {
        "light_shared": {"text": "You open your lantern's little glass door and the Watcher leans its lens-face "
                                 "in, close as a cold nose. For a moment the beam and your flame argue about "
                                 "color; then they agree on teal. The coat of lantern-glass slides off the "
                                 "Watcher like a coat at the end of a shift, and what steps out of it is small, "
                                 "dry, and free. It gives you the lens that was its face — the Watcher's Eye — "
                                 "and walks down the stairs it could never leave, out the door it could never "
                                 "see, into the ordinary night. The beam goes on. It is shared now, not kept.",
                          "return_location": "lighthouse",
                          "consequence": "The Skyless Light's beam is shared now, and the Watcher walks free."},
        "name_given": {"text": "You say the name — Brinehold, the name the ledger's smudges were hiding, the "
                               "name the Watcher's own lens-face was too polished to read. The figure says it "
                               "after you, once, in a voice like a lamp being lit. Two glassbeads fall from "
                               "somewhere, because the shore pays for mercies. Brinehold stands down. The "
                               "beam keeps turning, but from now on it is a lighthouse, not a looking.",
                        "return_location": "tidegate",
                        "consequence": "Brinehold, the old keeper of the Skyless Light, remembers its name and owes a shift."},
        "shadow_taken": {"text": "The name goes wrong in your mouth and the Watcher catches it before it "
                                 "drowns — but catching things has a cost, and the cost is you, part-time. "
                                 "Your shadow takes an evening shift holding the beam. You will notice it "
                                 "coming home tired on days you cannot name. The Watcher is very polite about "
                                 "the arrangement. The shore says nothing, but the tavern pours darker.",
                         "return_location": "lighthouse",
                         "consequence": "Someone's shadow works evening shifts at the Skyless Light."},
        "page_burned": {"text": "The page burns badly, the way things burn that were written in duty. Three "
                                "beads of melted brass roll out of the binding — the ledger's own savings, "
                                "pressed into your hand by no hand at all. The beam dims, wavers, and settles "
                                "into something smaller and freer: a lighthouse again, instead of a "
                                "appointment. Somewhere out on the water, a wave is counted, and the count "
                                "stops at nine, satisfied.",
                         "return_location": "lighthouse",
                         "consequence": "A page burned in the Skyless Light; an appointment was refused by fire."},
        "beam_shuttered": {"text": "You force the shutter home through a resistance like deep water, and the "
                                   "beam — the patient, shadowless beam — stops. The quiet afterward is not "
                                   "empty; it is relieved. The Watcher bows the way tired workers bow, and "
                                   "the sea takes up its own watching. Two glassbeads, warm from the mechanism, "
                                   "are your severance. You are not the keeper. You are the one who ended the keeping.",
                           "return_location": "lighthouse",
                           "consequence": "The Skyless Light was shuttered by a visitor, and the sea approved."},
    },
    "echo_offers": {
        "light_shared": [{"kind": "item", "title": "The Watcher's Eye", "detail": "A lens that remembers watching.",
                          "data": {"item_id": "watchers_eye"}},
                         {"kind": "achievement", "title": "Lampfriend", "detail": "Shared a flame with the Watcher.",
                          "data": {"trait_skill": "notice", "trait_delta": 1}}],
        "beam_shuttered": [{"kind": "achievement", "title": "Duty-Ender", "detail": "Shuttered a beam that would not stop.",
                            "data": {"trait_skill": "endure", "trait_delta": 1}}],
        "page_burned": [{"kind": "achievement", "title": "Unappointed", "detail": "Refused a keeper's duty by fire.",
                         "data": {"trait_skill": "fight", "trait_delta": 1}}],
    },
})

PACK.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
print("pack extended:",
      f"{len(pack['locations'])} locations, {len(pack['items'])} items, "
      f"{len(pack['portals'])} portals, {len(pack['adventures'])} adventures, "
      f"{len(pack['npcs'])} npcs, {len(pack['foreshadow_threads'])} threads")
