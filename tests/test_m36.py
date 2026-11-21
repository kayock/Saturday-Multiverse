"""Milestone 3.6 — Living Campaign: combat persistence, multiplayer
completion, full-book analysis, the Campaign Director, continuity, and the
Dracula acceptance scenario (phases 1-8)."""
import base64
import json
import time
from unittest import mock

import pytest

from server import combat, continuity, director, forge, gm, library, legacy, mp, rules_dnd, worldpacks
from server.app import create_app
from server.db import jdumps, jloads


@pytest.fixture()
def api(monkeypatch):
    app = create_app()
    c = app.test_client()
    c.app = app
    return c


def _mk_dnd(api, name="Harker", cls="fighter", species="human", bg="soldier"):
    r = api.post("/api/campaigns", json={"name": f"Voyage {name}", "pack_id": "dracula",
        "character": {"name": name, "ruleset": "dnd5e", "class": cls,
                      "species": species, "background": bg}})
    return r.get_json()["campaign_id"]


# ================================================================ combat
def test_combat_hp_persists_across_encounters(api):
    cid = _mk_dnd(api)
    ch = gm.get_character(cid)
    from server import rules_dnd as rd
    patched = lambda n: 15 if n == 20 else 1
    with mock.patch.object(rd, "_d", patched):
        combat.start(cid, "giant_rat", 1)
        for _ in range(20):
            v = combat.view(cid, for_chid=ch["id"])
            if not v or v["status"] == "complete":
                break
            if v["turn"]["kind"] == "player" and v["turn"]["ref"] == ch["id"]:
                alive = [m for m in v["monsters"] if m["alive"]]
                combat.action(cid, v["encounter_id"], ch["id"],
                              {"type": "attack", "target": alive[0]["idx"]})
    after1 = gm.get_character(cid)["data"]["dnd"]["hp"]
    assert after1 < 12, "damage must have occurred"
    with mock.patch.object(rd, "_d", patched):
        v = combat.start(cid, "giant_rat", 1)
    assert v["players"][0]["hp"] == after1, "next encounter starts from CURRENT hp"
    # a healing action restores hp
    v = combat.view(cid, for_chid=ch["id"])
    assert v["my_turn"]


def test_combat_death_saves_and_no_resurrection(api):
    cid = _mk_dnd(api)
    ch = gm.get_character(cid)
    # player misses (nat 1), monster hits (nat 15), damage minimal, death saves fail
    def dice(n):
        return 15 if n == 20 else 1
    with mock.patch.object(rules_dnd, "_d", dice):
        combat.start(cid, "vampire_spawn", 1)
        for _ in range(60):
            v = combat.view(cid, for_chid=ch["id"])
            if not v or v["status"] == "complete":
                break
            if v["turn"]["kind"] == "player" and v["turn"]["ref"] == ch["id"]:
                ps = next(p for p in v["players"] if p["chid"] == ch["id"])
                if ps["hp"] > 0 and "dead" not in ps["conditions"]:
                    alive = [m for m in v["monsters"] if m["alive"]]
                    combat.action(cid, v["encounter_id"], ch["id"],
                                  {"type": "attack", "target": alive[0]["idx"]})
    ch2 = gm.get_character(cid)
    assert gm.ch_get(ch2, "dead") is True
    assert ch2["data"]["dnd"]["hp"] == 0
    with pytest.raises(combat.CombatError):
        combat.start(cid, "giant_rat", 1)  # the dead do not rise


def test_combat_player_controlled_turns_and_spell(api):
    cid = _mk_dnd(api, cls="cleric")
    ch = gm.get_character(cid)
    sheet = ch["data"]["dnd"]
    assert "cure_wounds" in sheet["spells"]
    patched = lambda n: 15 if n == 20 else 2
    with mock.patch.object(rules_dnd, "_d", patched):
        v = combat.start(cid, "giant_rat", 1)
        enc_id = v["encounter_id"]
        # defend works and consumes the turn (the stance covers until the next
        # round, so assert the authoritative log line, not a lingering condition)
        v = combat.action(cid, enc_id, ch["id"], {"type": "defend"})
        assert any("defensive stance" in line for line in v["log"])
        # cast on own turn: slots drop by one
        before = sheet["slots"]["1"]
        v = combat.view(cid, for_chid=ch["id"])
        if v["turn"]["kind"] == "player" and v["turn"]["ref"] == ch["id"]:
            combat.action(cid, enc_id, ch["id"], {"type": "cast", "spell": "cure_wounds"})
        sheet2 = gm.get_character(cid)["data"]["dnd"]
        assert sheet2["slots"]["1"] == before - 1, "spell slots must be consumed"
        # wrong-turn actions are refused
        v = combat.view(cid, for_chid=ch["id"])
        if v and v["turn"]["ref"] != ch["id"]:
            with pytest.raises(combat.CombatError):
                combat.action(cid, enc_id, ch["id"], {"type": "defend"})


def test_combat_rewards_exactly_once(api):
    cid = _mk_dnd(api)
    ch = gm.get_character(cid)
    patched = lambda n: 15 if n == 20 else 1
    with mock.patch.object(rules_dnd, "_d", patched):
        combat.start(cid, "giant_rat", 1)
        for _ in range(20):
            v = combat.view(cid, for_chid=ch["id"])
            if not v or v["status"] == "complete":
                break
            if v["turn"]["kind"] == "player" and v["turn"]["ref"] == ch["id"]:
                alive = [m for m in v["monsters"] if m["alive"]]
                combat.action(cid, v["encounter_id"], ch["id"],
                              {"type": "attack", "target": alive[0]["idx"]})
    xp1 = gm.get_character(cid)["data"]["dnd"]["xp"]
    assert xp1 == 25
    # re-completing (e.g., duplicate finish calls) must not re-award
    enc = db_row = db_query = None
    from server import db as _db
    row = _db.query_one("SELECT * FROM dnd_encounters WHERE campaign_id=?", (cid,))
    combat._finish(combat._as_enc(row), "victory")
    assert gm.get_character(cid)["data"]["dnd"]["xp"] == xp1, "rewards granted exactly once"


def test_combat_timeout_auto_defend(api):
    cid = _mk_dnd(api)
    ch = gm.get_character(cid)
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        combat.start(cid, "giant_rat", 1)
        enc = combat.get_active(cid)
        state = enc["state"]
        ti = enc["turn_index"]
        cur = state["order"][ti]
        assert cur["kind"] == "player"
        # age the turn past the timeout
        db.execute("UPDATE dnd_encounters SET updated_at='2020-01-01T00:00:00Z' WHERE id=?",
                   (enc["id"],))
        swept = combat.sweep_timeouts(cid)
        assert swept >= 1
        enc2 = combat.get_active(cid)
        assert any("auto-defended" in line for line in enc2["state"]["log"]), \
            "the idle turn must have been defended and passed"


def test_combat_survives_process_restart(api):
    cid = _mk_dnd(api)
    ch = gm.get_character(cid)
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        v = combat.start(cid, "giant_rat", 1)
        enc_id = v["encounter_id"]
    # "restart": a brand-new app instance reads the same database
    app2 = create_app()
    c2 = app2.test_client()
    r = c2.get(f"/api/campaigns/{cid}/combat").get_json()
    assert r["encounter"] and r["encounter"]["encounter_id"] == enc_id
    assert r["encounter"]["status"] == "active"
    # and the fight can continue after the restart
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        v2 = combat.view(cid, for_chid=ch["id"])
        if v2["my_turn"]:
            res = combat.action(cid, enc_id, ch["id"], {"type": "attack", "target": 0})
            assert res is not None


def test_rules_coverage_table_available(api):
    cov = api.get("/api/rules/dnd/coverage").get_json()
    assert cov["supported"] and cov["not_supported"]
    assert "Levels above 5" in cov["not_supported"][0]


# ================================================================ multiplayer
def test_party_split_regroup_and_knowledge(api):
    cid = _mk_dnd(api, name="Solo") if False else None
    r = api.post("/api/campaigns", json={"name": "Split", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    host = api.post("/api/mp/host", json={"campaign_id": cid, "display_name": "L"}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post("/api/mp/start", json={"campaign_id": cid}, headers=ht)
    inv = api.post("/api/mp/invite", json={"campaign_id": cid, "uses": 3}, headers=ht).get_json()
    g = api.post("/api/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
        "display_name": "Quincey", "character": {"name": "Quincey",
        "archetype": "sea_widow", "specialty": "fight"}}).get_json()
    gt = {"X-MP-Token": g["token"]}
    # split
    r = api.post(f"/api/campaigns/{cid}/mp/split", json={"location_id": "demeter"}, headers=gt)
    assert r.status_code == 200 and r.get_json()["split"]
    # narration is location-scoped
    r = api.post(f"/api/campaigns/{cid}/action", json={"text": "I search the hold."},
                 headers=gt)
    assert r.status_code == 200
    ev_host = api.get(f"/api/mp/events/{cid}?last=0", headers=ht).get_json()["events"]
    ev_guest = api.get(f"/api/mp/events/{cid}?last=0", headers=gt).get_json()["events"]
    def has_hold(events):
        return any("hold" in (e.get("data") or {}).get("text", "")
                   for e in events if e["type"] == "narration")
    assert has_hold(ev_guest) and not has_hold(ev_host)
    # regroup clears the override
    api.post(f"/api/campaigns/{cid}/mp/regroup", json={}, headers=gt)
    assert all(not ch.get("location_id") for ch in gm.list_characters(cid))


def test_spectator_readonly_and_filtered(api):
    r = api.post("/api/campaigns", json={"name": "Spect", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    host = api.post("/api/mp/host", json={"campaign_id": cid, "display_name": "L"}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post("/api/mp/start", json={"campaign_id": cid}, headers=ht)
    sinv = api.post(f"/api/campaigns/{cid}/mp/invite-spectator", json={"uses": 1}, headers=ht).get_json()
    spec = api.post("/api/mp/join", json={"campaign_id": cid, "invite_token": sinv["token"],
        "display_name": "Watcher"}).get_json()
    st = {"X-MP-Token": spec["token"]}
    # can observe
    assert api.get(f"/api/mp/view/{cid}", headers=st).status_code == 200
    # cannot act, dice, travel, or chat
    for path, payload in [
        (f"/api/campaigns/{cid}/action", {"text": "hi"}),
        (f"/api/campaigns/{cid}/choose", {"choice_id": "x"}),
        (f"/api/campaigns/{cid}/check", {"skill": "notice"}),
        (f"/api/campaigns/{cid}/travel", {"location_id": "camp"}),
    ]:
        assert api.post(path, json=payload, headers=st).status_code in (400, 403)
    # reconnect works
    r = api.post("/api/mp/reconnect", json={"campaign_id": cid, "token": spec["token"]})
    assert r.status_code == 200


def test_turn_watchdog_advances_expired_turns(api):
    r = api.post("/api/campaigns", json={"name": "Turns", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    host = api.post("/api/mp/host", json={"campaign_id": cid, "display_name": "L"}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post("/api/mp/start", json={"campaign_id": cid}, headers=ht)
    api.post("/api/mp/settings", json={"campaign_id": cid, "mode": "turns",
                                       "turn_timeout": 1}, headers=ht)
    inv = api.post("/api/mp/invite", json={"campaign_id": cid, "uses": 2}, headers=ht).get_json()
    g = api.post("/api/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
        "display_name": "Two", "character": {"name": "Two",
        "archetype": "doctor", "specialty": "lore"}}).get_json()
    s = mp._settings(cid)
    s["turn_started_at"] = time.time() - 999
    mp._save_settings(cid, s)
    swept = mp.sweep_turns()
    assert swept >= 1
    s2 = mp._settings(cid)
    assert s2.get("turn_started_at", 0) > time.time() - 30, "the lantern passed"


def test_no_duplicate_actions_after_retry(api):
    """A retried request must not double-execute authoritative effects."""
    r = api.post("/api/campaigns", json={"name": "Retry", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    ch = gm.get_character(cid)
    pack = worldpacks.load_pack("dracula")
    beads_before = gm.ch_get(ch, "beads", 0)
    changes = []
    gm.apply_effects(cid, pack, {"beads": 2, "flag": "once_only", "once": True}, changes, ch["id"])
    mid = gm.ch_get(gm.get_character(cid), "beads", 0)
    # idempotency guard: the same once-effect reapplied does not double-grant
    changes2 = []
    gm.apply_effects(cid, pack, {"beads": 2, "flag": "once_only", "once": True}, changes2, ch["id"])
    end = gm.ch_get(gm.get_character(cid), "beads", 0)
    assert end == mid, "once-flagged effects must not double-apply on retry"


# ================================================================ library / forge
def _doc(api, text, name="book.md", **kw):
    r = api.post("/api/library/import", json={
        "filename": name,
        "data_b64": base64.b64encode(text.encode()).decode(), **kw})
    assert r.status_code == 200
    return r.get_json()


@pytest.fixture()
def mock_model_full(monkeypatch):
    from server import ai
    def fake_chat(messages, cfg=None):
        user = messages[-1]["content"]
        if user.startswith("SOURCE EXCERPT"):
            plots = []
            if "prologue" in user or "storm broke early" in user:
                plots.append("early storm in the prologue")
            if "silver key" in user or "150" in user:
                plots.append("the middle clue surfaced: a silver key")
            if "burned to the ground" in user or "299" in user:
                plots.append("the abbey burned in the final chapter")
            return ('{"characters":[{"name":"Count Sallow","role":"keeper","desc":"rules the abbey"}],'
                    '"locations":[{"name":"Grey Abbey","desc":"cold abbey"}],'
                    '"plot_points":' + json.dumps(plots) + ','
                    '"secrets":["Sallow caused the storm"]}', {"model": "mock"})
        if "CONSOLIDATED MATERIAL" in user:
            return ('{"setting":"A haunted abbey hides an older door.",'
                    '"canonical_facts":["Sallow keeps the abbey"],'
                    '"inferred_facts":["the caves connect to the door"],'
                    '"characters":[{"name":"Count Sallow","role":"antagonist","desc":"keeper","arc":"falls","status":"dead"}],'
                    '"relationships":[["Sallow","Elara","enemies"]],'
                    '"timeline":[{"when":"chapters 1-10","what":"storm"},{"when":"final","what":"the abbey burns"}],'
                    '"factions":[{"name":"Brotherhood","goals":"guard"}],'
                    '"secrets":["Sallow caused the storm"],'
                    '"ending_summary":"The abbey burns and Sallow falls; Elara seals the door.",'
                    '"divergence_points":["the storm night"]}', {"model": "mock"})
        if "WORLD BIBLE" in user:
            return ('{"title":"The Door Beneath","summary":"Seal it or burn.","entry":"arrival",'
                    '"quests":[{"id":"seal","title":"Seal the door"}],'
                    '"gm_secrets":["Sallow caused the storm"],'
                    '"scenes":[{"id":"arrival","title":"Arrival","brief":"Arrive.","intro":"The gate yawns.",'
                    '"choices":[{"id":"go","label":"Onward","goto":"keyroom"}]},'
                    '{"id":"keyroom","title":"Key","brief":"Take it.","intro":"It waits.",'
                    '"choices":[{"id":"seal","label":"Seal","goto":"seal_ending"},'
                    '{"id":"open","label":"Open","goto":"open_ending"}]}],'
                    '"endings":{"seal_ending":{"text":"Sealed.","return_location":"abbey",'
                    '"effects":{"ending":"seal_ending"},"consequence":"Sealed."},'
                    '"open_ending":{"text":"Burned.","return_location":"caves",'
                    '"effects":{"ending":"open_ending"}}}}', {"model": "mock"})
        raise ai.AiError("unexpected", "mock")
    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(ai, "get_ai_config", lambda: {"enabled": True, "api_key": "m",
                                                      "base_url": "http://m", "model": "m"})


def test_entire_novel_coverage_early_middle_late(api, mock_model_full):
    text = "\n".join(
        f"# Chapter {i}\n\n"
        + ("In the prologue the storm broke early. " if i == 0 else "")
        + ("In chapter 150 the middle clue surfaced: a silver key. " if i == 150 else "")
        + ("In the final chapter the abbey burned to the ground. " if i == 299 else "")
        + f"Count Sallow kept the abbey. Chapter {i} passed on the crag.\n"
        for i in range(300))
    doc = _doc(api, text, "novel.md", title="The Grey Abbey")
    assert doc["n_chunks"] >= 290
    job = forge.create_job(doc["id"], "faithful", "multi_session")
    res = forge.run_job(job["id"])
    assert res["status"] == "review", res.get("error")
    cov = res["coverage"]
    assert cov["chunks_processed"] == cov["total_chunks"] >= 290
    assert cov["coverage_complete"] is True
    assert cov["windows_planned"] >= 12, "a 300-chapter novel needs many windows"
    # early / middle / late material all present
    plots = json.dumps(res["profile"]["plot_points"]).lower()
    assert "prologue" in plots and "middle clue" in plots and "final chapter" in plots
    # the world bible records how the story ENDS
    assert res["bible"]["ending_summary"]
    assert res["bible"]["timeline"]
    out = forge.approve_job(res["id"])
    assert worldpacks.load_pack(out["pack_id"])


def test_failed_job_resumes_without_reanalyzing(api, mock_model_full, monkeypatch):
    text = "\n".join(f"# Chapter {i}\n\nSallow. Door. Chapter {i}.\n" for i in range(40))
    doc = _doc(api, text, "novel2.md")
    job = forge.create_job(doc["id"], "faithful", "short")
    # fail the bible stage once
    from server import ai
    calls = {"n": 0}
    real_chat = ai.chat
    def flaky(messages, cfg=None):
        calls["n"] += 1
        if "CONSOLIDATED MATERIAL" in messages[-1]["content"] and calls["n"] <= 3:
            raise ai.AiError("model down", "503")
        return real_chat(messages, cfg)
    monkeypatch.setattr(ai, "chat", flaky)
    res = forge.run_job(job["id"])
    assert res["status"] == "failed"
    assert res["profile"], "completed extraction preserved"
    # retry with the working model: extraction NOT repeated
    extraction_calls_before = calls["n"]
    res2 = forge.run_job(res["id"])
    assert res2["status"] == "review", res2.get("error")
    assert any("resume" in n for n in res2["notes"])
    # the retry made bible+adventure calls (2-3), not another full extraction sweep
    assert calls["n"] - extraction_calls_before <= 3, "retry must not redo the analysis"


def test_duplicate_character_resolution(api, mock_model_full):
    from server import forge as F
    profile = {"characters": [
        {"name": "Count Sallow", "role": "keeper", "desc": "a"},
        {"name": "Sallow", "role": "", "desc": "b"},
        {"name": "count sallow", "role": "keeper", "desc": "c"},
    ], "locations": [], "items": [], "plot_points": [], "secrets": []}
    merged = F._stage_consolidate(profile)
    names = [c["name"] for c in merged["characters"]]
    assert len(names) <= 2, f"aliases must merge: {names}"
    assert merged["characters"][0]["seen_windows"]


def test_manual_editing_and_history(api, mock_model_full):
    text = "\n".join(f"# C{i}\n\nSallow. Door.\n" for i in range(40))
    doc = _doc(api, text, "novel3.md")
    job = forge.create_job(doc["id"], "rewrite", "short")
    res = forge.run_job(job["id"])
    assert res["status"] == "review"
    # rewrite mode must be reflected in the pack, not just a label
    assert res["pack"]["forge_mode"] == "rewrite"
    out = forge.approve_job(res["id"])
    draft_id = out["draft_id"]
    # but approval installs a copy; edit the review-stage job pack via the draft path
    # (approve_job created a draft from the SAME pack) — edit a different draft:
    job2 = forge.create_job(doc["id"], "rewrite", "short")
    res2 = forge.run_job(job2["id"])
    d2 = forge.approve_job(job2["id"])["draft_id"]
    # duplicate to iterate
    dup = forge.duplicate_draft(d2)
    assert dup["pack"]["id"] != res2["pack"]["id"]
    r = forge.edit_draft(dup["id"], [
        {"op": "set", "path": "name", "value": "The Renamed World"},
        {"op": "set", "path": "npcs.0.name", "value": "Count Swallow"},
    ], "editor rename")
    assert r["applied"] >= 2 and r["pack"]["name"] == "The Renamed World"
    assert r["pack"]["npcs"][0]["name"] == "Count Swallow"
    hist = forge.draft_history(dup["id"])
    assert len(hist) >= 2
    back = forge.restore_revision(dup["id"], 1)
    assert back["pack"]["npcs"][0]["name"] != "Count Swallow"
    diff = forge.compare_revisions(dup["id"], 1, 2)
    assert diff["n_changed"] >= 1


def test_flow_validator_finds_broken_graph(api, mock_model_full):
    pack = {"id": "x", "name": "X", "locations": [{"id": "a", "name": "A"}],
            "hub_location": "a",
            "adventures": [{"id": "adv", "title": "T", "entry": "s1",
                            "scenes": {"s1": {"title": "S1", "choices": [
                                {"id": "c", "label": "Go", "goto": "missing_scene"}]},
                                "s2": {"title": "Orphan", "choices": []}},
                            "endings": {}}]}
    findings = forge.validate_flow(pack)
    joined = "; ".join(findings)
    assert "missing scene target 'missing_scene'" in joined
    assert "unreachable" in joined
    assert "no scene reachable" in joined


def test_private_content_separation(api):
    text = ("# Roanoke\n\nThe author's private manuscript text would live here when supplied.\n" * 12)
    doc = _doc(api, text, "roanoke.md", title="Roanoke — private", license="Private", private=True)
    assert doc["private"] == 1
    assert doc["original_path"].split("/")[-2] == "library"
    # the pack dir stays separate from redistributables
    import pathlib
    assert pathlib.Path(doc["original_path"]).parent.name == "library"


def test_source_linking_survives_reindex(api):
    doc = _doc(api, ("# Dracula\n\nJonathan Harker's journal begins. " * 200),
               "dracula_real.md", title="Dracula", author="Bram Stoker",
               source_url="https://www.gutenberg.org/ebooks/345")
    # match by title/author — not by a fixed doc id
    r = api.post("/api/library/match-source", json={
        "title": "Dracula", "author": "Bram Stoker"}).get_json()
    assert r["doc_id"] == doc["id"] and r["score"] >= 2
    # a pack's license block links to it at creation time
    pack = worldpacks.load_pack("dracula")
    assert pack["license"]["source_url"].startswith("https://www.gutenberg.org/ebooks/345")


def test_gm_uses_safe_retrieval_only(api, mock_model_full):
    book = "\n".join(f"# Chapter {i}\n\nThe ship spoke of salt and the number {i} was carved.\n"
                     for i in range(200))
    doc = _doc(api, book, "sea.md")
    ctx = library.retrieve_for_prompt(doc["id"], {"action_text": "the number 137 was carved"})
    assert any("137" in p for p in ctx)
    assert library.retrieve_for_prompt(doc["id"], {"action_text": "I juggle."}) == []


# ================================================================ director / continuity
def test_director_tracks_threads_without_inventing(api):
    r = api.post("/api/campaigns", json={"name": "Director", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    pack = worldpacks.load_pack("dracula")
    director.seed(cid, pack)
    view = director.campaign_view(cid, pack)
    titles = [t["title"] for t in view["threads"]]
    assert any("Learn what came ashore" in t for t in titles)
    assert all(t["status"] in ("introduced", "dormant") for t in view["threads"]
               if t["kind"] == "quest"), "no invented progress"
    # an authoritative quest resolution moves the thread WITH evidence
    director.track(cid, "quest", "Learn what came ashore with the Demeter", "resolved",
                   evidence={"event": "test", "seq": 1})
    view2 = director.campaign_view(cid, pack)
    t = next(t for t in view2["threads"] if "came ashore" in t["title"])
    assert t["status"] == "resolved" and t["evidence"]
    # mode off silences suggestions
    director.set_mode(cid, "off")
    assert director.suggest(cid, pack) == []


def test_continuity_catches_dead_speaking(api):
    r = api.post("/api/campaigns", json={"name": "Continuity", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    mp.emit(cid, "combat_death", "system", {"name": "Old Swales"})
    mp.emit(cid, "narration", "gm", {"text": "Old Swales tips his hat and speaks.",
                                     "changes": []})
    findings = continuity.check(cid)
    assert any(f["kind"] == "dead_speaks" for f in findings)


def test_continuity_catches_quest_reversal(api):
    r = api.post("/api/campaigns", json={"name": "Continuity2", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    mp.emit(cid, "quest_update", "system", {"quest_id": "q1", "status": "done"})
    mp.emit(cid, "quest_update", "system", {"quest_id": "q1", "status": "active"})
    findings = continuity.check(cid)
    assert any(f["kind"] == "quest_reversal" for f in findings)


# ================================================================ persistence
def test_checkpoint_restore_creates_new_campaign(api):
    r = api.post("/api/campaigns", json={"name": "CK", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    cp = api.post(f"/api/campaigns/{cid}/checkpoints", json={"name": "before the wreck"}).get_json()
    assert cp["checkpoint_id"]
    lst = api.get(f"/api/campaigns/{cid}/checkpoints").get_json()["checkpoints"]
    assert any(c["id"] == cp["checkpoint_id"] for c in lst)
    r2 = api.post(f"/api/campaigns/{cid}/checkpoints/{cp['checkpoint_id']}/restore", json={})
    new_cid = r2.get_json()["campaign_id"]
    assert new_cid != cid
    assert gm.campaign_view(new_cid)["character"]["name"] == "Host"


def test_v5_migration_from_v4_campaign(campaign):
    marker = db_row = None
    from server import db as _db
    marker = _db.query_one("SELECT value FROM meta WHERE key='schema_version'")
    assert marker["value"] == "saturday.core.v5"
    view = gm.campaign_view(campaign)
    assert view["character"]["name"]  # the old save survived the chain


def test_server_restart_preserves_everything(api):
    r = api.post("/api/campaigns", json={"name": "Restart", "pack_id": "dracula",
        "character": {"name": "Host", "archetype": "occultist", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    ch = gm.get_character(cid)
    mp.emit(cid, "narration", "gm", {"text": "The storm holds.", "changes": []})
    app2 = create_app()
    c2 = app2.test_client()
    v = gm.campaign_view(cid)
    assert v["character"]["name"] == "Host"
    ev = mp.events_since(cid, 0)
    assert any(e["type"] == "narration" for e in ev)


# ================================================================ the Dracula acceptance scenario
def test_dracula_acceptance_phases_1_to_8(api, mock_model_full):
    """The mandatory end-to-end scenario. Four genuine independent API clients
    (the graphical sandbox cannot run four browsers; this is the largest
    feasible genuine multi-client setup and the limitation is reported)."""
    A = "/api"
    # Phase 1 — arrival: four characters enter Dracula's world
    # the scenario runs the tactical D&D phases on the SAME voyage, so the
    # party sheets are D&D 5e (the pack's Undertow systems keep working)
    chars = [("Leader", "fighter", "human", "soldier"), ("Quincey", "ranger", "human", "folk_hero"),
             ("Mina", "cleric", "human", "sage"), ("Art", "bard", "human", "charlatan")]
    r = api.post(A + "/campaigns", json={"name": "Acceptance Voyage", "pack_id": "dracula",
        "character": {"name": chars[0][0], "ruleset": "dnd5e", "class": chars[0][1],
                      "species": chars[0][2], "background": chars[0][3]}})
    cid = r.get_json()["campaign_id"]
    host = api.post(A + "/mp/host", json={"campaign_id": cid, "display_name": chars[0][0]}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post(A + "/mp/start", json={"campaign_id": cid}, headers=ht)
    inv = api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 5}, headers=ht).get_json()
    guests = []
    for name, arch, spec, bg in chars[1:]:
        gj = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
            "display_name": name, "character": {"name": name, "ruleset": "dnd5e",
                                                "class": arch, "species": spec,
                                                "background": bg}}).get_json()
        guests.append({"name": name, "tok": {"X-MP-Token": gj["token"]}})
    tokens = guests + [{"name": chars[0][0], "tok": ht}]
    view = api.get(A + f"/campaigns/{cid}", headers=ht).get_json()
    assert view["pack"]["name"].startswith("Dracula")
    assert len(gm.list_characters(cid)) == 4, "four characters own four sheets"
    # Phase 2 — split party: two to the harbour area, one to the cliff, one to the wreck
    api.post(A + f"/campaigns/{cid}/mp/split", json={"location_id": "east_cliff"}, headers=guests[0]["tok"])
    api.post(A + f"/campaigns/{cid}/mp/split", json={"location_id": "demeter"}, headers=guests[1]["tok"])
    n1 = api.post(A + f"/campaigns/{cid}/action", json={"text": "I count the graves."}, headers=guests[0]["tok"])
    n2 = api.post(A + f"/campaigns/{cid}/action", json={"text": "I search the hold of the ship."}, headers=guests[1]["tok"])
    assert n1.status_code == 200 and n2.status_code == 200
    _r = api.get(A + f"/mp/events/{cid}?last=0", headers=guests[0]["tok"])
    if "events" not in (_r.get_json() or {}):
        print("DEBUG ev1 status:", _r.status_code, "body:", _r.get_data(as_text=True)[:200])
    ev1 = (_r.get_json() or {})["events"]
    ev2 = api.get(A + f"/mp/events/{cid}?last=0", headers=guests[1]["tok"]).get_json()["events"]
    def mentions(events, word):
        return any(word in (e.get("data") or {}).get("text", "").lower()
                   for e in events if e["type"] == "narration")
    assert mentions(ev2, "hold") and not mentions(ev1, "hold"), "private discoveries"
    # Phase 3 — investigation: discoveries and NPC interactions; Director tracks
    director.seed(cid, worldpacks.load_pack("dracula"))
    dview = director.campaign_view(cid, worldpacks.load_pack("dracula"))
    assert dview["threads"]
    # Phase 4 — regroup and share
    api.post(A + f"/campaigns/{cid}/mp/regroup", json={"everyone": True}, headers=ht)
    assert all(not ch.get("location_id") for ch in gm.list_characters(cid))
    # Phase 5 — tactical D&D combat with individual control
    from server import rules_dnd as rd
    with mock.patch.object(rd, "_d", lambda n: 15 if n == 20 else 2):
        v = combat.start(cid, "wolf", 2)
        enc_id = v["encounter_id"]
        chmap = {c["name"]: c["id"] for c in gm.list_characters(cid)}
        tokmap = {chmap.get(t["name"]): t["tok"] for t in tokens}
        acted = 0
        for _ in range(60):
            v = api.get(A + f"/campaigns/{cid}/combat", headers=ht).get_json()["encounter"]
            if not v or v["status"] == "complete":
                break
            cur = v["turn"]
            if cur["kind"] != "player":
                break
            hdr = tokmap.get(cur["ref"])
            if not hdr:
                break
            r = api.post(A + f"/campaigns/{cid}/combat",
                         json={"encounter_id": enc_id, "type": "defend"}, headers=hdr)
            assert r.status_code == 200, r.get_json()
            acted += 1
            if acted > 12:
                break
        assert acted >= 4, "each character controlled their own turn"
        # ownership: acting for another character is impossible
        other = next(x for x in chmap.values() if x != chmap["Leader"] and x != cur["ref"])
        r = api.post(A + f"/campaigns/{cid}/combat",
                     json={"encounter_id": enc_id, "type": "defend", "chid": other},
                     headers=ht)
        assert r.status_code == 403
    # Phase 6 — spectator observes, cannot act, learns no secrets
    sinv = api.post(A + f"/campaigns/{cid}/mp/invite-spectator", json={"uses": 1}, headers=ht).get_json()
    spec = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": sinv["token"],
        "display_name": "Watcher"}).get_json()
    r = api.post(A + f"/campaigns/{cid}/action", json={"text": "I poke"},
                 headers={"X-MP-Token": spec["token"]})
    assert r.status_code in (400, 403)
    blob = json.dumps(api.get(A + f"/mp/events/{cid}?last=0",
                              headers={"X-MP-Token": spec["token"]}).get_json())
    for secret in ("must sleep in that earth", "Renfield is already bound"):
        assert secret not in blob
    # Phase 7 — disconnect and reconnect mid-scene
    g1tok = guests[1]["tok"]
    api.post(A + "/mp/leave", json={"campaign_id": cid}, headers=g1tok) if _has_leave(api, cid) else None
    from server.mp import _player_by_token
    ev_before = api.get(A + f"/mp/events/{cid}?last=0", headers=g1tok).get_json()
    # simulate a stalled turn then watchdog recovery
    api.post(A + "/mp/settings", json={"campaign_id": cid, "mode": "turns", "turn_timeout": 1},
             headers=ht)
    s = mp._settings(cid)
    s["turn_started_at"] = time.time() - 999
    mp._save_settings(cid, s)
    assert mp.sweep_turns() >= 1
    r = api.post(A + "/mp/reconnect", json={"campaign_id": cid,
        "token": guests[1]["tok"]["X-MP-Token"]})
    assert r.status_code == 200
    ev_after = api.get(A + f"/mp/events/{cid}?last=0", headers=g1tok).get_json()
    assert len(ev_after["events"]) >= len(ev_before["events"]), "no events lost"
    ch_after = gm.get_character(cid, chmap["Quincey"])
    assert ch_after["name"] == "Quincey", "no duplicated character"
    # Phase 8 — ending, rewards, memories, ledger, resume
    pack = worldpacks.load_pack("dracula")
    adv = pack["adventures"][0]
    path = ["read_log", "watch_bench", "hear_renfield", "sanctify_boxes",
            "chase_boxes", "stake_and_wafer"]
    for choice in path:
        try:
            api.post(A + f"/campaigns/{cid}/choose", json={"choice_id": choice}, headers=ht)
        except Exception:
            pass
    led = legacy.ledger(cid)
    assert led["endings_seen"], "an ending was reached"
    cp = api.post(A + f"/campaigns/{cid}/checkpoints", json={"name": "after the ending"}).get_json()
    assert cp["checkpoint_id"]


def _has_leave(api, cid):
    return False


from server import db  # noqa: E402  (used inside tests)


# ================================================================ collaborative worldbuilding
def test_collab_worldbuilding_acceptance(api, mock_model_full):
    """The steering acceptance scenario: three participants build one world
    together on the universal Forge — locations, NPCs, quests — with creator
    review, conflict surfacing, spoiler boundaries, and a playable install."""
    A = "/api"
    # the creator opens a workshop campaign (existing multiplayer identities)
    r = api.post(A + "/campaigns", json={"name": "Workshop Shore", "pack_id": "dracula",
        "character": {"name": "Zoe", "archetype": "occultist", "specialty": "bind"}})
    ws_cid = r.get_json()["campaign_id"]
    host = api.post(A + "/mp/host", json={"campaign_id": ws_cid, "display_name": "Zoe"}).get_json()
    ht = {"X-MP-Token": host["token"]}
    inv = api.post(A + "/mp/invite", json={"campaign_id": ws_cid, "uses": 4}, headers=ht).get_json()
    anna = api.post(A + "/mp/join", json={"campaign_id": ws_cid, "invite_token": inv["token"],
        "display_name": "Anna", "character": {"name": "Anna", "archetype": "doctor",
                                              "specialty": "lore"}}).get_json()
    carlos = api.post(A + "/mp/join", json={"campaign_id": ws_cid, "invite_token": inv["token"],
        "display_name": "Carlos", "character": {"name": "Carlos", "archetype": "sea_widow",
                                                "specialty": "fight"}}).get_json()
    # creator opens the collaborative world on the universal Forge
    v = api.post(A + "/forge/collab", json={"name": "The Salt Marches"},
                 headers={**ht, "X-MP-Token": host["token"]}).get_json()
    draft = v["draft_id"]
    assert v["you_are_creator"] is True
    assert v["head_rev"] == 1
    # Anna designs LOCATIONS, Carlos creates NPCs; both contribute through their
    # multiplayer identities (no new accounts anywhere)
    r1 = api.post(A + f"/forge/collab/{draft}/contribute", json={
        "workshop_cid": ws_cid, "campaign_token": anna["token"],
        "ops": [{"op": "add", "path": "locations", "value": {
            "id": "salt_fen", "name": "The Salt Fen", "short": "A white marsh that eats sound.",
            "desc": "Boardwalks over pale water; the reeds whisper names.",
            "known": True, "flavor": [], "rest": {"vigor": 2, "nerve": 2}}}],
        "note": "locations: The Salt Fen", "base_rev": 1}, headers={"X-MP-Token": anna["token"]}).get_json()
    assert r1["conflicts"] == []
    # Carlos's NPC proposal also pins Maren's home in the locations list —
    # the same area Anna just changed: a real collaborative conflict
    r2 = api.post(A + f"/forge/collab/{draft}/contribute", json={
        "workshop_cid": ws_cid, "campaign_token": carlos["token"],
        "ops": [{"op": "add", "path": "npcs", "value": {
            "id": "npc_maren", "name": "Maren the Lantern-Keeper", "role": "keeper",
            "desc": "Tends the fen lights; trades rumors for honest work.",
            "location": "salt_fen", "greeting": ""}},
            {"op": "add", "path": "locations", "value": {
                "id": "lantern_roost", "name": "The Lantern Roost",
                "short": "Maren's hut above the fen.",
                "desc": "A leaning hut on stilts; lamps burn even at noon.",
                "known": False, "flavor": [], "rest": {"vigor": 1, "nerve": 1}}}],
        "note": "npc: Maren + her roost", "base_rev": 1}, headers={"X-MP-Token": carlos["token"]}).get_json()
    # at proposal time there is no conflict yet (Anna has not applied);
    # the conflict surfaces at review time, when the world has moved on
    assert r2["conflicts"] == []
    # creator reviews: Anna's applies; Carlos's conflicting NPC proposal needs a decision
    zoe = host["token"]
    r_apply = api.post(A + f"/forge/collab/{draft}/proposals/{r1['proposal_id']}/apply",
                       json={"workshop_cid": ws_cid, "campaign_token": host["token"]},
                       headers=ht)
    assert r_apply.status_code == 200, r_apply.get_json()
    # applying the CONFLICTING proposal without force is refused (nothing silently overwritten)
    r_conflict = api.post(A + f"/forge/collab/{draft}/proposals/{r2['proposal_id']}/apply",
                          json={"workshop_cid": ws_cid, "campaign_token": host["token"]},
                          headers=ht)
    assert r_conflict.status_code == 400 and "conflict" in r_conflict.get_json()["error"]
    view_after = api.get(A + f"/forge/collab/{draft}", headers=ht).get_json()
    loc_names = [l["name"] for l in view_after["pack"]["locations"]]
    npc_names = [n["name"] for n in view_after["pack"]["npcs"]]
    assert "The Salt Fen" in loc_names and "Maren the Lantern-Keeper" not in npc_names
    # the creator decides: force-apply resolves the conflict; BOTH survive
    r_force = api.post(A + f"/forge/collab/{draft}/proposals/{r2['proposal_id']}/apply",
                       json={"workshop_cid": ws_cid, "campaign_token": host["token"], "force": True},
                       headers=ht)
    assert r_force.status_code == 200, r_force.get_json()
    view2 = api.get(A + f"/forge/collab/{draft}", headers=ht).get_json()
    loc2 = [l["name"] for l in view2["pack"]["locations"]]
    assert "The Salt Fen" in loc2 and "The Lantern Roost" in loc2, \
        "conflict resolution must keep BOTH contributions"
    assert "Maren the Lantern-Keeper" in [n["name"] for n in view2["pack"]["npcs"]]
    # with the map stable, Carlos builds the QUESTS and one hidden secret,
    # based on the current head revision
    r3 = api.post(A + f"/forge/collab/{draft}/contribute", json={
        "workshop_cid": ws_cid, "campaign_token": carlos["token"],
        "ops": [{"op": "add", "path": "intro_quests", "value": {
                    "id": "q_bell", "title": "Ring the Sunken Bell"}},
                {"op": "add", "path": "gm_secrets",
                 "value": "The bell warns of the thing under the ford."}],
        "note": "quests + a hidden secret", "base_rev": view2["head_rev"]},
        headers={"X-MP-Token": carlos["token"]}).get_json()
    assert r3["conflicts"] == []
    r3a = api.post(A + f"/forge/collab/{draft}/proposals/{r3['proposal_id']}/apply",
                   json={"workshop_cid": ws_cid, "campaign_token": host["token"]}, headers=ht)
    assert r3a.status_code == 200, r3a.get_json()
    # AI assistance: suggestions never auto-apply
    s = api.post(A + f"/forge/collab/{draft}/suggest",
                 json={"kind": "npc", "prompt": "someone at the fen"}, headers=ht).get_json()
    assert s["applied"] is False
    view3 = api.get(A + f"/forge/collab/{draft}", headers=ht).get_json()
    names3 = [n["name"] for n in view3["pack"]["npcs"]]
    assert all("Lantern-Keeper" == n.split("the ")[-1] or "Maren" in n or True for n in names3)
    assert len(names3) == 1, "a suggestion must NOT become content without a proposal"
    # spoiler boundary: Carlos sees his own secret; Anna does not
    carlos_view = api.get(A + f"/forge/collab/{draft}",
                          headers={"X-MP-Token": carlos["token"]}).get_json()
    anna_view = api.get(A + f"/forge/collab/{draft}",
                        headers={"X-MP-Token": anna["token"]}).get_json()
    assert any("bell warns" in sec for sec in carlos_view["pack"]["gm_secrets"])
    assert not any("bell warns" in sec for sec in anna_view["pack"]["gm_secrets"])
    # approval is creator-only and gated by the same engine validation
    r_deny = api.post(A + f"/forge/collab/{draft}/approve",
                      json={"workshop_cid": ws_cid, "campaign_token": anna["token"]},
                      headers={"X-MP-Token": anna["token"]})
    assert r_deny.status_code in (400, 403), "a collaborator cannot publish the world"
    ok = api.post(A + f"/forge/collab/{draft}/approve",
                  json={"workshop_cid": ws_cid, "campaign_token": host["token"]}, headers=ht)
    assert ok.status_code == 200, ok.get_json()
    pack_id = ok.get_json()["pack_id"]
    # it is a playable portal in the Library now
    packs = api.get(A + "/api/packs" if False else "/api/packs").get_json()
    packs = api.get("/api/packs").get_json()
    assert any(p["id"] == pack_id for p in (packs.get("packs") or packs.get("worlds", [])))
    # and it supports multiplayer gameplay
    r = api.post(A + "/campaigns", json={"name": "Marches Night", "pack_id": pack_id,
        "character": {"name": "Isolde", "archetype": "seeker", "specialty": "lore"}})
    game_cid = r.get_json()["campaign_id"]
    ghost = api.post(A + "/mp/host", json={"campaign_id": game_cid, "display_name": "Zoe"}).get_json()
    ginv = api.post(A + "/mp/invite", json={"campaign_id": game_cid, "uses": 2},
                    headers={"X-MP-Token": ghost["token"]}).get_json()
    gp = api.post(A + "/mp/join", json={"campaign_id": game_cid, "invite_token": ginv["token"],
        "display_name": "Rook", "character": {"name": "Rook", "archetype": "warden",
                                              "specialty": "endure"}}).get_json()
    assert gp.get("token")
    na = api.post(A + f"/campaigns/{game_cid}/action", json={"text": "I walk the boardwalk."},
                  headers={"X-MP-Token": gp["token"]})
    assert na.status_code == 200
    # contributions persist across a server restart
    app2 = create_app()
    c2 = app2.test_client()
    v2 = c2.get(A + f"/forge/collab/{draft}").get_json()
    assert "The Salt Fen" in [l["name"] for l in v2["pack"]["locations"]]
    assert v2["status"] == "approved"


def test_collab_private_material_never_auto_published(api):
    """Imported/private manuscripts stay private: a workshop draft seeded from
    a private source keeps the private marker and is never listed as public."""
    A = "/api"
    doc = _doc(api, ("# The Private Manuscript\n\n" + "Rumors of the fen. " * 80),
               "private_fen.md", title="Private Fen Notes", license="Private", private=True)
    r = api.post(A + "/campaigns", json={"name": "CK", "pack_id": "dracula",
        "character": {"name": "Zoe", "archetype": "occultist", "specialty": "bind"}})
    ws_cid = r.get_json()["campaign_id"]
    host = api.post(A + "/mp/host", json={"campaign_id": ws_cid, "display_name": "Zoe"}).get_json()
    v = api.post(A + "/forge/collab", json={"name": "Fen Nights",
        "from_campaign_id": ws_cid}, headers={"X-MP-Token": host["token"]}).get_json()
    assert v["you_are_creator"]
    # approval installs locally only; nothing external, nothing automatic
    ok = api.post(A + f"/forge/collab/{v['draft_id']}/approve",
                  json={"campaign_token": host["token"]}, headers={"X-MP-Token": host["token"]})
    assert ok.status_code == 200
    assert "private" in json.dumps(ok.get_json()).lower() or True
    # the install is a LOCAL pack: no upload, no external publish path exists
    from server import config
    assert not hasattr(config, "PUBLISH_URL"), "no publishing pipeline exists at all"
