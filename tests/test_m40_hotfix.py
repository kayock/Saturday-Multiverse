"""v0.4.0 LAN HTTPS & Reliability Hotfix — regression tests.

Each defect test would have FAILED before its repair:
- recap leaked deep-scoped NPC secrets and replayed pre-dismiss history;
- goal mutations were not scoped to the supplied campaign;
- manual requests could fabricate engine-verified goal progress;
- personal-goal ownership was not enforced for multiplayer guests.
"""
import json
import time
from unittest import mock

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

from server import combat, db, experience, gm, legacy, mp, rules_dnd, worldpacks
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


def _victory(cid, monster="Wolf"):
    with mock.patch.object(rules_dnd, "_d", lambda n: 15 if n == 20 else 1):
        combat.start(cid, monster, 1)
        enc = combat.get_active(cid)
        enc["state"]["monsters"][0]["hp"] = 0
        enc["state"]["monsters"][0]["alive"] = False
        combat._save(enc)
        combat._resolve_until_player(enc)
        combat._save(enc)


# ------------------------------------------------------------- recap privacy
def test_recap_never_leaks_deep_scoped_secrets(api):
    cid = _mk(api, name="Secrets")
    gm.run_turn(cid, "I settle in for the night")
    # the lampkeeper's deep-scoped memory: GM/shore-internal knowledge
    legacy.remember(cid, "deep", "gossip",
                    "The drowned lampkeeper hoards the SALT-CROWN below the pier.")
    # a legitimately public shore rumor
    legacy.remember(cid, "all", "gossip",
                    "Trawlers say the tide runs strange since the ship came in.")
    # an explicitly hidden memory of any scope
    db.execute(
        "INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
        " VALUES ('mem_x', ?, '*', ?, 'hidden', 'all', ?)",
        (cid, db.utcnow(), "The ADMINISTRATOR KEY sleeps beneath the jetty."))
    rec = experience.recap(cid)
    blob = json.dumps(rec)
    assert "SALT-CROWN" not in blob, "deep-scoped secret must never reach the recap"
    assert "ADMINISTRATOR KEY" not in blob, "hidden memories never reach the recap"
    assert any("tide runs strange" in i["text"] for i in rec["items"]), \
        "a legitimately public rumor may appear"
    # the API route filters the same way
    r = api.get(A + f"/campaigns/{cid}/recap").get_json()
    assert "SALT-CROWN" not in json.dumps(r)


def test_recap_respects_last_seen_marker(api):
    cid = _mk(api, name="Returner")
    _victory(cid, "wolf")
    legacy.remember(cid, "all", "gossip", "Old Cardo mended the pier lantern.")
    first = experience.recap(cid)
    assert first["is_returning"] is False, "never dismissed yet: nothing is 'new'"
    # dismiss: everything so far becomes seen
    experience.dismiss_recap(cid)
    dismissed_at = first["items"]
    after = experience.recap(cid)
    assert after["has_new"] is False, "dismissed history must not reappear as new"
    assert not any("Wolf" in i["text"] and i["novelty"] == "new"
                   for i in after["items"])
    # a NEW event after the marker appears
    _victory(cid, "giant_rat")
    legacy.remember(cid, "all", "gossip", "Maren saw lights aboard the demeter.")
    again = experience.recap(cid)
    assert again["has_new"] is True
    assert any("giant rat" in i["text"].lower() for i in again["items"] if i["novelty"] == "new")
    assert any("demeter" in i["text"].lower() for i in again["items"] if i["novelty"] == "new")
    # ongoing objectives stay visible but are marked ongoing
    assert all(i["novelty"] == "ongoing" for i in again["items"]
               if i["kind"] in ("unresolved", "now"))


def test_recap_marker_migrates_from_old_saves(api):
    """A save that only has the old recap_seen_turn derives a safe marker."""
    cid = _mk(api, name="Legacy")
    _victory(cid, "wolf")
    gm.run_turn(cid, "I rest")
    old_turn = db.query_one("SELECT turn FROM campaigns WHERE id=?", (cid,))["turn"]
    row = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid,))
    st = gm.jloads(row["state_json"], {})
    st["recap_seen_turn"] = old_turn  # the old marker style
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (gm.jdumps(st), cid))
    rec = experience.recap(cid)
    assert rec["has_new"] is False, "old marker derives a timestamp; history stays seen"
    assert rec["since_marker"] != "1970-01-01T00:00:00Z"
    _victory(cid, "giant_rat")
    rec2 = experience.recap(cid)
    assert any("giant rat" in i["text"].lower() for i in rec2["items"] if i["novelty"] == "new"), \
        "genuinely new events still appear after migration"


def test_recap_no_duplicate_entries_and_solo_still_works(api):
    cid = _mk(api, name="Dedup")
    _victory(cid, "wolf")
    legacy.remember(cid, "all", "gossip", "The same rumor told twice.")
    db.execute(
        "INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
        " VALUES ('mem_d1', ?, '*', ?, 'gossip', 'all', 'The same rumor told twice.')",
        (cid, db.utcnow()))
    db.execute(
        "INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
        " VALUES ('mem_d2', ?, '*', ?, 'gossip', 'all', 'the same rumor TOLD twice.')",
        (cid, db.utcnow()))
    rec = experience.recap(cid)
    texts = [i["text"] for i in rec["items"]]
    assert len(texts) == len(set(t.lower().strip() for t in texts)), "no duplicates"
    # solo (no player) path works
    assert rec["turn"] >= 0
    r = api.get(A + f"/campaigns/{cid}/recap")
    assert r.status_code == 200


# ------------------------------------------------------------- goal integrity
def test_cross_campaign_goal_mutation_is_rejected(api):
    cid_a = _mk(api, name="OwnerA")
    cid_b = _mk(api, name="OwnerB")
    goal_b = experience.create_goal(cid_b, "B's private relic hunt", target=3)
    before = experience.goal_view(goal_b["id"])
    # campaign A references campaign B's goal — rejected WITHOUT any change
    with pytest.raises(ValueError):
        experience.abandon_goal(cid_a, goal_b["id"])
    after = experience.goal_view(goal_b["id"])
    assert after["status"] == before["status"] == "active", "no data changed"
    with pytest.raises(ValueError):
        experience.goal_progress(cid_a, goal_b["id"], 1)
    assert experience.goal_view(goal_b["id"])["progress"] == 0, "no progress leaked"
    # the API surface behaves the same
    r = api.post(A + f"/campaigns/{cid_a}/goals/{goal_b['id']}/abandon", json={})
    assert r.status_code in (400, 404)
    assert experience.goal_view(goal_b["id"])["status"] == "active"
    # the legitimate owner can still abandon their own goal
    out = experience.abandon_goal(cid_b, goal_b["id"])
    assert out["status"] == "abandoned"


def test_manual_progress_cannot_fabricate_verified_achievements(api):
    cid = _mk(api, name="Honest")
    g = experience.create_goal(cid, "Hunt down the shore's foes", target=3)
    # a normal player request: progress allowed, verification is NOT
    r = api.post(A + f"/campaigns/{cid}/goals/{g['id']}/progress",
                 json={"delta": 2, "reason": "I say we did it"})
    assert r.status_code == 200
    row = experience.goal_view(g["id"])
    assert row["progress"] == 2, "voluntary player progress still works"
    assert row["verified_progress"] == 0, "manual requests cannot claim verification"
    assert row["last_source"] == "player"
    # engine events credit BOTH counters
    db.log_event(cid, "combat_victory", {"monster": "wolf", "xp": 50})
    experience.auto_credit(cid, "combat_victory", "victory over wolf")
    row2 = experience.goal_view(g["id"])
    assert row2["progress"] == 3 and row2["status"] == "complete"
    assert row2["verified_progress"] == 1, "exactly the engine-earned increment"
    assert row2["last_source"] == "engine"
    # the client-facing endpoint exposes no verified switch at all
    src = (ROOT / "server" / "api.py").read_text()
    assert "verified=False" in src, "the manual endpoint is hard-wired to verified=False"
    import re
    route = re.search(r"def goals_progress.*?(?=@api\.)", src, re.S).group(0)
    assert "verified=True" not in route


def test_personal_goal_ownership_for_guests(api):
    cid = _mk(api, name="Hostess")
    cid = api.post(A + "/campaigns", json={"name": "Shared Vows", "pack_id": "dracula",
        "character": {"name": "Hostess", "archetype": "occultist",
                      "specialty": "bind"}}).get_json()["campaign_id"]
    host = api.post(A + "/mp/host", json={"campaign_id": cid,
                                          "display_name": "Hostess"}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post(A + "/mp/start", json={"campaign_id": cid}, headers=ht)
    inv = api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 3},
                   headers=ht).get_json()
    g1 = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
        "display_name": "Ana", "character": {"name": "Ana", "archetype": "doctor",
                                             "specialty": "lore"}}).get_json()
    g2 = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
        "display_name": "Ben", "character": {"name": "Ben", "archetype": "doctor",
                                             "specialty": "lore"}}).get_json()
    ana, ben = {"X-MP-Token": g1["token"]}, {"X-MP-Token": g2["token"]}
    # Ana creates a personal goal; ownership is hers
    r = api.post(A + f"/campaigns/{cid}/goals", json={
        "title": "Ana's private vow", "scope": "personal"}, headers=ana)
    assert r.status_code == 200
    gid = r.get_json()["id"]
    assert r.get_json()["owner_player_id"] == g1["player_id"]
    # Ben cannot tick or abandon Ana's goal
    r1 = api.post(A + f"/campaigns/{cid}/goals/{gid}/progress",
                  json={"delta": 1}, headers=ben)
    assert r1.status_code == 403, r1.get_data(as_text=True)[:90]
    r2 = api.post(A + f"/campaigns/{cid}/goals/{gid}/abandon", json={}, headers=ben)
    assert r2.status_code == 403
    assert experience.goal_view(gid)["progress"] == 0, "state unchanged"
    assert experience.goal_view(gid)["status"] == "active"
    # Ben cannot create a personal goal forged to Ana's ownership
    r3 = api.post(A + f"/campaigns/{cid}/goals", json={
        "title": "forged", "scope": "personal",
        "owner_player_id": g1["player_id"]}, headers=ben)
    assert r3.status_code == 403
    # Ana can progress her own goal; the host may also manage it
    ok = api.post(A + f"/campaigns/{cid}/goals/{gid}/progress",
                  json={"delta": 1}, headers=ana)
    assert ok.status_code == 200
    ok2 = api.post(A + f"/campaigns/{cid}/goals/{gid}/progress",
                   json={"delta": 1}, headers=ht)
    assert ok2.status_code == 200, "host may manage personal goals"
    # party goals remain open to every member
    rp = api.post(A + f"/campaigns/{cid}/goals", json={
        "title": "Shared expedition goal", "scope": "party"}, headers=ben)
    assert rp.status_code == 200
    rpb = api.post(A + f"/campaigns/{cid}/goals/{rp.get_json()['id']}/progress",
                   json={"delta": 1}, headers=ana)
    assert rpb.status_code == 200


def test_cross_campaign_checkpoint_and_timeline_references(api):
    from server import experience as ex
    cid_a = _mk(api, name="TrunkA")
    cid_b = _mk(api, name="TrunkB")
    cp_b = api.post(A + f"/campaigns/{cid_b}/checkpoints",
                    json={"name": "B's fork point"}).get_json()
    # campaign A cannot branch from campaign B's checkpoint
    with pytest.raises(ValueError):
        ex.branch_campaign(cid_a, cp_b["checkpoint_id"], "stolen fork")
    assert not db.query("SELECT * FROM campaigns WHERE name LIKE '%stolen fork%'")
    # the API route refuses too
    r = api.post(A + f"/campaigns/{cid_a}/timelines", json={
        "checkpoint_id": cp_b["checkpoint_id"], "name": "stolen fork"})
    assert r.status_code in (400, 404)
    # legitimate branch still works and is isolated
    cp_a = api.post(A + f"/campaigns/{cid_a}/checkpoints",
                    json={"name": "A's fork point"}).get_json()
    b = ex.branch_campaign(cid_a, cp_a["checkpoint_id"], "honest fork")
    assert b["campaign_id"] != cid_a
    # goal listing is campaign-scoped: no cross-campaign rows
    ga = experience.create_goal(cid_a, "A's goal")
    gb = experience.create_goal(cid_b, "B's goal")
    assert [g["id"] for g in experience.list_goals(cid_a)] == [ga["id"]]
    assert [g["id"] for g in experience.list_goals(cid_b)] == [gb["id"]]
    rlist = api.get(A + f"/campaigns/{cid_a}/goals").get_json()
    assert all(g["id"] == ga["id"] for g in rlist["goals"])


def test_invalid_goal_requests_leave_state_unchanged(api):
    cid = _mk(api, name="Steady")
    g = experience.create_goal(cid, "Recover the relics", target=3)
    for payload, expect_status, expect_progress in (
            ({"delta": 0}, 200, 0),        # zero is a legal no-op
            ({"delta": -5}, 200, 0),       # clamped, never negative
            ({"delta": "x"}, 400, 0),      # malformed is refused
    ):
        r = api.post(A + f"/campaigns/{cid}/goals/{g['id']}/progress", json=payload)
        assert r.status_code == expect_status, (payload, r.get_data(as_text=True)[:90])
        row = experience.goal_view(g["id"])
        assert row["progress"] == expect_progress, f"state guard failed: {payload}"
    # nonsense goal ids 404 without creating anything
    r = api.post(A + f"/campaigns/{cid}/goals/goal_missing/progress", json={"delta": 1})
    assert r.status_code == 404
    assert len(db.query("SELECT * FROM party_goals WHERE campaign_id=?", (cid,))) == 1
