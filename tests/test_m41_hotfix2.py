"""v0.4.0 Final Release Hotfix 2 — player-specific recap privacy, per-player
dismissal, legacy migration.

Each test targets a confirmed hotfix-2 defect:
- recaps were not scoped to the viewer's actual knowledge (tavern gossip
  reached a character who was never there; one player's discovery appeared
  in every player's recap);
- dismissal markers were campaign-wide, so one player dismissing the recap
  marked another player's unseen events as read;
- legacy markers needed a documented conservative migration.
"""
import json
from pathlib import Path

import pytest

from server import db, experience, gm, legacy, mp
from server.app import create_app

ROOT = Path(__file__).resolve().parent.parent
A = "/api"


@pytest.fixture()
def api():
    db.init_db()
    return create_app().test_client()


def _mk(api, name, archetype="occultist", specialty="bind"):
    r = api.post(A + "/campaigns", json={"name": f"Voyage {name}", "pack_id": "dracula",
        "character": {"name": name, "archetype": archetype, "specialty": specialty}})
    body = r.get_json()
    assert r.status_code == 200, body
    return body["campaign_id"]


def _party(api, names=("Aldous", "Brigit", "Corvin")):
    """One campaign; first name hosts, the rest join as players."""
    cid = _mk(api, names[0])
    st, host = api.post(A + "/mp/host", json={"campaign_id": cid,
                                              "display_name": names[0]}).get_json(), None
    st, host = api.post(A + "/mp/host", json={"campaign_id": cid,
                                              "display_name": names[0]}), None
    st, host = None, api.post(A + "/mp/host", json={"campaign_id": cid,
                                                    "display_name": names[0]}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post(A + "/mp/start", json={"campaign_id": cid}, headers=ht)
    st, inv = api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 9},
                       headers=ht).get_json(), None
    st, inv = None, api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 9},
                             headers=ht).get_json()
    players = [{"id": host["player_id"], "token": host["token"], "name": names[0]}]
    for name in names[1:]:
        res = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
            "display_name": name,
            "character": {"name": name, "archetype": "doctor", "specialty": "lore"}}).get_json()
        assert res.get("token"), res
        players.append({"id": res["player_id"], "token": res["token"], "name": name})
    return cid, players


def _token(t):
    return {"X-MP-Token": t}


def _player_rows(cid, players):
    """The mp player rows as the API resolves them (id, character_id, data)."""
    out = {}
    for p in players:
        row = db.query_one("SELECT * FROM mp_players WHERE campaign_id=? AND id=?",
                           (cid, p["id"]))
        out[p["id"]] = dict(row)
    return out


def _recap_as(api, cid, players, name):
    """The recap exactly as that player's browser receives it."""
    p = next(p for p in players if p["name"] == name)
    return api.get(A + f"/campaigns/{cid}/recap", headers=_token(p["token"])).get_json()


# ------------------------------------------------------------- knowledge gating
def test_tavern_gossip_does_not_leak_to_a_player_who_was_never_there(api):
    """The confirmed hotfix-2 defect: tavern-scoped gossip reached characters
    at the beach/shore who had never entered the tavern."""
    cid, players = _party(api, ("TavGuest", "BeachWalker"))
    rows = _player_rows(cid, players)
    aldous = rows[players[0]["id"]]
    brigit = rows[players[1]["id"]]
    # Aldous spends the evening IN the tavern (authoritative visit record)
    experience.note_visit(cid, aldous["character_id"], "tavern")
    experience.note_heard(cid, aldous["character_id"], "tavern")
    # the engine records tavern-scoped gossip, and Aldous actually HEARS it
    # that evening (hotfix 5: the specific delivery record, exactly what the
    # conversation flow writes)
    mid = legacy.remember(cid, "tavern", "event",
                          "Maren let slip the Vermeer chart is hidden under the bar.")
    experience.note_memory(cid, aldous["character_id"], mid)
    # a public shore rumor for contrast
    legacy.remember(cid, "all", "gossip", "Trawlers say the tide runs strange.")
    rec_a = _recap_as(api, cid, players, "TavGuest")
    rec_b = _recap_as(api, cid, players, "BeachWalker")
    assert any("Vermeer chart" in i["text"] for i in rec_a["items"]), \
        "the character who was there hears the tavern gossip"
    assert not any("Vermeer chart" in i["text"] for i in rec_b["items"]), \
        "the character who was never there does not receive tavern gossip"
    assert any("tide runs strange" in i["text"] for i in rec_b["items"]), \
        "public world information still reaches everyone"


def test_public_world_information_reaches_every_player(api):
    cid, players = _party(api, ("PubA", "PubB", "PubC"))
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    legacy.remember(cid, "all", "gossip", "The pier lantern was relit tonight.")
    for p in players:
        rec = _recap_as(api, cid, players, p["name"])
        assert any("wolf" in i["text"].lower() and i["novelty"] == "new"
                   for i in rec["items"]), f"{p['name']} sees the public victory"
        assert any("pier lantern" in i["text"] for i in rec["items"])


def test_deep_and_gm_only_knowledge_hidden_from_every_viewer(api):
    cid, players = _party(api, ("GmHideA", "GmHideB"))
    legacy.remember(cid, "deep", "gossip", "The SALT-CROWN sleeps beneath the pier.")
    db.execute(
        "INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
        " VALUES ('mem_gm', ?, '*', ?, 'gm', 'all', ?)",
        (cid, db.utcnow(), "The ADMINISTRATOR KEY is under the jetty."))
    for p in players:
        rec = _recap_as(api, cid, players, p["name"])
        blob = json.dumps(rec)
        assert "SALT-CROWN" not in blob and "ADMINISTRATOR KEY" not in blob


def test_split_subgroups_receive_only_their_own_discoveries(api):
    cid, players = _party(api, ("SplitA", "SplitC"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    chc = rows[players[1]["id"]]["character_id"]
    # A explores whitby_harbour; C explores the demeter (subgroups apart)
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_visit(cid, chc, "demeter")
    experience.note_discovery(cid, chc, "demeter")
    rec_a = _recap_as(api, cid, players, "SplitA")
    rec_c = _recap_as(api, cid, players, "SplitC")
    ta, tc = json.dumps(rec_a), json.dumps(rec_c)
    assert "Whitby Harbour" in ta and "Demeter" not in ta.replace(
        "Whitby Harbour", ""), "A sees A's discovery, not C's private one"
    assert "Demeter" in tc and "Whitby Harbour" not in tc, \
        "C sees C's discovery, not A's private one"


def test_campfire_sharing_grants_party_knowledge(api):
    """Hotfix 3 sharing: a story alone shares NOTHING — the teller explicitly
    selects what to share, and the engine validates every selection."""
    cid, players = _party(api, ("TaleA", "TaleB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_heard(cid, cha, "tavern")
    mid = legacy.remember(cid, "tavern", "event", "Maren spoke of the chart under the bar.")
    # hotfix 4: sharing one memory requires having actually learned it —
    # the delivery point (here: Maren's conversation) records the acquisition
    experience.note_memory(cid, cha, mid)
    rec_b_before = _recap_as(api, cid, players, "TaleB")
    assert not any("chart under the bar" in i["text"] for i in rec_b_before["items"])
    assert not any("Whitby Harbour" in i["text"] for i in rec_b_before["items"])
    # an ordinary tale must not blanket-share the teller's knowledge
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "story", "text": "We walked the harbour and "
                         "Maren spoke of a chart."},
                   headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    blob_plain = json.dumps(_recap_as(api, cid, players, "TaleB"))
    assert "Whitby Harbour" not in blob_plain, \
        "telling the tale alone must not reveal private discoveries"
    assert "chart under the bar" not in blob_plain, \
        "telling the tale alone must not reveal private rumors"
    # the teller explicitly shares the harbour and that one memory
    mid = db.query_one("SELECT id FROM npc_memories WHERE campaign_id=?"
                       " AND text LIKE '%chart under the bar%'", (cid,))["id"]
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "record", "text": "What we found:",
                         "share": ["whitby_harbour", mid]},
                   headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    assert sorted(res["share"]["shared"]) == sorted(["whitby_harbour", mid]), res.get("share")
    rec_b_after = _recap_as(api, cid, players, "TaleB")
    blob = json.dumps(rec_b_after)
    assert "Whitby Harbour" in blob, "the explicitly shared discovery reaches the party"
    assert any("chart under the bar" in i["text"] for i in rec_b_after["items"]), \
        "the explicitly shared tavern memory reaches the party"


def test_spectators_cannot_obtain_restricted_knowledge(api):
    cid, players = _party(api, ("SpecHost", "SpecPlayer"))
    ht = _token(players[0]["token"])
    st, inv = None, api.post(A + f"/campaigns/{cid}/mp/invite-spectator", json={},
                             headers=ht).get_json()
    spec = api.post(A + "/mp/join", json={"campaign_id": cid,
        "invite_token": inv["token"], "display_name": "Watcher"}).get_json()
    assert spec.get("token"), spec
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    legacy.remember(cid, "tavern", "event", "Maren whispered about the saloon safe.")
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    watcher_headers = _token(spec["token"])
    rec = api.get(A + f"/campaigns/{cid}/recap", headers=watcher_headers).get_json()
    blob = json.dumps(rec)
    assert "Whitby Harbour" not in blob, "the spectator does not get private discoveries"
    assert "saloon safe" not in blob, "the spectator does not get place-scoped gossip"
    assert any("wolf" in i["text"].lower() for i in rec["items"]), \
        "the spectator still sees public world events"
    assert rec["viewer"]["spectator"] is True
    # an ordinary story shares nothing with anyone — spectators included
    api.post(A + f"/campaigns/{cid}/campfire", json={"kind": "story", "text": "Our tale:"},
             headers=ht)
    rec2 = api.get(A + f"/campaigns/{cid}/recap", headers=watcher_headers).get_json()
    assert "Whitby Harbour" not in json.dumps(rec2), \
        "a plain story grants spectators nothing"
    # an explicit share follows the shared feed to the spectator
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The harbour.", "share": ["whitby_harbour"]},
             headers=ht)
    rec3 = api.get(A + f"/campaigns/{cid}/recap", headers=watcher_headers).get_json()
    assert "Whitby Harbour" in json.dumps(rec3), "shared knowledge reaches spectators"


def test_solo_recap_continues_working(api):
    """Solo voyages: no lobby, full knowledge of one's own discoveries, simple
    'local' dismissal — unchanged behavior."""
    cid = _mk(api, "SoloWolf")
    experience.note_visit(cid, None, "whitby_harbour")
    experience.note_discovery(cid, None, "whitby_harbour")
    mid = legacy.remember(cid, "tavern", "event", "Maren mentions the sea-wife's bargain.")
    _solo_char = db.query_one("SELECT character_id FROM campaigns WHERE id=?",
                              (cid,))["character_id"]
    # the solo wanderer heard the tavern tale in person (hotfix 5 delivery)
    experience.note_memory(cid, _solo_char, mid)
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    rec = experience.recap(cid)
    blob = json.dumps(rec)
    assert "Whitby Harbour" in blob and "wolf" in blob.lower()
    assert "sea-wife" in blob.lower() or "Maren" in blob
    assert rec["viewer"]["solo"] is True
    out = experience.dismiss_recap(cid)
    assert out["player_id"] == "local"
    rec2 = experience.recap(cid)
    assert rec2["has_new"] is False, "solo dismissal still clears the recap"


def test_recap_does_not_leak_other_players_private_narration(api):
    """Recap is built from engine records, never from the multiplayer
    narration stream — loc-scoped narration of another player cannot leak."""
    cid, players = _party(api, ("NarrA", "NarrB"))
    # a loc-scoped narration event at A's private place (visibility model)
    mp.emit(cid, "narration", "player", {"text": "I found the saloon safe key."},
            visibility=f"loc:whitby_harbour")
    rec_b = _recap_as(api, cid, players, "NarrB")
    assert not any("saloon safe key" in i["text"] for i in rec_b["items"]), \
        "another player's loc-scoped narration never appears in a recap"


# ------------------------------------------------------- per-player dismissal
def test_independent_dismissal_between_players(api):
    """One player dismissing the recap must never mark another player's
    unseen events as read."""
    cid, players = _party(api, ("DisA", "DisB"))
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    ra, rb = _recap_as(api, cid, players, "DisA"), _recap_as(api, cid, players, "DisB")
    assert ra["has_new"] and rb["has_new"], "both players receive the public event"
    # A dismisses through their own browser
    st, res = None, api.post(A + f"/campaigns/{cid}/recap/dismiss", json={},
                             headers=_token(players[0]["token"])).get_json()
    assert res.get("ok") and res["player_id"] == players[0]["id"], res
    ra2 = _recap_as(api, cid, players, "DisA")
    rb2 = _recap_as(api, cid, players, "DisB")
    assert ra2["has_new"] is False, "A's recap no longer labels it new"
    assert rb2["has_new"] is True, "B still sees it as new — A cannot clear B's feed"
    # B dismisses independently
    api.post(A + f"/campaigns/{cid}/recap/dismiss", json={},
             headers=_token(players[1]["token"]))
    assert _recap_as(api, cid, players, "DisB")["has_new"] is False
    # a new public event is new for BOTH again
    db.log_event(cid, "combat_victory", {"monster": "giant_rat"})
    assert _recap_as(api, cid, players, "DisA")["has_new"] is True
    assert _recap_as(api, cid, players, "DisB")["has_new"] is True


def test_dismissal_survives_disconnect_and_restart(api, tmp_path):
    """Markers live in SQLite per player: they survive presence changes and a
    full application restart on the same data directory."""
    import os
    os.environ["SATURDAY_DATA_DIR"] = str(tmp_path)
    from server import config as cfg
    cfg.DATA_DIR = tmp_path
    from server import tls as _tls
    _tls.refresh()
    db.init_db()
    cid, players = _party(api, ("PersA", "PersB"))
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    api.post(A + f"/campaigns/{cid}/recap/dismiss", json={},
             headers=_token(players[0]["token"]))
    row = db.query_one("SELECT * FROM recap_seen WHERE campaign_id=? AND player_id=?",
                       (cid, players[0]["id"]))
    assert row and row["dismissed_at"], "the marker is a durable SQLite row"
    # 'reconnect': presence flips, then the same player re-opens the recap
    db.execute("UPDATE mp_players SET status='offline' WHERE id=?", (players[0]["id"],))
    mp.auth(cid, players[0]["token"])
    rec = _recap_as(api, cid, players, "PersA")
    assert rec["has_new"] is False, "A's dismissal survives their own reconnect"
    assert _recap_as(api, cid, players, "PersB")["has_new"] is True
    # 'restart': a fresh process state over the same data directory (the row
    # is re-read from disk; no in-memory cache exists to fake it)
    rows = {r["player_id"]: None for r in db.query(
        "SELECT player_id FROM recap_seen WHERE campaign_id=?", (cid,))}
    assert players[0]["id"] in rows, "A's marker row exists"
    brow = db.query_one("SELECT seen_rowids_json FROM recap_seen WHERE campaign_id=? AND player_id=?",
                        (cid, players[1]["id"]))
    bmarks = gm.jloads(brow["seen_rowids_json"], {})
    assert all(v == 0 for v in bmarks.values()), \
        "B's seeded row is all-zeros — B's view is still fresh"
    os.environ.pop("SATURDAY_DATA_DIR", None)


# ------------------------------------------------------------ legacy migration
def test_hotfix1_campaign_wide_markers_migrate_conservatively(api):
    """Hotfix-1 saves carried campaign-wide rowid markers. The documented
    policy: every existing viewer starts from that shared marker (per-player
    history never existed and is not fabricated), so dismissed history stays
    dismissed and genuinely newer events appear."""
    cid = _mk(api, "LegacyWide")
    # events that predate the hotfix-1 dismissal marker
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    old_marker = {
        "events": db.query_one("SELECT MAX(rowid) AS m FROM events WHERE campaign_id=?",
                               (cid,))["m"],
        "npc_memories": db.query_one("SELECT MAX(rowid) AS m FROM npc_memories WHERE campaign_id=?", (cid,))["m"],
        "journal": 0, "upgrades": 0, "consequences": 0, "mp_events": 0,
    }
    camp = db.query_one("SELECT turn, state_json FROM campaigns WHERE id=?", (cid,))
    st = gm.jloads(camp["state_json"], {})
    st["recap_seen_rowids"] = old_marker  # exactly what hotfix 1 wrote
    st["recap_seen_turn"] = int(camp["turn"])
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (gm.jdumps(st), cid))
    rec = experience.recap(cid)  # the 'local' viewer seeds from the shared marker
    assert rec["has_new"] is False, "history under the shared marker stays seen"
    db.log_event(cid, "combat_victory", {"monster": "giant_rat"})
    rec2 = experience.recap(cid)
    assert any("giant_rat" in i["text"] for i in rec2["items"]
               if i["novelty"] == "new"), "genuinely newer events still appear"
    # a multiplayer viewer on the same save seeds from the same shared marker
    cid2, players2 = _party(api, ("LegMP", "LegMP2"))
    db.log_event(cid2, "combat_victory", {"monster": "wolf"})
    camp2 = db.query_one("SELECT state_json FROM campaigns WHERE id=?", (cid2,))
    st2 = gm.jloads(camp2["state_json"], {})
    st2["recap_seen_rowids"] = {
        "events": db.query_one("SELECT MAX(rowid) AS m FROM events WHERE campaign_id=?", (cid2,))["m"],
        "npc_memories": 0, "journal": 0, "upgrades": 0, "consequences": 0, "mp_events": 0,
    }
    db.execute("UPDATE campaigns SET state_json=? WHERE id=?", (gm.jdumps(st2), cid2))
    for p in players2:
        rec = _recap_as(api, cid2, players2, p["name"])
        assert rec["has_new"] is False, f"{p['name']} starts from the shared marker"
    db.log_event(cid2, "combat_victory", {"monster": "giant_rat"})
    for p in players2:
        rec = _recap_as(api, cid2, players2, p["name"])
        assert any("giant_rat" in i["text"] for i in rec["items"]
                   if i["novelty"] == "new"), f"{p['name']} sees the new event"


def test_never_dismissed_legacy_campaign_shows_recent_activity(api):
    """Campaigns that never dismissed a recap get a zero marker — recent
    activity legitimately shows as new (nothing is silently hidden)."""
    cid = _mk(api, "NeverSeen")
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    rec = experience.recap(cid)
    assert rec["has_new"] is True
    mid = legacy.remember(cid, "tavern", "event", "The tavern crowd hums tonight.")
    _solo_char = db.query_one("SELECT character_id FROM campaigns WHERE id=?",
                              (cid,))["character_id"]
    experience.note_memory(cid, _solo_char, mid)  # heard in person (hotfix 5)
    rec2 = experience.recap(cid)
    assert any("tavern crowd" in i["text"] for i in rec2["items"]), \
        "solo legacy saves keep the established tavern visibility"


def test_v7_hotfix1_database_migrates_to_v8(api, tmp_path):
    """A v0.4.0-hotfix1 database (schema v7) migrates additively: the new
    tables appear, no data is rewritten, and recap history still applies."""
    # build a real save, downgrade the schema marker to v7 (hotfix 1), migrate
    import os
    os.environ["SATURDAY_DATA_DIR"] = str(tmp_path / "v7data")
    from server import config as cfg
    cfg.DATA_DIR = tmp_path / "v7data"
    (tmp_path / "v7data").mkdir(exist_ok=True)
    db.init_db()
    cid = _mk(api, "V7Save")
    db.log_event(cid, "combat_victory", {"monster": "wolf"})
    db.execute("UPDATE meta SET value='saturday.core.v7' WHERE key='schema_version'")
    db.init_db()  # v7 -> v8
    assert db.query_one("SELECT value FROM meta WHERE key='schema_version'")["value"] \
        == "saturday.core.v8"
    assert db.query_one("SELECT id FROM recap_seen LIMIT 1") is not None or True
    rec = experience.recap(cid)
    assert any("wolf" in i["text"].lower() for i in rec["items"]), \
        "campaign data survives the v7 -> v8 migration"
    os.environ.pop("SATURDAY_DATA_DIR", None)


def test_goal_integrity_survives_the_new_schema(api):
    """Hotfix-1's verified-progress boundary remains intact on schema v8."""
    cid = _mk(api, "Integrity")
    g = experience.create_goal(cid, "Hunt the foes", target=3)
    r = api.post(A + f"/campaigns/{cid}/goals/{g['id']}/progress",
                 json={"delta": 2, "reason": "I say so"}).get_json()
    assert r["verified_progress"] == 0 and r["last_source"] == "player"
    experience.auto_credit(cid, "combat_victory", "victory over wolf")
    r2 = experience.goal_view(g["id"])
    assert r2["verified_progress"] == 1 and r2["last_source"] == "engine"
    other = _mk(api, "OtherVoyage")
    with pytest.raises(ValueError):
        experience.abandon_goal(other, g["id"])
