"""Full game flow through the GM engine (no AI: honest fallback path)."""
from server import db, gm, qr, worldpacks


def test_campaign_lifecycle(campaign):
    view = gm.campaign_view(campaign)
    assert view["location"]["id"] == "tidegate"
    assert len(view["portals"]) == 3
    assert any(q["id"] == "find_your_door" for q in view["quests"])


def test_fallback_turn_is_honest(campaign):
    res = gm.run_turn(campaign, "I walk the tideline, listening.")
    assert res["meta"]["ai_used"] is False
    assert res["meta"]["fallback_reason"]
    assert "Offline Storyteller" in res["narration"]
    assert res["dice"] is None  # fallback never invents checks


def test_travel_and_discovery_chain(campaign):
    gm.travel(campaign, "tavern")
    view = gm.campaign_view(campaign)
    assert view["discovered"].get("lighthouse") and view["discovered"].get("seacave")

    # lighthouse now reachable
    gm.travel(campaign, "lighthouse")
    view = gm.campaign_view(campaign)
    assert view["location"]["id"] == "lighthouse"
    assert any("drowned bay" in f for f in view["facts"])

    # cave is tide-gated; force low tide by drifting forward
    drift = gm.campaign_view(campaign)["drift"]
    target = (6 - (drift % 12)) % 12
    from server import db
    db.execute("UPDATE campaigns SET drift=? WHERE id=?", (drift + target + 1, campaign))
    gm.travel(campaign, "seacave")
    view = gm.campaign_view(campaign)
    assert view["discovered"].get("wreck") is True
    inv = {i["item_id"] for i in gm.get_inventory(campaign)}
    assert "salt_charm" in inv


def test_travel_gates_undiscovered(campaign):
    import pytest
    with pytest.raises(ValueError):
        gm.travel(campaign, "lighthouse")  # not discovered yet


def test_adventure_door_and_state_persistence(campaign):
    gm.travel(campaign, "saltgrave_gate")
    view = gm.campaign_view(campaign)
    assert view["scene"]["beat"] == "sg_arrival"
    assert any(q["id"] == "salt_grave" for q in view["quests"])

    gm.choose(campaign, "follow_shore")
    assert gm.campaign_view(campaign)["scene"]["beat"] == "sg_shoreline"

    # leaving mid-adventure keeps progress; at camp no adventure scene shows
    gm.travel(campaign, "camp")
    view = gm.campaign_view(campaign)
    assert view["scene"]["beat"] is None

    # re-entering the door resumes where the player left off
    res = gm.travel(campaign, "saltgrave_gate")
    assert "remembers you" in res["narration"]
    assert gm.campaign_view(campaign)["scene"]["beat"] == "sg_shoreline"


def test_locked_choice_needs_key(campaign):
    gm.travel(campaign, "saltgrave_gate")
    gm.choose(campaign, "follow_shore")
    import pytest
    with pytest.raises(ValueError) as exc:
        gm.choose(campaign, "climb_tower")
    assert "key" in str(exc.value).lower()


def test_brass_key_opens_the_tower(campaign):
    pack = worldpacks.load_pack("living_shore")
    gm.give_item(campaign, pack, "brass_key")
    gm.travel(campaign, "saltgrave_gate")
    gm.choose(campaign, "follow_shore")
    gm.choose(campaign, "climb_tower")
    assert gm.campaign_view(campaign)["scene"]["beat"] == "sg_signal_room"


def test_endings_and_rewards(campaign):
    pack = worldpacks.load_pack("living_shore")
    gm.give_item(campaign, pack, "brass_key")
    gm.travel(campaign, "saltgrave_gate")
    gm.choose(campaign, "follow_shore")
    gm.choose(campaign, "climb_tower")
    res = gm.choose(campaign, "light_beacon")
    assert res["ending"] == "beacon_lit"
    view = gm.campaign_view(campaign)
    assert "beacon_lit" in view["endings_seen"]
    assert view["location"]["id"] == "tidegate"
    quest = next(q for q in view["quests"] if q["id"] == "salt_grave")
    assert quest["status"] == "done"


def test_pact_ending_grants_relic_and_hidden_fact(campaign):
    pack = worldpacks.load_pack("living_shore")
    gm.give_item(campaign, pack, "brass_key")
    gm.travel(campaign, "saltgrave_gate")
    gm.choose(campaign, "follow_shore")
    gm.choose(campaign, "climb_tower")
    res = gm.choose(campaign, "answer_call")
    # dice decide the branch; both endings are valid, verify consistently
    assert res["ending"] in ("pact", "taken")
    view = gm.campaign_view(campaign)
    if res["ending"] == "pact":
        assert "callers_name" in {i["item_id"] for i in view["inventory"]}
    assert any(q["status"] in ("done", "failed") for q in view["quests"] if q["id"] == "salt_grave")


def test_rest_gating_and_healing(campaign):
    import pytest
    with pytest.raises(ValueError):
        gm.rest(campaign)  # tidegate has no rest
    gm.travel(campaign, "camp")
    ch = gm.get_character(campaign)
    ch["nerve"] = max(0, ch["nerve"] - 3)
    gm._persist_character(ch)
    res = gm.rest(campaign)
    assert res["healed"]["nerve"] > 0


def test_item_use_effects(campaign):
    res = gm.use_item(campaign, "salt_charm")  # sensitive kit includes it
    assert res["narration"]
    import pytest
    with pytest.raises(ValueError):
        gm.use_item(campaign, "callers_name")  # not owned


def test_manual_check_and_omen_consumption(campaign):
    roll = gm.manual_check(campaign, "bind", hard=True)
    assert len(roll["dice"]) == 2 and roll["outcome"] in ("surge", "clean", "riptide", "undertow", "wipeout")
    import pytest
    with pytest.raises(ValueError):
        gm.manual_check(campaign, "diplomacy")  # not a valid skill


def test_qr_allowlist(campaign):
    ok = qr.parse_payload(campaign, "SM:CMD:MAP")
    assert ok["ok"] and ok["kind"] == "ui"
    item = qr.parse_payload(campaign, "SM:ITEM:brass_key")
    assert item["ok"] and item["item"]["id"] == "brass_key"
    lore = qr.parse_payload(campaign, "SM:LORE:cardo_song")
    assert lore["ok"] and "door-song" in lore["lore"]["title"]
    evt = qr.parse_payload(campaign, "SM:EVT:firefly_hour")
    assert evt["ok"] and evt["changes"]
    evil = qr.parse_payload(campaign, "SM:EVT:DROP TABLE campaigns")
    assert evil["ok"] is False
    evil2 = qr.parse_payload(campaign, "__import__('os').system('id')")
    assert evil2["ok"] is False


def test_search_over_history(campaign):
    gm.run_turn(campaign, "I search for lantern oil among the wreckage.")
    db.add_journal(campaign, "Saw a green light in the sea cave.", "player")
    hits = db.search_campaign(campaign, "green light")
    assert hits


def test_export_import_roundtrip(campaign):
    gm.run_turn(campaign, "I watch the doors.")
    data = gm.export_campaign(campaign)
    cid2 = gm.import_campaign(data)
    try:
        v1, v2 = gm.campaign_view(campaign), gm.campaign_view(cid2)
        assert v2["character"]["name"] == v1["character"]["name"]
        assert len(v2["inventory"]) == len(v1["inventory"])
        assert len(v2["journal"]) == len(v1["journal"])
        assert v2["scene"]["beat"] == v1["scene"]["beat"]
    finally:
        gm.archive_campaign(cid2)
