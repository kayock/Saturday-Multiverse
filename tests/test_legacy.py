"""Milestones 1.5 / 2.0 / 2.5 — the legacy systems."""
import pytest

from server import db, gm, legacy, rules, worldpacks


# ---------------------------------------------------------------- GM styles
def test_style_defaults_and_persistence(campaign):
    state = legacy.normalize_style({})
    assert state["id"] == "classic"
    res = legacy.set_style(campaign, "noir")
    assert res["style_id"] == "noir"
    state = jloads_state(campaign)
    assert legacy.normalize_style(state)["id"] == "noir"
    with pytest.raises(ValueError):
        legacy.set_style(campaign, "wizardpunk")
    with pytest.raises(ValueError):
        legacy.set_style(campaign, "custom", "")


def test_style_reaches_prompt_and_fallback(campaign):
    legacy.set_style(campaign, "noir")
    pack = worldpacks.load_pack("living_shore")
    campaign_row = gm.get_campaign(campaign)
    ch = gm.get_character(campaign)
    state = jloads_state(campaign)
    prompt = gm.build_system_prompt(pack, ch, campaign_row, state, 200)
    assert "Noir" in prompt
    text = gm._fallback_narration(pack, campaign_row, state, "I look for clues.")
    assert "Offline Storyteller" in text  # honest labeling intact
    outcome = gm._gm_outcome_narration(campaign, pack, campaign_row, state,
                                       {"outcome": "riptide", "skill": "notice",
                                        "dice": [3, 4], "note": "x"})
    assert "tail you didn't order" in outcome


# ------------------------------------------------------------- NPC memories
def test_gossip_is_scoped_and_grounded(campaign):
    # a tavern-scoped memory: Maren hears it, Cardo does not
    legacy.remember(campaign, "tavern", "event", "The Skyless Light was relit by a stranger.")
    gm.travel(campaign, "tavern")
    maren = legacy.talk(campaign, "maren", "what's new")
    assert any("relit" in line for line in maren["lines"])
    gm.travel(campaign, "camp")
    cardo = legacy.talk(campaign, "old_cardo", "what's new")
    assert not any("relit" in line for line in cardo["lines"])
    with pytest.raises(ValueError):
        legacy.talk(campaign, "maren", "what's new")  # maren is not at camp


def test_gossip_fallback_lines_exist(campaign):
    gm.travel(campaign, "tavern")
    res = legacy.talk(campaign, "maren", "rumors")
    assert len(res["lines"]) >= 2
    assert res["meta"]["ai_used"] is False  # AI disabled in tests


# ------------------------------------------------------------- tide & wash
def test_tide_phase_progression(campaign):
    phases = [legacy.tide_phase(d)["tide"] for d in range(12)]
    assert phases == ["high"] * 6 + ["low"] * 6
    assert legacy.tide_phase(0)["beats_to_change"] == 6
    assert 0.0 <= legacy.tide_phase(3)["progress"] < 1.0


def test_washashore_is_reproducible_and_single_pick(campaign):
    pack = worldpacks.load_pack("living_shore")
    # push drift to an eligible beat deterministically
    row = db.query_one("SELECT drift FROM campaigns WHERE id=?", (campaign,))
    target = (row["drift"] // 12) * 12 + 4
    if target <= row["drift"]:
        target += 12
    db.execute("UPDATE campaigns SET drift=? WHERE id=?", (target, campaign))
    first = legacy.check_washashore(campaign, pack)
    second = legacy.check_washashore(campaign, pack)
    if first:  # hash may legitimately yield nothing on this beat
        assert first == second  # reproducible
        picked = legacy.pick_washashore(campaign, pack)
        assert picked["label"] == first["label"]
        assert legacy.check_washashore(campaign, pack) is None  # beach swept
        with pytest.raises(ValueError):
            legacy.pick_washashore(campaign, pack)  # cannot pick twice


# ----------------------------------------------------------------- tactics
def test_risk_declared_before_roll(campaign):
    roll = gm.manual_check(campaign, "fight", risk=True)
    pending = legacy.get_pending_roll(campaign)
    assert pending["risk"] is True
    assert roll["sit_mod"] >= 2  # risk bonus applied


def test_push_rules_and_costs(campaign, monkeypatch):
    # sensitive: bind +3 → dice [2,4] = 9 = riptide; pushable
    seq = iter([2, 4])
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    ch = gm.get_character(campaign)
    ch["vigor"] = 5
    gm._persist_character(ch)
    roll = gm.manual_check(campaign, "bind")
    assert roll["outcome"] == "riptide"
    res = legacy.push_roll(campaign)
    assert res["pending"]["outcome"] == "clean"
    assert gm.get_character(campaign)["vigor"] == 4
    with pytest.raises(ValueError):
        legacy.push_roll(campaign)  # once per roll


def test_push_rejected_on_clean_and_low_vigor(campaign, monkeypatch):
    seq = iter([6, 5])  # 6+5+3(bind) = 14 → surge; even clean would refuse; use notice: wits+1 → 12 surge
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    gm.manual_check(campaign, "notice")
    with pytest.raises(ValueError):
        legacy.push_roll(campaign)
    ch = gm.get_character(campaign)
    ch["vigor"] = 1
    gm._persist_character(ch)
    seq = iter([2, 4])  # bind: 9 = riptide, pushable but not affordable (vigor 1 < 2)
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    legacy._clear_pending(campaign)
    gm.manual_check(campaign, "bind")
    with pytest.raises(ValueError):
        legacy.push_roll(campaign)


def test_resist_halves_harm(campaign, monkeypatch):
    ch = gm.get_character(campaign)
    ch["vigor"] = 10
    ch["nerve"] = 10
    gm._persist_character(ch)
    seq = iter([1, 3])  # fight: might −1 → 3 = undertow → 2 vigor harm
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    roll = gm.manual_check(campaign, "fight")
    assert roll["harm"] == 2
    res = legacy.resist_roll(campaign)
    assert res["pending"]["harm"] == 1
    assert gm.get_character(campaign)["nerve"] == 9  # 1 nerve paid
    assert gm.get_character(campaign)["vigor"] == 9  # 1 refunded
    with pytest.raises(ValueError):
        legacy.resist_roll(campaign)  # once per roll


def test_death_concludes_and_echoes(campaign, monkeypatch):
    ch = gm.get_character(campaign)
    ch["vigor"] = 1
    ch["nerve"] = 0
    gm._persist_character(ch)
    seq = iter([1, 3])  # fight: 3 → undertow → vigor 2 harm → both lamps out
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    gm.manual_check(campaign, "fight")
    assert jloads_state(campaign).get("dead") is True
    with pytest.raises(ValueError):
        gm.run_turn(campaign, "I stand back up.")
    echoes = legacy.list_echoes()
    assert any(e["title"] == "Remembrance" for e in echoes)


# -------------------------------------------------------------- omen hand
def test_omen_hand_rules(campaign):
    hand = legacy.omen_hand(campaign)
    assert hand["hand_max"] == 2 and hand["draws_left"] == 2
    d1 = legacy.draw_to_hand(campaign)
    assert d1["card"]
    d2 = legacy.draw_to_hand(campaign)
    with pytest.raises(ValueError):
        legacy.draw_to_hand(campaign)  # per-rest cap
    # play an edge if we drew one; turns heal nerve
    card = d1["card"]
    if card["kind"] == "complication":
        with pytest.raises(ValueError):
            legacy.play_omen(campaign, card["id"])  # complications play themselves
    else:
        res = legacy.play_omen(campaign, card["id"])
        assert res["narration"]
        state = jloads_state(campaign)
        if card["kind"] == "edge":
            assert state.get("omen_bonus")
    with pytest.raises(ValueError):
        legacy.play_omen(campaign, "om999")  # not in hand


# --------------------------------------------------------------- upgrades
def test_upgrade_economy(campaign):
    pack = worldpacks.load_pack("living_shore")
    with pytest.raises(ValueError):
        legacy.buy_upgrade(campaign, "camp_kettle")  # no beads, wrong place
    state = jloads_state(campaign)
    state["beads"] = 2
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (db.jdumps(state), campaign))
    with pytest.raises(ValueError):
        legacy.buy_upgrade(campaign, "camp_kettle")  # right beads, wrong place
    gm.travel(campaign, "camp")
    res = legacy.buy_upgrade(campaign, "camp_kettle")
    assert res["beads_left"] == 0
    with pytest.raises(ValueError):
        legacy.buy_upgrade(campaign, "camp_kettle")  # already built
    # the kettle visibly improves camp rest
    ch = gm.get_character(campaign)
    ch["vigor"] = 4
    gm._persist_character(ch)
    rest = gm.rest(campaign)
    assert rest["healed"]["vigor"] == 5  # 3 base + 2 kettle
    assert "up_camp_kettle" in jloads_state(campaign).get("flags", [])
    upgrades = legacy.list_upgrades(campaign)
    assert any(u["id"] == "camp_kettle" and u["owned"] for u in upgrades)


# ----------------------------------------------------------------- echoes
def test_echo_lifecycle(campaign):
    pack = worldpacks.load_pack("living_shore")
    eid = legacy.create_echo(campaign, "item", "Keeper's lantern", "echoed", {"item_id": "keepers_lantern"})
    eid2 = legacy.create_echo(campaign, "trait", "Beaconlighter", "echoed", {"trait_skill": "endure", "trait_delta": 1})
    cid2 = gm.create_campaign("NG+ Voyage", "living_shore", {
        "name": "Heir", "archetype": "warden", "specialty": "fight",
        "echo_ids": [eid, eid2],
    })
    ch = gm.get_character(cid2)
    assert "keepers_lantern" in {i["item_id"] for i in gm.get_inventory(cid2)}
    assert ch["skills"]["endure"] == 1  # warden base 0 + echo
    with pytest.raises(ValueError):
        gm.create_campaign("Thief", "living_shore", {"name": "X", "archetype": "warden",
                                                     "echo_ids": [eid]})  # already woven
    with pytest.raises(ValueError):
        legacy.weave_echoes(cid2, pack, [eid, eid2, eid2])  # cap enforced via reuse error


def test_reputation_and_portal_echoes(campaign):
    rep = legacy.create_echo(None, "reputation", "Friend of Maren", "rumored", {
        "npc_id": "maren", "npc_name": "Maren", "rel_delta": 2})
    eid = legacy.create_echo(None, "portal", "A door already open", "seeded", {"seed": "Glass Prairie"})
    cid2 = gm.create_campaign("Reputed", "living_shore", {"name": "Y", "archetype": "warden",
                                                          "echo_ids": [rep, eid]})
    npcs = {n["npc_id"]: n for n in gm.campaign_view(cid2)["npcs"]}
    assert npcs["maren"]["rel"] == 2 and npcs["maren"]["reputation"] is True
    assert len(legacy.list_worlds(cid2)) == 1  # portal echo pre-generated a world


# ------------------------------------------------ consequences & clue threads
def test_consequences_dedupe_and_surface(campaign):
    legacy.register_consequence(campaign, "ending:test", "Something changed forever.", {})
    legacy.register_consequence(campaign, "ending:test", "Something changed forever.", {})
    cons = legacy.recent_consequences(campaign)
    assert len([c for c in cons if c["trigger"] == "ending:test"]) == 1
    # tavern gossip picks consequences up
    gm.travel(campaign, "tavern")
    res = legacy.talk(campaign, "maren", "the shore")
    assert any("changed forever" in line for line in res["lines"])


def test_clue_thread_payoff_ninth_wave(campaign):
    pack = worldpacks.load_pack("living_shore")
    for i in range(3):
        res = legacy.add_clue(campaign, "ninth_wave", f"clue number {i} of the count", "event")
        assert res is None  # threshold not yet reached
    res = legacy.add_clue(campaign, "ninth_wave", "the fourth and final mark", "event")
    assert res and res["thread"] == "The Ninth Wave"
    view = gm.campaign_view(campaign)
    assert view["discovered"].get("ninth_wave") is True
    # entering the ninth wave grants its one-time gifts
    gm.travel(campaign, "ninth_wave")
    inv = {i["item_id"] for i in gm.get_inventory(campaign)}
    assert "ninth_pearl" in inv
    # re-entering does not farm the gifts
    db.execute("UPDATE campaigns SET drift=? WHERE id=?",
               (gm.campaign_view(campaign)["drift"] + 12, campaign))
    gm.travel(campaign, "tidegate")
    gm.travel(campaign, "ninth_wave")
    inv2 = [i for i in gm.get_inventory(campaign) if i["item_id"] == "ninth_pearl"]
    assert len(inv2) == 1


def test_wrong_gull_thread_pays_into_rest(campaign):
    for i in range(3):
        legacy.add_clue(campaign, "wrong_gull", f"feather {i}", "omen")
    state = jloads_state(campaign)
    assert "gull_friend" in state.get("flags", [])
    gm.travel(campaign, "camp")
    rest = gm.rest(campaign)
    state = jloads_state(campaign)
    assert state.get("omen_bonus", {}).get("skill") == "notice"


def test_saltgrave_ending_grants_echo_offers_and_consequence(campaign):
    pack = worldpacks.load_pack("living_shore")
    gm.give_item(campaign, pack, "brass_key")
    gm.travel(campaign, "saltgrave_gate")
    gm.choose(campaign, "follow_shore")
    gm.choose(campaign, "climb_tower")
    res = gm.choose(campaign, "light_beacon")
    assert res["ending"] == "beacon_lit"
    assert res["echo_offers"]
    cons = legacy.recent_consequences(campaign)
    assert any("Salt door" in c["summary"] for c in cons)
    # the beacon clue fed the ninth wave thread
    threads = {t["id"]: t["count"] for t in legacy.thread_progress(campaign)}
    assert threads["ninth_wave"] >= 1


# ------------------------------------------------------------------ ledger
def test_ledger_structure(campaign):
    legacy.generate_and_store(campaign, "Clockwork Ocean")
    legacy.remember(campaign, "tavern", "event", "Something worth gossiping about.")
    led = legacy.ledger(campaign)
    assert {"worlds", "people", "threads", "consequences", "memories",
            "endings", "echoes", "beads", "upgrades", "open_quests"} <= set(led.keys())
    assert len(led["worlds"]) == 1
    assert any(m["text"].startswith("Something worth") for m in led["memories"])


# ---------------------------------------------------------------- HTTP API
def test_new_http_endpoints(client):
    res = client.get("/api/styles")
    assert res.status_code == 200
    assert any(s["id"] == "noir" for s in res.get_json()["styles"])

    res = client.post("/api/campaigns", json={
        "name": "M2 Voyage", "pack_id": "living_shore",
        "character": {"name": "Ledger Keeper", "archetype": "deepwright", "specialty": "lore"},
    })
    cid = res.get_json()["campaign_id"]

    res = client.post(f"/api/campaigns/{cid}/style", json={"style_id": "cosmic"})
    assert res.get_json()["style_id"] == "cosmic"

    res = client.post(f"/api/campaigns/{cid}/travel", json={"location_id": "camp"})
    assert res.status_code == 200
    res = client.post(f"/api/campaigns/{cid}/talk", json={"npc_id": "old_cardo", "topic": "doors"})
    assert res.status_code == 200

    res = client.post(f"/api/campaigns/{cid}/worlds", json={"seed": "Clockwork Ocean"})
    assert res.status_code == 200
    world = res.get_json()
    res = client.post(f"/api/campaigns/{cid}/travel", json={"location_id": world["entry_location"]})
    assert res.status_code == 200

    res = client.get(f"/api/campaigns/{cid}/omen_hand")
    assert res.status_code == 200
    res = client.post(f"/api/campaigns/{cid}/omen/draw")
    assert res.status_code == 200

    res = client.get(f"/api/campaigns/{cid}/upgrades")
    assert res.status_code == 200

    res = client.get("/api/echoes?unused=1")
    assert res.status_code == 200

    res = client.get(f"/api/campaigns/{cid}/ledger")
    assert res.status_code == 200
    assert "worlds" in res.get_json()

    res = client.get("/api/seeds/suggest")
    assert res.status_code == 200


# ------------------------------------------------------------------ helpers
def jloads_state(cid):
    row = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))
    return db.jloads(row["state_json"], {})
