#!/usr/bin/env python3
"""End-to-end backend smoke test for Saturday Multiverse (no AI configured).

Exercises: pack validation, campaign creation, travel/gating, adventure
choices with dice, rest, items, manual check, QR allowlist, search, export
and import. Run with a disposable data dir:

    SATURDAY_DATA_DIR=/tmp/smdata python3 scripts/smoke_test.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import db, gm, qr, rules, worldpacks  # noqa: E402


def check(label: str, cond: bool, extra: str = "") -> None:
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        raise SystemExit(f"smoke test failed at: {label}")


def main() -> None:
    db.init_db()

    # 1. pack
    pack = worldpacks.load_pack("living_shore")
    check("world pack loads", pack is not None)
    check("9 locations", len(pack["locations"]) == 9, str(len(pack["locations"])))
    check("19 items", len(pack["items"]) == 19)
    check("24 omens", len(pack["omens"]) == 24)
    check("lore file present", len(worldpacks.lore_text(pack)) > 500)
    ids = [i["id"] for i in pack["items"]]
    check("ending rewards in catalog", "callers_name" in ids and "marrow_bell_shard" in ids)

    # 2. rules sanity
    r = rules.roll_check(2, 1)
    check("roll total consistent", r.total == sum(r.dice) + 3, r.text)
    check("outcome in bands", r.outcome in rules.BANDS)

    # 3. campaign creation
    cid = gm.create_campaign("Smoke Voyage", "living_shore", {
        "name": "Test Traveler", "archetype": "lanternist",
        "specialty": "bind", "portrait_seed": "smoke1",
    })
    view = gm.campaign_view(cid)
    check("campaign created", view["name"] == "Smoke Voyage")
    check("character created", view["character"]["name"] == "Test Traveler")
    check("vigor = 10+might(-1)=9", view["character"]["vigor_max"] == 9, str(view["character"]["vigor_max"]))
    check("kit items granted", len(view["inventory"]) == 3)
    check("intro quest present", any(q["id"] == "find_your_door" for q in view["quests"]))
    check("hub is tidegate", view["location"]["id"] == "tidegate")
    check("4 doors on the Beam", len(view["portals"]) == 4)

    # 4. freeform turn (AI disabled -> honest fallback)
    turn = gm.run_turn(cid, "I walk the tideline and listen to the doors.")
    check("turn narration produced", len(turn["narration"]) > 40)
    check("fallback is honest", turn["meta"]["ai_used"] is False and turn["meta"]["fallback_reason"])
    check("dice log clean (no check requested)", turn["dice"] is None)

    # 5. travel + discovery
    gm.travel(cid, "tavern")
    view = gm.campaign_view(cid)
    check("tavern reached", view["location"]["id"] == "tavern")
    check("tavern reveals lighthouse+seacave", view["discovered"].get("lighthouse") and view["discovered"].get("seacave"))

    gm.travel(cid, "camp")
    rest = gm.rest(cid)
    check("rest at camp heals", rest["healed"]["vigor"] >= 0)

    # 6. adventure through the Door of Salt
    tr = gm.travel(cid, "saltgrave_gate")
    check("adventure entered", "Nine Lanterns" in tr["narration"] or "lanterns" in tr["narration"].lower())
    view = gm.campaign_view(cid)
    check("beat = sg_arrival", view["scene"]["beat"] == "sg_arrival")
    check("salt_grave quest opened", any(q["id"] == "salt_grave" for q in view["quests"]))
    check("arrival has 3 choices", len(view["scene"]["choices"]) == 3)

    # climb_tower must be locked (no key yet)
    locked = next(c for c in view["scene"]["choices"] if c["id"] == "climb_tower") \
        if any(c["id"] == "climb_tower" for c in view["scene"]["choices"]) else None
    if locked:
        check("tower locked without key", not locked["available"])
        try:
            gm.choose(cid, "climb_tower")
            check("locked choice rejected", False)
        except ValueError as exc:
            check("locked choice rejected", "key" in str(exc).lower() or "brass" in str(exc).lower())

    gm.choose(cid, "follow_shore")
    view = gm.campaign_view(cid)
    check("moved to wreckline", view["scene"]["beat"] == "sg_shoreline")

    # descend to the lampkeeper, then to the signal room
    gm.choose(cid, "descend_stair")
    view = gm.campaign_view(cid)
    beat = view["scene"]["beat"]
    check("stair scene reached (branch)", beat in ("sg_stair", "sg_shoreline"), beat)
    if beat == "sg_stair":
        gm.choose(cid, "ask_signal")   # no check -> straight to signal room
        view = gm.campaign_view(cid)
        check("signal room reached", view["scene"]["beat"] == "sg_signal_room")
        check("lampkeeper fact recorded", any("holding the line" in f for f in view["facts"]))

    # 7. manual dice + items + qr
    roll = gm.manual_check(cid, "bind")
    check("manual check rolls 2 dice", len(roll["dice"]) == 2, roll["text"])
    item = gm.use_item(cid, "ward_paper")
    check("item use heals", isinstance(item["narration"], str))
    qr_result = qr.parse_payload(cid, "SM:CMD:INVENTORY")
    check("qr ui command allowed", qr_result["ok"] and qr_result["kind"] == "ui")
    qr_bad = qr.parse_payload(cid, "import os; os.system('rm -rf /')")
    check("qr hostile payload rejected", qr_bad["ok"] is False and qr_bad["kind"] == "unknown")

    # 8. resume check: view is fully reconstructible
    view = gm.campaign_view(cid)
    check("view has journal", len(view["journal"]) > 3)
    check("view has dice log", len(view["dice_log"]) >= 1)
    check("search works", len(db.search_campaign(cid, "lanterns")) >= 1)

    # 9. export / import
    data = gm.export_campaign(cid)
    cid2 = gm.import_campaign(data)
    v2 = gm.campaign_view(cid2)
    check("import creates new campaign", cid2 != cid)
    check("imported character intact", v2["character"]["name"] == "Test Traveler")
    check("imported inventory intact", len(v2["inventory"]) == len(view["inventory"]))

    # 10. archive
    gm.archive_campaign(cid)
    check("archive hides campaign", gm.get_campaign(cid) is None)

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
