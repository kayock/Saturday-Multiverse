"""v0.4.0 — The Living Worlds.

Regression coverage for every confirmed defect from the release audit,
plus the reliability and engagement acceptance checks. Each defect test
would have FAILED before its repair.
"""
import base64
import pathlib
import json
import shutil
import time
from unittest import mock

import pytest

from server import combat, continuity, director, db, forge, gm, library, mp, rules_dnd, worldpacks
from server.app import create_app


@pytest.fixture()
def api():
    db.init_db()
    return create_app().test_client()


A = "/api"


def _mk(api, name="Harker", **spec):
    body = {"name": name, "ruleset": "dnd5e", "class": "fighter",
            "species": "human", "background": "soldier"}
    body.update(spec)
    r = api.post(A + "/campaigns", json={"name": f"Voyage {name}", "pack_id": "dracula",
                                         "character": body})
    return r.get_json()["campaign_id"]


# ------------------------------------------------------------- 4.1 solo combat
def test_solo_combat_action_submission(api):
    """A solo player can act in combat through the POST endpoint (was 403)."""
    cid = _mk(api)
    ch = gm.get_character(cid)
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        v = combat.start(cid, "giant_rat", 1)
        r = api.post(A + f"/campaigns/{cid}/combat",
                     json={"encounter_id": v["encounter_id"], "type": "defend"})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body.get("log"), "the action resolved through the engine"
    # multiplayer ownership is untouched: forged chid still refused
    other = "chr_does_not_exist"
    r2 = api.post(A + f"/campaigns/{cid}/combat",
                  json={"encounter_id": v["encounter_id"], "type": "defend", "chid": other})
    assert r2.status_code == 403


# ------------------------------------------------------------- 4.2 invalid target costs nothing
def test_invalid_spell_target_preserves_slot(api):
    cid = _mk(api, name="Mina", cls=None, class_="wizard") if False else \
        _mk(api, name="Mina", **{"class": "wizard"})
    sheet0 = gm.get_character(cid)["data"]["dnd"]
    slots0 = dict(sheet0["slots"])
    chid = gm.get_character(cid)["id"]
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        v = combat.start(cid, "giant_rat", 1)
        enc = v["encounter_id"]
        v = combat.view(cid, for_chid=chid)
        assert v["my_turn"]
        with pytest.raises(combat.CombatError):
            combat.action(cid, enc, chid, {"type": "cast", "spell": "magic_missile",
                                           "target": 99})
        sheet1 = gm.get_character(cid)["data"]["dnd"]
        assert sheet1["slots"]["1"] == slots0["1"], "invalid target must not consume a slot"
        # a heal spell aimed at a nonexistent ally also costs nothing
        with pytest.raises(combat.CombatError):
            combat.action(cid, enc, chid, {"type": "cast", "spell": "cure_wounds",
                                           "target": "chr_missing"})
        sheet2 = gm.get_character(cid)["data"]["dnd"]
        assert sheet2["slots"]["1"] == slots0["1"]
        # a VALID cast consumes exactly one slot (the wizard's own spell)
        v2 = combat.view(cid, for_chid=chid)
        if v2 and v2.get("my_turn"):
            combat.action(cid, enc, chid, {"type": "cast", "spell": "magic_missile",
                                           "target": 0})
            sheet3 = gm.get_character(cid)["data"]["dnd"]
            assert sheet3["slots"]["1"] == slots0["1"] - 1
        else:
            # the rat's turn intervened; finish it on the next player turn
            for _ in range(10):
                v3 = combat.view(cid, for_chid=chid)
                if not v3 or v3["status"] == "complete":
                    break
                if v3["my_turn"]:
                    combat.action(cid, enc, chid, {"type": "cast", "spell": "magic_missile",
                                                   "target": 0})
                    sheet3 = gm.get_character(cid)["data"]["dnd"]
                    assert sheet3["slots"]["1"] == slots0["1"] - 1
                    break


# ------------------------------------------------------------- 4.3 SSE replay starvation
def test_replay_survives_501_invisible_events(api):
    cid = _mk(api, name="Host", ruleset=None) if False else \
        api.post(A + "/campaigns", json={"name": "Replay", "pack_id": "dracula",
            "character": {"name": "Host", "archetype": "occultist",
                          "specialty": "bind"}}).get_json()["campaign_id"]
    host = api.post(A + "/mp/host", json={"campaign_id": cid,
                                          "display_name": "L"}).get_json()
    inv = api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 2},
                   headers={"X-MP-Token": host["token"]}).get_json()
    g = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
        "display_name": "Ana", "character": {"name": "Ana", "archetype": "doctor",
                                             "specialty": "lore"}}).get_json()
    gt = {"X-MP-Token": g["token"]}
    for i in range(501):
        mp.emit(cid, "system", "system", {"n": i},
                visibility=f"player:{host['player_id']}")
    mp.emit(cid, "system", "system", {"text": "VISIBLE-MARKER"}, visibility="party")
    page = api.get(A + f"/mp/events/{cid}?last_seq=0", headers=gt).get_json()
    texts = json.dumps(page.get("events", []))
    assert "VISIBLE-MARKER" in texts, "the cursor must advance past invisible events"
    assert page.get("cursor", 0) >= 502, "the scan position advanced"
    # thousands of mixed events: no loss, no duplicates, in order
    for i in range(600):
        mp.emit(cid, "system", "system", {"text": f"pub-{i}"}, visibility="party")
        mp.emit(cid, "system", "system", {"text": f"priv-{i}"},
                visibility=f"player:{host['player_id']}")
    seen = []
    cursor = 0
    for _ in range(10):
        page = api.get(A + f"/mp/events/{cid}?last_seq={cursor}", headers=gt).get_json()
        seqs = [e["seq"] for e in page["events"]]
        assert seqs == sorted(seqs), "ordering preserved"
        assert len(seqs) == len(set(seqs)), "no duplicates"
        seen.extend(e["data"].get("text", "") for e in page["events"])
        cursor = page.get("cursor", cursor)
        if cursor >= page.get("latest_seq", 0):
            break
    pubs = [s for s in seen if s.startswith("pub-")]
    assert len(pubs) == 600, f"all 600 public events delivered, got {len(pubs)}"
    assert not any(s.startswith("priv-") for s in seen), "no private leak"
    # repeated replays are idempotent
    page2 = api.get(A + f"/mp/events/{cid}?last_seq={cursor}", headers=gt).get_json()
    assert page2.get("events") == [] or page2.get("cursor", 0) >= cursor


# ------------------------------------------------------------- 4.4 forge recovery
def test_interrupted_job_recovers_after_restart(api):
    book = "\n".join(f"# C{i}\n\nSallow. Door. Chapter {i}.\n" for i in range(30))
    doc = library.import_document(book.encode(), "b.md")
    job = forge.create_job(doc["id"], "faithful", "short")
    jid = job["id"]
    # simulate an interrupted worker mid-analysis: running lease, dead heartbeat
    db.execute("UPDATE forge_jobs SET status='running', owner='watchdog',"
               " heartbeat='2020-01-01T00:00:00Z', stage='analyzing window 1/4' WHERE id=?",
               (jid,))
    # the watchdog recovery marks it resumable; retry is then accepted
    assert forge.recover_stale_jobs() >= 1
    row = db.query_one("SELECT status, stage FROM forge_jobs WHERE id=?", (jid,))
    assert row["status"] == "failed" and "resume" in row["stage"]
    retried = forge.retry_job(jid)
    assert retried["status"] == "queued"
    # a live lease cannot be stolen by another worker
    db.execute("UPDATE forge_jobs SET status='running', owner='w1', heartbeat=? WHERE id=?",
               (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), jid))
    with pytest.raises(forge.JobError):
        forge.run_job(jid, worker="w2")
    # claim is single-winner
    db.execute("UPDATE forge_jobs SET status='queued', owner=NULL WHERE id=?", (jid,))
    first = forge.claim_next_job("w1")
    assert first == jid
    assert forge.claim_next_job("w2") is None or forge.claim_next_job("w2") != jid
    # no naive timeout: a fresh heartbeat keeps a long job alive
    db.execute("UPDATE forge_jobs SET status='running', owner='w1', heartbeat=? WHERE id=?",
               (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), jid))
    assert forge.recover_stale_jobs() == 0


# ------------------------------------------------------------- 4.5 rejected actions preserve state
def test_rejected_actions_do_not_advance_the_clock(api):
    cid = _mk(api, name="Lost")
    ch = gm.get_character(cid)
    gm.ch_set(ch, "dead", True)
    gm._persist_character(ch)
    t0 = db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,))["turn"]
    with pytest.raises(ValueError):
        gm.run_turn(cid, "I press on regardless")
    t1 = db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,))["turn"]
    assert t1 == t0, "a rejected action must not advance the world clock"
    with pytest.raises(ValueError):
        gm.run_turn(cid, "")  # malformed
    t2 = db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,))["turn"]
    assert t2 == t0


# ------------------------------------------------------------- 4.6 FTS5-less startup
def test_startup_without_fts5(monkeypatch):
    """A build without the fts5 module starts, warns, and searches via LIKE."""
    import shutil
    import sqlite3
    import server.db as dbmod
    from server import config

    scratch = pathlib.Path("/tmp/sm-nolife")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)

    class NoFtsConn:
        """Proxy that fails exactly like a build without the fts5 module."""
        def __init__(self, real):
            self._real = real

        def executescript(self, script):
            if "FTS5" in script.upper():  # a build without the module raises here
                raise Exception("no such module: fts5")
            return self._real.executescript(script)

        def __getattr__(self, name):
            return getattr(self._real, name)

    fresh = sqlite3.connect(str(scratch / "fresh.db"))
    fresh.row_factory = sqlite3.Row
    proxy = NoFtsConn(fresh)
    monkeypatch.setattr(dbmod, "get_conn", lambda: proxy)
    monkeypatch.setattr(config, "DATA_DIR", scratch)
    dbmod._FTS_STATE["available"] = True
    dbmod._FTS_STATE["warning"] = None
    try:
        dbmod.init_db()
        assert not dbmod.fts_available(), "degraded mode reported"
        assert dbmod.fts_warning() and "LIKE" in dbmod.fts_warning()
        book = "\n".join(f"# Chapter {i}\n\nThe salt tide speaks of stone {i}.\n"
                         for i in range(40))
        doc = library.import_document(book.encode(), "b.md")
        hits = library.search("salt tide stone", k=3)
        assert hits, "LIKE fallback returns results"
        from server.app import create_app
        c = create_app().test_client()
        assert c.get(A + "/health").get_json()["fts5"] is False, \
            "diagnostic indicator exposed"
    finally:
        monkeypatch.undo()
        dbmod._FTS_STATE["available"] = True
        dbmod._FTS_STATE["warning"] = None
        fresh.close()
        shutil.rmtree(scratch, ignore_errors=True)
        dbmod._CONN = None
        dbmod.init_db()


def test_story_horizon_blocks_late_revelation(api):
    book = "\n".join(
        (f"# Chapter {i}\n\n" +
         ("An early clue: the WAX-SEAL was pressed with a ring. " if i == 2 else "") +
         ("THE VILLAIN REVEALED: Magistrate Crane wears the ring. " if i == 25 else "") +
         f"Chapter {i} of the marsh inquiry continues.\n")
        for i in range(30))
    doc = library.import_document(book.encode(), "mystery.md", title="The Marsh Inquiry",
                                  author="A. Writer")
    cid = api.post(A + "/campaigns", json={"name": "Mystery", "pack_id": "dracula",
        "character": {"name": "H", "archetype": "occultist", "specialty": "bind"}}
    ).get_json()["campaign_id"]
    # a forge-installed pack binds its source at creation: the campaign state
    # carries source_doc_id + source_horizon (established by _bind_source from
    # the pack's license). Seed that authoritative state here so the test is
    # independent of which other documents exist in the library.
    boundary, total = gm._initial_horizon(doc["id"])
    row = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))
    state = gm.jloads(row["state_json"], {})
    state["source_doc_id"] = doc["id"]
    state["source_total"] = total
    state["source_horizon"] = boundary
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (gm.jdumps(state), cid))
    assert state["source_horizon"] < 25, "the window starts at the opening chapters"
    ctx = {"action_text": "the magistrate and the ring and the villain revealed",
           "horizon": state["source_horizon"]}
    before = library.retrieve_for_prompt(doc["id"], ctx)
    assert not any("CRANE" in p.upper() for p in before), "no late spoiler"
    # legitimate progression advances the window; the reveal becomes retrievable
    st = gm.jloads(db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))["state_json"], {})
    gm._advance_horizon(cid, st, 1.0, "ending reached")
    after = library.retrieve_for_prompt(doc["id"], {**ctx, "horizon": st["source_horizon"]})
    assert any("CRANE" in p.upper() for p in after)


# ------------------------------------------------------------- 4.8 full-text extraction
def test_extraction_beyond_chunk_prefixes(api, monkeypatch):
    chunk = "filler about weather and tides. " * 60
    book = "\n".join(f"# Chapter {i}\n\n{chunk}" +
                     (f"THE HIDDEN KEY lies beneath the millstone of chapter {i}. "
                      if i in (3, 17, 29) else "") + "\n" for i in range(30))
    doc = library.import_document(book.encode(), "long.md")
    from server import ai
    def fake_chat(messages, cfg=None):
        user = messages[-1]["content"]
        if user.startswith("SOURCE EXCERPT"):
            import re
            hits = []
            pos = 0
            while True:
                k = user.find("HIDDEN KEY", pos)
                if k < 0:
                    break
                m = re.search(r"chapter (\d+)", user[k:k + 80])
                if m:
                    hits.append(f"the hidden key lies at chapter {m.group(1)}")
                pos = k + 10
            return ('{"characters":[{"name":"The Miller","role":"keeper","desc":"k"}],'
                    '"locations":[{"name":"The Mill","desc":"millstone"}],'
                    '"plot_points":' + json.dumps(hits) + ',"secrets":[]}', {"model": "mock"})
        if "CONSOLIDATED MATERIAL" in user:
            return ('{"setting":"A mill.","canonical_facts":["the mill keeps the key"],'
                    '"inferred_facts":[],'
                    '"characters":[{"name":"The Miller","role":"keeper","desc":"k",'
                    '"arc":"","status":""}],"relationships":[],'
                    '"timeline":[{"when":"ch 3","what":"key placed"}],"factions":[],'
                    '"secrets":["the millstone hides the key"],'
                    '"ending_summary":"The key surfaces.","divergence_points":[]}',
                    {"model": "mock"})
        if "WORLD BIBLE" in user:
            return ('{"title":"The Mill","summary":"Find the key.","entry":"arrival",'
                    '"quests":[{"id":"key","title":"Find the key"}],'
                    '"gm_secrets":["the millstone hides the key"],'
                    '"scenes":[{"id":"arrival","title":"A","brief":"b","intro":"i",'
                    '"choices":[{"id":"go","label":"g","goto":"end_s"}]},'
                    '{"id":"end_s","title":"E","brief":"b","intro":"i",'
                    '"choices":[{"id":"fin","label":"f","effects":{"ending":"e1"}}]}],'
                    '"endings":{"e1":{"text":"Found.","return_location":"mill",'
                    '"effects":{"ending":"e1"},"consequence":"c"}}}', {"model": "mock"})
        raise ai.AiError("unexpected", "mock")
    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(ai, "get_ai_config",
                        lambda: {"enabled": True, "api_key": "m", "base_url": "http://m",
                                 "model": "m"})
    job = forge.create_job(doc["id"], "faithful", "short")
    res = forge.run_job(job["id"])
    cov = res["coverage"]
    assert cov["characters_processed"] == cov["total_characters"], \
        "100% coverage means 100% of the TEXT, not chunk openings"
    assert cov["sections_skipped"] == 0 and cov["coverage_complete"]
    assert cov["chapters_fully_analyzed"] == cov["chapters"]
    plots = json.dumps(res["profile"]["plot_points"])
    for ch in ("chapter 3", "chapter 17", "chapter 29"):
        assert ch in plots, f"end-of-chunk fact lost: {ch}"


# ------------------------------------------------------------- 5.3 transaction integrity
def test_combat_reward_idempotency(api):
    cid = _mk(api, name="Rewarded")
    ch = gm.get_character(cid)
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        combat.start(cid, "giant_rat", 1)
        enc = combat.get_active(cid)
        enc["state"]["monsters"][0]["hp"] = 0
        enc["state"]["monsters"][0]["alive"] = False
        combat._save(enc)
        combat._resolve_until_player(enc)
        combat._save(enc)
    xp1 = gm.get_character(cid)["data"]["dnd"]["xp"]
    assert xp1 == 25
    row = db.query_one("SELECT * FROM dnd_encounters WHERE campaign_id=?", (cid,))
    combat._finish(combat._as_enc(row), "victory")  # duplicate finish
    assert gm.get_character(cid)["data"]["dnd"]["xp"] == xp1, "rewards exactly once"


# ------------------------------------------------------------- 6.6 backup integrity under WAL
def test_backup_restore_reproduces_state(api):
    cid = _mk(api, name="Backup")
    ch = gm.get_character(cid)
    gm.ch_set(ch, "beads", 12)
    gm._persist_character(ch)
    mp.emit(cid, "narration", "gm", {"text": "The tide remembers.", "changes": []})
    ev_before = mp.latest_seq(cid)
    r = api.post(A + "/backup", json={})
    assert r.status_code == 200, "a whole-database backup can be created"
    bid = r.get_json()["id"]
    bak_path = pathlib.Path(r.get_json()["path"])
    assert bak_path.exists() and bak_path.stat().st_size > 0
    # the backup file reproduces the authoritative state (sqlite3 src.backup()
    # copies a consistent WAL-safe snapshot)
    conn = sqlite3.connect(str(bak_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT data_json FROM characters WHERE campaign_id=?",
                       (cid,)).fetchone()
    assert row and gm.jloads(row["data_json"], {}).get("beads") == 12
    n = conn.execute("SELECT MAX(seq) m FROM mp_events WHERE campaign_id=?",
                     (cid,)).fetchone()
    assert n["m"] == ev_before, "event sequences preserved"
    conn.close()
    r2 = api.post(A + f"/backups/{bid}/restore", json={})
    assert r2.status_code == 200, r2.get_data(as_text=True)[:120]


import sqlite3  # noqa: E402
402


# ================================================================ 16.4 engagement features
def test_returning_player_recap_from_real_events(api):
    from server import experience
    cid = _mk(api, name="Returner")
    ch = gm.get_character(cid)
    pack = worldpacks.load_pack("dracula")
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        combat.start(cid, "wolf", 1)
        enc = combat.get_active(cid)
        enc["state"]["monsters"][0]["hp"] = 0
        enc["state"]["monsters"][0]["alive"] = False
        combat._save(enc)
        combat._resolve_until_player(enc)
        combat._save(enc)
    rec = experience.recap(cid)
    assert rec["is_returning"] is False or rec["turn"] >= 0
    assert any(i["kind"] == "achievement" and "wolf" in i["text"].lower()
               for i in rec["items"]), \
        "the recap cites the actual recorded victory"
    experience.dismiss_recap(cid)
    rec2 = experience.recap(cid)
    assert rec2["dismissed_at"] and rec2["is_returning"] is False


def test_shared_goals_credit_from_engine_events(api):
    from server import experience
    cid = _mk(api, name="Goaled")
    g = experience.create_goal(cid, "Hunt down the shore's foes", target=2)
    pack = worldpacks.load_pack("dracula")
    changes = []
    gm.apply_effects(cid, pack, {"discover": "demeter"}, [], gm.get_character(cid)["id"])
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        combat.start(cid, "wolf", 1)
        enc = combat.get_active(cid)
        enc["state"]["monsters"][0]["hp"] = 0
        enc["state"]["monsters"][0]["alive"] = False
        combat._save(enc)
        combat._resolve_until_player(enc)
        combat._save(enc)
    row = experience.goal_view(g["id"])
    assert row["progress"] == 1, "engine events (victory) credit matching goals"
    # personal scope + abandon
    p = experience.create_goal(cid, "A private vow", target=1, scope="personal")
    assert p["scope"] == "personal"
    experience.abandon_goal(cid, g["id"])
    assert experience.goal_view(g["id"])["status"] == "abandoned"


def test_campfire_stories_are_player_authored_not_engine_proof(api):
    from server import experience, continuity
    cid = _mk(api, name="Fireside")
    s = experience.add_story(cid, "local", "Zoe", "story",
                             "We definitely slew a dragon (we did not).")
    assert s["kind"] == "story"
    stories = experience.list_stories(cid)
    assert any("dragon" in x["text"] for x in stories)
    # the retelling must NEVER become an engine fact: no events, no threads
    evs = mp.events_since(cid, 0)
    assert not any("dragon" in json.dumps(e.get("data", {})).lower() for e in evs
                   if e["type"] not in ("campfire_story",))
    findings = continuity.check(cid)
    assert not any("dragon" in json.dumps(f).lower() for f in findings)
    with pytest.raises(ValueError):
        experience.add_story(cid, "local", "Z", "not-a-kind", "x")


def test_what_if_timelines_stay_isolated(api):
    from server import experience
    cid = _mk(api, name="Trunk")
    ch = gm.get_character(cid)
    gm.ch_set(ch, "beads", 30)
    gm._persist_character(ch)
    api.post(A + "/backup", json={})  # ensure a backup artifact exists
    cp = api.post(A + f"/campaigns/{cid}/checkpoints", json={"name": "before the door"})
    assert cp.status_code == 200
    cp_id = cp.get_json()["checkpoint_id"]
    b = experience.branch_campaign(cid, cp_id, "What if we never knocked?")
    bcid = b["campaign_id"]
    assert bcid != cid
    # play the branch: acquire an item there (a real engine effect)
    bch = gm.get_character(bcid)
    pack = worldpacks.load_pack("dracula")
    item_id = (pack.get("items") or [{}])[0].get("id", "lantern")
    changes = []
    gm.apply_effects(bcid, pack, {"item_give": [{"item_id": item_id, "qty": 1}]},
                     changes, bch["id"])
    assert changes, "the item was granted through the engine"

    gm.run_turn(bcid, "I walk differently in this timeline")
    # the ORIGINAL campaign is untouched
    assert gm.get_character(cid)["data"]["beads"] == 30
    assert not db.query("SELECT * FROM inventory WHERE campaign_id=? AND item_id=?",
                        (cid, item_id)), "no reward leakage into the trunk"
    assert db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,))["turn"] == 0
    # the branch carries its own event stream
    evs = db.query("SELECT type FROM events WHERE campaign_id=?", (bcid,))
    assert any(e["type"] == "turn" for e in evs), "the branch played its own turns"
    evs0 = db.query("SELECT type FROM events WHERE campaign_id=?", (cid,))
    assert not any(e["type"] == "turn" for e in evs0), "the trunk stayed untouched"
    # comparison reports real differences
    cmp_ = experience.compare_timelines(cid, bcid)
    inv = [d for d in cmp_["diffs"] if d["kind"] == "inventory"]
    assert inv and item_id in inv[0]["detail"], "inventory divergence shown"
    assert any(d["kind"] == "turn" for d in cmp_["diffs"])
    branches = experience.list_branches(cid)
    assert any(x["campaign_id"] == bcid for x in branches)
    # no reward duplication into the original
    assert gm.get_character(cid)["data"]["beads"] == 30


def test_engine_trace_reflects_real_rules(api):
    cid = _mk(api, name="Tracer")
    res = gm.run_turn(cid, "I scan the tideline")
    trace = res.get("trace")
    assert trace and trace["steps"]
    assert trace["steps"][0]["step"] == "action"
    assert any(s["step"] == "narration" for s in trace["steps"])
    # when dice were rolled they appear with the authoritative outcome
    if res.get("dice"):
        roll = next(s for s in trace["steps"] if s["step"] == "roll")
        assert roll["result"] == res["dice"]["outcome"]
        assert isinstance(roll["dice"], list)
    # no GM-only leakage: the trace never contains hidden facts
    blob = json.dumps(trace)
    for secret in (pack["gm_secrets"] for pack in [worldpacks.load_pack("dracula")]):
        for s in secret:
            assert s.lower()[:24] not in blob.lower() or len(s) < 12


def test_workshop_playtest_portal_is_isolated(api):
    from server import forge
    v = forge.create_collab("Playtest World", "local", "Zoe")
    d = v["draft_id"]
    pt = forge.start_playtest(d, "Trial Run")
    pcid = pt["campaign_id"]
    row = db.query_one("SELECT state_json, name FROM campaigns WHERE id=?", (pcid,))
    st = gm.jloads(row["state_json"], {})
    assert st.get("playtest_of") == d
    assert "playtest" in row["name"].lower()
    # playing the portal does not approve the draft
    gm.run_turn(pcid, "I test the world")
    assert db.query_one("SELECT status FROM forge_drafts WHERE id=?", (d,))["status"] == "draft"
    # report gives actionable findings
    rep = forge.playtest_report(d, pcid)
    assert "validation_problems" in rep and "flow_findings" in rep
    # stop removes the portal cleanly
    out = forge.stop_playtest(d, pcid)
    assert out["stopped"]
    assert db.query_one("SELECT status FROM campaigns WHERE id=?", (pcid,))["status"] == "archived"
