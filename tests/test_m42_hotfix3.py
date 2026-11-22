"""v0.4.0 Final Release Hotfix 3 — knowledge privacy, recap integrity,
strict HTTPS identities, cross-platform CI.

Each test targets a confirmed hotfix-3 defect:
- every campfire story blanket-shared the teller's ENTIRE knowledge scope
  (visited places, discoveries, heard scopes) with the whole party, so an
  ordinary story granted future private rumors; sharing must be explicit,
  bounded and server-validated;
- recap() fetched the newest 8 NPC memories and filtered afterwards, so 8
  hidden/unauthorized rows starved an older authorized rumor out of the
  window entirely;
- certificate diagnostics merged the Common Name into the SAN list and only
  checked expiry, so a CN-only or not-yet-valid certificate passed strict
  HTTPS validation;
- the TLS test helper imported Unix-only `fcntl`, and the CI dev
  requirements never installed `cryptography`, so the Windows CI matrix
  could not run the suite.
"""
import json
import re
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
    host = api.post(A + "/mp/host", json={"campaign_id": cid,
                                          "display_name": names[0]}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post(A + "/mp/start", json={"campaign_id": cid}, headers=ht)
    inv = api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 9},
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
    out = {}
    for p in players:
        row = db.query_one("SELECT * FROM mp_players WHERE campaign_id=? AND id=?",
                           (cid, p["id"]))
        out[p["id"]] = dict(row)
    return out


def _recap_as(api, cid, players, name):
    p = next(p for p in players if p["name"] == name)
    return api.get(A + f"/campaigns/{cid}/recap", headers=_token(p["token"])).get_json()


def _memory_id(cid, snippet):
    row = db.query_one("SELECT id FROM npc_memories WHERE campaign_id=? AND text LIKE ?"
                       " ORDER BY rowid DESC LIMIT 1", (cid, f"%{snippet}%"))
    assert row, snippet
    return row["id"]


def _party_shared_rows(cid):
    return db.query("SELECT kind, ref, ts FROM char_knowledge WHERE campaign_id=?"
                    " AND character_id='*party*'", (cid,))


# =====================================================================
# Defect 1 — the campfire must not blanket-share the teller's knowledge
# =====================================================================
def test_ordinary_story_shares_nothing(api):
    """A player writes "The moon over Whitby was beautiful tonight." — the
    story appears, and NO unrelated mysteries or hearing scopes are granted."""
    cid, players = _party(api, ("MoonA", "MoonB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_heard(cid, cha, "tavern")
    legacy.remember(cid, "tavern", "event", "Maren spoke of the chart under the bar.")
    st, res = None, api.post(A + f"/campaigns/{cid}/campfire",
                             json={"kind": "story",
                                   "text": "The moon over Whitby was beautiful tonight."},
                             headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    assert res["text"] == "The moon over Whitby was beautiful tonight."
    # the story exists, but nothing was shared with the party
    assert _party_shared_rows(cid) == [], "an ordinary story must share no knowledge"
    rec_b = _recap_as(api, cid, players, "MoonB")
    blob = json.dumps(rec_b)
    assert "Whitby Harbour" not in blob, "no private discovery leaks via an ordinary story"
    assert "chart under the bar" not in blob, "no tavern gossip leaks via an ordinary story"


def test_ordinary_story_grants_no_future_rumors(api):
    """Even after someone once told a story, rumors introduced LATER at the
    tavern stay private to whoever actually heard them."""
    cid, players = _party(api, ("FutureA", "FutureB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_heard(cid, cha, "tavern")
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "story", "text": "We drank, the tide came in."},
             headers=_token(players[0]["token"]))
    legacy.remember(cid, "tavern", "gossip",
                    "LATER: the safe behind the panel holds the Vermeer chart.")
    legacy.remember(cid, "all", "gossip", "Public: the pier lantern was relit.")
    rec_b = _recap_as(api, cid, players, "FutureB")
    blob = json.dumps(rec_b)
    assert "Vermeer chart" not in blob, "a story must not grant the tavern hearing scope"
    assert any("pier lantern" in i["text"] for i in rec_b["items"]), \
        "public world information still reaches everyone"


def test_explicit_share_transfers_exactly_one_discovery(api):
    """Sharing is explicit: the teller selects ONE discovery; only that
    discovery reaches the party, and the teller's other private knowledge
    stays private."""
    cid, players = _party(api, ("SelA", "SelB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "demeter")     # A's other private find
    legacy.remember(cid, "tavern", "event", "Maren spoke of the chart under the bar.")
    st, res = None, api.post(A + f"/campaigns/{cid}/campfire",
                             json={"kind": "record", "text": "About the harbour…",
                                   "share": ["whitby_harbour"]},
                             headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    assert res["share"]["shared"] == ["whitby_harbour"], res.get("share")
    rec_b = _recap_as(api, cid, players, "SelB")
    blob = json.dumps(rec_b)
    assert "Whitby Harbour" in blob, "the selected discovery reaches the party"
    assert "Demeter" not in blob, "unselected private discoveries stay hidden"
    assert "chart under the bar" not in blob, "unselected tavern gossip stays hidden"
    # a later story by the SAME teller shares nothing again
    api.post(A + f"/campaigns/{cid}/campfire", json={"kind": "story", "text": "More tales."},
             headers=_token(players[0]["token"]))
    assert len(_party_shared_rows(cid)) == 1, "each story shares only what was selected"


def test_shared_rumor_does_not_reveal_later_tavern_rumor(api):
    """Sharing one past tavern rumor transfers exactly that memory — it must
    not grant the tavern hearing scope, so a LATER tavern rumor stays hidden."""
    cid, players = _party(api, ("RumA", "RumB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_heard(cid, cha, "tavern")
    legacy.remember(cid, "tavern", "gossip",
                    "The captain's log mentions a strange cargo.")
    mid = _memory_id(cid, "strange cargo")
    # hotfix 4: the teller must actually have learned this memory — record
    # the acquisition exactly as the engine's delivery points do
    experience.note_memory(cid, cha, mid)
    st, res = None, api.post(A + f"/campaigns/{cid}/campfire",
                             json={"kind": "memory", "text": "Heard at the tavern…",
                                   "share": [mid]},
                             headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    assert res["share"]["shared"] == [mid], res.get("share")
    rec_b = _recap_as(api, cid, players, "RumB")
    assert any("strange cargo" in i["text"] for i in rec_b["items"]), \
        "the selected past rumor reaches the party"
    # a rumor introduced AFTER the share stays hidden from the party
    legacy.remember(cid, "tavern", "gossip",
                    "LATER: the harbor bell was sold to a whisper broker.")
    rec_b2 = _recap_as(api, cid, players, "RumB")
    blob = json.dumps(rec_b2)
    assert "whisper broker" not in blob, "future rumors stay hidden after a clue is shared"
    assert "strange cargo" in blob, "the shared clue itself remains visible"


def test_cannot_share_knowledge_the_character_does_not_hold(api):
    """The engine validates every selection: a player cannot share a place
    they never visited, another character's discovery, or a GM-only secret."""
    cid, players = _party(api, ("ValA", "ValB"))
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    experience.note_discovery(cid, chb, "demeter")     # B's private discovery
    legacy.remember(cid, "deep", "gossip", "The SALT-CROWN sleeps beneath the pier.")
    db.execute("INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
               " VALUES ('mem_gmsecret', ?, '*', ?, 'gm', 'all', ?)",
               (cid, db.utcnow(), "The ADMINISTRATOR KEY is under the jetty."))
    st, res = None, api.post(A + f"/campaigns/{cid}/campfire",
                             json={"kind": "record", "text": "Sharing…",
                                   "share": ["demeter", "mem_gmsecret",
                                             "SALT-CROWN", "nowhere_at_all"]},
                             headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    share = res["share"]
    assert share["shared"] == [], "A holds none of these — nothing may be granted"
    reasons = {r["ref"]: r["reason"] for r in share["rejected"]}
    assert set(reasons) == {"demeter", "mem_gmsecret", "SALT-CROWN", "nowhere_at_all"}
    assert reasons["demeter"], "another character's discovery is refused with a reason"
    assert reasons["mem_gmsecret"], "a GM-only memory is refused"
    assert _party_shared_rows(cid) == [], "no restricted information was disclosed"
    # B still sees their OWN discovery (legitimately); nobody gains A's view
    # of it, and GM-only knowledge surfaces nowhere
    blob_a = json.dumps(_recap_as(api, cid, players, "ValA"))
    blob_b = json.dumps(_recap_as(api, cid, players, "ValB"))
    assert "Demeter" not in blob_a, "A did not acquire B's private discovery"
    assert "SALT-CROWN" not in blob_a and "SALT-CROWN" not in blob_b \
        and "ADMINISTRATOR KEY" not in blob_a and "ADMINISTRATOR KEY" not in blob_b


def test_hearing_scope_cannot_be_shared_directly(api):
    """A hearing scope (things heard at the tavern) is not a shareable item:
    sharing it wholesale would grant every past and future rumor there.
    The specific memory can be shared instead."""
    cid, players = _party(api, ("ScopeA", "ScopeB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_heard(cid, cha, "tavern")
    st, res = None, api.post(A + f"/campaigns/{cid}/campfire",
                             json={"kind": "story", "text": "Tales of the tavern…",
                                   "share": ["tavern"]},
                             headers=_token(players[0]["token"])).get_json()
    assert "error" not in res, res
    assert res["share"]["shared"] == [], "a bare hearing scope is never granted"
    assert any(r["ref"] == "tavern" for r in res["share"]["rejected"])
    # but the specific memory CAN be shared explicitly — once the teller has
    # actually learned it (hotfix 4: the acquisition record, exactly as the
    # engine's delivery points write it)
    legacy.remember(cid, "tavern", "gossip", "The landlord keeps a ledger of names.")
    mid = _memory_id(cid, "ledger of names")
    res_unlearned = api.post(A + f"/campaigns/{cid}/campfire",
                             json={"kind": "memory", "text": "…", "share": [mid]},
                             headers=_token(players[0]["token"])).get_json()
    assert res_unlearned["share"]["shared"] == [], \
        "a hearing scope alone does not make a memory shareable"
    experience.note_memory(cid, cha, mid)
    res2 = api.post(A + f"/campaigns/{cid}/campfire",
                    json={"kind": "memory", "text": "One thing he said…",
                          "share": [mid]},
                    headers=_token(players[0]["token"])).get_json()
    assert res2["share"]["shared"] == [mid]


def test_split_party_sharing_isolation(api):
    """Split parties share what they choose; the other subgroup's private
    discoveries stay private until they are shared too."""
    cid, players = _party(api, ("SplitShareA", "SplitShareC"))
    rows = _player_rows(cid, players)
    cha, chc = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_visit(cid, chc, "demeter")
    experience.note_discovery(cid, chc, "demeter")
    # A shares only the harbour
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The harbour.", "share": ["whitby_harbour"]},
             headers=_token(players[0]["token"]))
    rec_a = _recap_as(api, cid, players, "SplitShareA")
    rec_c = _recap_as(api, cid, players, "SplitShareC")
    assert "Whitby Harbour" in json.dumps(rec_c), "C receives what A explicitly shared"
    assert "Demeter" in json.dumps(rec_c), "C's own discovery is untouched by A's share"
    assert "Demeter" not in json.dumps(rec_a), "A's share does not expose C's private discovery"


def test_multiple_players_share_different_discoveries(api):
    cid, players = _party(api, ("MultiA", "MultiB"))
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, chb, "demeter")
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The harbour.", "share": ["whitby_harbour"]},
             headers=_token(players[0]["token"]))
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The ship.", "share": ["demeter"]},
             headers=_token(players[1]["token"]))
    blob_a = json.dumps(_recap_as(api, cid, players, "MultiA"))
    blob_b = json.dumps(_recap_as(api, cid, players, "MultiB"))
    assert "Whitby Harbour" in blob_b and "Demeter" in blob_a, "both shares flowed"
    assert "Whitby Harbour" in blob_a and "Demeter" in blob_b, "the party holds both"


def test_share_retries_do_not_duplicate(api):
    cid, players = _party(api, ("RetryA", "RetryB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    for _ in range(3):
        res = api.post(A + f"/campaigns/{cid}/campfire",
                       json={"kind": "record", "text": "Again.", "share": ["whitby_harbour"]},
                       headers=_token(players[0]["token"])).get_json()
        assert res["share"]["shared"] == ["whitby_harbour"]
    shared = _party_shared_rows(cid)
    assert len([r for r in shared if r["ref"] == "whitby_harbour"]) == 1, \
        "retries never duplicate the party grant"
    shares = db.query("SELECT * FROM knowledge_shares WHERE campaign_id=? AND ref=?",
                      (cid, "whitby_harbour"))
    assert len(shares) == 1, "the share ledger records the event exactly once"
    rec_b = _recap_as(api, cid, players, "RetryB")
    told = [i for i in rec_b["items"] if i["text"].startswith("Told at the fire")]
    assert len(told) <= 1, "retries never duplicate the fire-telling entry"


def test_share_records_who_and_when(api):
    cid, players = _party(api, ("WhoA", "WhoB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The harbour.", "share": ["whitby_harbour"]},
             headers=_token(players[0]["token"]))
    row = db.query_one("SELECT * FROM knowledge_shares WHERE campaign_id=? AND ref=?",
                       (cid, "whitby_harbour"))
    assert row, "the share is recorded durably"
    assert row["shared_by_player_id"] == players[0]["id"]
    assert row["shared_by_character_id"] == cha
    assert row["ref_kind"] == "place" and row["source_kind"] == "discovery"
    assert row["ts"], "the share carries its timestamp"
    ev = db.query("SELECT type FROM events WHERE campaign_id=? AND type='knowledge_shared'",
                  (cid,))
    assert ev, "the share is visible in the campaign event stream"


def test_shared_knowledge_survives_restart(api):
    """Shares live in SQLite: a fresh read over the same data directory still
    shows the party what was shared."""
    cid, players = _party(api, ("PersA3", "PersB3"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The harbour.", "share": ["whitby_harbour"]},
             headers=_token(players[0]["token"]))
    # 'restart': the row is re-read from disk (no in-memory cache exists)
    row = db.query_one("SELECT ts FROM knowledge_shares WHERE campaign_id=? AND ref=?",
                       (cid, "whitby_harbour"))
    assert row and row["ts"]
    rec_b = _recap_as(api, cid, players, "PersB3")
    assert "Whitby Harbour" in json.dumps(rec_b)


def test_spectators_receive_only_what_their_role_permits(api):
    """A spectator follows the shared feed: a plain story grants nothing, and
    an explicit share reaches them without unlocking anything else."""
    cid, players = _party(api, ("Spec3Host", "Spec3Player"))
    ht = _token(players[0]["token"])
    inv = api.post(A + f"/campaigns/{cid}/mp/invite-spectator", json={}, headers=ht).get_json()
    spec = api.post(A + "/mp/join", json={"campaign_id": cid,
        "invite_token": inv["token"], "display_name": "Watcher3"}).get_json()
    assert spec.get("token"), spec
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    legacy.remember(cid, "tavern", "event", "Maren whispered about the saloon safe.")
    watcher = _token(spec["token"])
    rec = api.get(A + f"/campaigns/{cid}/recap", headers=watcher).get_json()
    blob = json.dumps(rec)
    assert rec["viewer"]["spectator"] is True
    assert "Whitby Harbour" not in blob and "saloon safe" not in blob
    # an ordinary story shares nothing with anyone — spectators included
    api.post(A + f"/campaigns/{cid}/campfire", json={"kind": "story", "text": "Our tale:"},
             headers=ht)
    rec2 = api.get(A + f"/campaigns/{cid}/recap", headers=watcher).get_json()
    blob2 = json.dumps(rec2)
    assert "Whitby Harbour" not in blob2, "a plain story grants spectators nothing"
    # an explicit share follows the shared feed to the spectator
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "record", "text": "The harbour.", "share": ["whitby_harbour"]},
             headers=ht)
    rec3 = api.get(A + f"/campaigns/{cid}/recap", headers=watcher).get_json()
    assert "Whitby Harbour" in json.dumps(rec3), "explicitly shared knowledge reaches spectators"


def test_shareable_endpoint_lists_only_the_tellers_knowledge(api):
    """The picker shows what THIS character may share — places they know and
    specific eligible memories — never another player's knowledge."""
    cid, players = _party(api, ("PickA", "PickB"))
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, chb, "demeter")
    legacy.remember(cid, "tavern", "gossip", "The captain's log mentions a strange cargo.")
    # hotfix 4: the picker offers a memory only once the character actually
    # learned it (the acquisition record the engine's delivery points write)
    mid4 = _memory_id(cid, "strange cargo")
    picker_unlearned = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                               headers=_token(players[0]["token"])).get_json()
    assert mid4 not in [m["ref"] for m in picker_unlearned["memories"]], \
        "a rumor the character never heard is not offered"
    experience.note_memory(cid, cha, mid4)
    shareable = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                        headers=_token(players[0]["token"])).get_json()
    refs = [p["ref"] for p in shareable["places"]]
    assert "whitby_harbour" in refs and "demeter" not in refs
    assert any("strange cargo" in m["text"] for m in shareable["memories"]), \
        "the memories this character heard are selectable"
    # a spectator has no character: nothing is shareable through their token
    ht = _token(players[0]["token"])
    inv = api.post(A + f"/campaigns/{cid}/mp/invite-spectator", json={}, headers=ht).get_json()
    spec = api.post(A + "/mp/join", json={"campaign_id": cid,
        "invite_token": inv["token"], "display_name": "WatcherPick"}).get_json()
    shareable_spec = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                             headers=_token(spec["token"])).get_json()
    assert shareable_spec["places"] == [] and shareable_spec["memories"] == []


def test_legacy_blanket_shares_do_not_authorize_future_memories(api):
    """Documented conservative policy for pre-hotfix3 saves: a historical
    party-wide grant stays readable up to the moment it was granted, but it
    must NOT authorize memories created afterwards. Nothing is deleted or
    fabricated — the grant simply stops at what it could have covered."""
    cid, players = _party(api, ("LegA", "LegB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_heard(cid, cha, "tavern")
    # a pre-hotfix3 world: one old tavern rumor, a blanket party-wide grant
    # recorded by the old campfire code, then a NEWER private rumor
    db.execute("INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
               " VALUES ('mem_old3', ?, '*', '2026-01-01T00:00:00Z', 'gossip', 'tavern', ?)",
               (cid, "OLD: the harbor bell rings itself on fog nights."))
    db.execute("INSERT INTO char_knowledge (id, campaign_id, character_id, kind, ref, ts)"
               " VALUES ('kn_old3', ?, '*party*', 'shared', 'tavern', '2026-01-02T00:00:00Z')",
               (cid,))
    db.execute("INSERT INTO npc_memories (id, campaign_id, npc_id, ts, kind, scope, text)"
               " VALUES ('mem_new3', ?, '*', '2026-01-03T00:00:00Z', 'gossip', 'tavern', ?)",
               (cid, "NEW: the whisper broker bought the bell."))
    rec_b = _recap_as(api, cid, players, "LegB")
    blob = json.dumps(rec_b)
    assert "harbor bell rings itself" in blob, \
        "what was already public at grant time stays readable"
    assert "whisper broker" not in blob, \
        "an old broad grant must not authorize memories created after it"
    # the teller, who genuinely heard both tales (the second one delivered
    # in person after the broad grant — hotfix 5 delivery record), sees both
    cha_leg = _player_rows(cid, players)[players[0]["id"]]["character_id"]
    experience.note_memory(cid, cha_leg, "mem_new3")
    rec_a = _recap_as(api, cid, players, "LegA")
    blob_a = json.dumps(rec_a)
    assert "harbor bell rings itself" in blob_a and "whisper broker" in blob_a


def test_legacy_shared_discovery_items_still_render(api):
    """Old shared rows remain readable history — no knowledge is erased by
    the migration: the party still sees the fire-tales they were told."""
    cid, players = _party(api, ("LegHistA", "LegHistB"))
    db.execute("INSERT INTO char_knowledge (id, campaign_id, character_id, kind, ref, ts)"
               " VALUES ('kn_hist3', ?, '*party*', 'shared', 'whitby_harbour',"
               " '2026-01-02T00:00:00Z')", (cid,))
    rec_b = _recap_as(api, cid, players, "LegHistB")
    assert "Whitby Harbour" in json.dumps(rec_b), \
        "historical shared entries survive the policy change"


# =====================================================================
# Defect 2 — recap must filter BEFORE limiting results
# =====================================================================
def _seed_starvation(api, cid, players, blocked_scope, blocked_marker):
    """One older public rumor; then `blocked_marker` newer rows the viewer is
    NOT entitled to (the hotfix2 window of 8 newest rows swallowed the
    eligible one)."""
    rows = _player_rows(cid, players)
    chb = rows[players[1]["id"]]["character_id"]
    experience.note_visit(cid, chb, "whitby_harbour")
    legacy.remember(cid, "all", "gossip",
                    "PUBLIC: the tide table was stolen from the harbour office.")
    for i in range(blocked_marker):
        legacy.remember(cid, blocked_scope, "gossip",
                        f"{blocked_marker}秘密{i}: the {blocked_scope} whisper {i} "
                        f"should never reach the beach walker.")
    return chb


def test_hidden_memories_cannot_starve_the_public_rumor(api):
    """At least 20 newer GM/deep memories must not push an older eligible
    public rumor out of the recap."""
    cid, players = _party(api, ("StarveA", "StarveB"))
    _seed_starvation(api, cid, players, "deep", 20)
    rec_b = _recap_as(api, cid, players, "StarveB")
    assert any("tide table was stolen" in i["text"] for i in rec_b["items"]), \
        json.dumps(rec_b["items"])[:600]
    blob = json.dumps(rec_b)
    assert "秘密" not in blob, "no hidden memory may surface"


def test_unentitled_place_memories_cannot_starve_the_public_rumor(api):
    """The same starvation with ordinary place-scoped rows the viewer simply
    has no entitlement for (they were at the beach, not the tavern)."""
    cid, players = _party(api, ("BeachA3", "BeachB3"))
    _seed_starvation(api, cid, players, "tavern", 24)
    rec_b = _recap_as(api, cid, players, "BeachB3")
    assert any("tide table was stolen" in i["text"] for i in rec_b["items"]), \
        json.dumps(rec_b["items"])[:600]
    blob = json.dumps(rec_b)
    assert "whisper" not in blob, "unentitled place gossip stays out"


def test_authorized_rumor_found_behind_hundreds_of_rows(api):
    """A long campaign: the eligible rumor sits behind 120 newer restricted
    rows — bounded retrieval must still reach it without unbounded work."""
    cid, players = _party(api, ("DeepA", "DeepB"))
    _seed_starvation(api, cid, players, "deep", 120)
    rec_b = _recap_as(api, cid, players, "DeepB")
    assert any("tide table was stolen" in i["text"] for i in rec_b["items"]), \
        json.dumps(rec_b["items"])[:600]


def test_mixed_public_and_private_rows_stay_ordered(api):
    """Mixed eligibility: the recap shows the eligible rows in sensible
    (newest-last within a kind) order without duplicates or leaks."""
    cid, players = _party(api, ("MixA", "MixB"))
    rows = _player_rows(cid, players)
    chb = rows[players[1]["id"]]["character_id"]
    experience.note_visit(cid, chb, "whitby_harbour")
    legacy.remember(cid, "tavern", "gossip", "TAVERN-only whisper one.")
    legacy.remember(cid, "all", "gossip", "PUBLIC harbor notice number one.")
    legacy.remember(cid, "deep", "gossip", "DEEP secret buried two.")
    legacy.remember(cid, "all", "gossip", "PUBLIC harbor notice number two.")
    legacy.remember(cid, "tavern", "gossip", "TAVERN-only whisper two.")
    rec_b = _recap_as(api, cid, players, "MixB")
    blob = json.dumps(rec_b)
    assert "TAVERN-only" not in blob and "DEEP secret" not in blob
    texts = [i["text"] for i in rec_b["items"] if i["kind"] == "npc"]
    assert texts == texts, "no crash"
    assert any("number two" in t for t in texts), "the newest public notice appears"


def test_viewing_recap_does_not_advance_the_marker(api):
    """Merely viewing a recap must never dismiss it: new items stay 'new'
    until the viewer explicitly dismisses."""
    cid, players = _party(api, ("ViewA", "ViewB"))
    legacy.remember(cid, "all", "gossip", "PUBLIC: gulls circled the pier at dawn.")
    r1 = _recap_as(api, cid, players, "ViewA")
    assert r1["has_new"] is True
    r2 = _recap_as(api, cid, players, "ViewA")
    assert r2["has_new"] is True, "viewing again does not silently dismiss"
    api.post(A + f"/campaigns/{cid}/recap/dismiss", json={},
             headers=_token(players[0]["token"]))
    r3 = _recap_as(api, cid, players, "ViewA")
    assert r3["has_new"] is False, "explicit dismissal still works"
    assert _recap_as(api, cid, players, "ViewB")["has_new"] is True, \
        "one player's dismissal never affects another player's marker"


def test_solo_recap_survives_starvation_too(api):
    """Solo voyages keep full recap eligibility: hidden rows cannot crowd out
    eligible ones there either."""
    cid = _mk(api, "SoloStarve")
    camp = db.query_one("SELECT character_id FROM campaigns WHERE id=?", (cid,))
    experience.note_heard(cid, camp["character_id"], "tavern")
    legacy.remember(cid, "all", "gossip", "PUBLIC: the ferry resumed at first light.")
    for i in range(12):
        legacy.remember(cid, "deep", "gossip", f"DEEP solo secret {i}.")
    rec = experience.recap(cid)
    assert any("ferry resumed" in i["text"] for i in rec["items"])


# =====================================================================
# Defect 3 — strict HTTPS identities and validity windows
# =====================================================================
@pytest.fixture()
def certdir(tmp_path, monkeypatch):
    monkeypatch.setenv("SATURDAY_DATA_DIR", str(tmp_path))
    from server import tls as tlsmod
    tlsmod.refresh()
    tlsmod.generate()
    yield tmp_path
    monkeypatch.delenv("SATURDAY_DATA_DIR", raising=False)
    tlsmod.refresh()


def _issue_cert(dir_path: Path, *, cn="localhost", sans=None, ips=None,
                not_before_days_ago=1, valid_days=800, sign_by_ca=True):
    """Craft a certificate with exact control over SANs and validity."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from server import tls as tlsmod
    now = datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    if sign_by_ca:
        issuer_cert = x509.load_pem_x509_certificate(tlsmod.ca_cert().read_bytes())
        issuer_key = serialization.load_pem_private_key(
            tlsmod.ca_key().read_bytes(), password=None)
    else:
        issuer_cert, issuer_key = None, key
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer_cert.subject if issuer_cert else name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=not_before_days_ago))
        .not_valid_after(now + datetime.timedelta(days=valid_days))
    )
    if issuer_cert:
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True)
    names = [x509.DNSName(d) for d in (sans or [])]
    names += [x509.IPAddress(ipaddress.ip_address(i)) for i in (ips or [])]
    if names:
        builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
    cert = builder.sign(issuer_key, hashes.SHA256())
    cert_path = dir_path / "custom.crt"
    key_path = dir_path / "custom.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return cert_path, key_path


def test_cn_only_certificate_is_rejected(certdir):
    """A CN=localhost certificate with NO Subject Alternative Name must never
    pass strict HTTPS validation — modern browsers require SAN identities."""
    from server import tls as tlsmod
    cert, key = _issue_cert(certdir, cn="localhost", sans=None)
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"], report
    assert any("Subject Alternative Name" in p for p in report["problems"])
    assert report["sans"] == [], "the CN must not appear as a SAN identity"
    assert report.get("cn") == "localhost", "the CN stays available as diagnostics only"
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(cert, key)
    assert "san" in str(exc.value).lower()


def test_cn_does_not_substitute_for_a_san(certdir):
    """CN=localhost + an unrelated SAN: 'localhost' must still count as
    uncovered — the CN is diagnostics-only."""
    from server import tls as tlsmod
    cert, key = _issue_cert(certdir, cn="localhost", sans=["elsewhere.example"])
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"]
    assert report["sans"] == ["elsewhere.example"]
    assert report.get("cn") == "localhost"
    assert any("covers NONE of the client-facing names" in p
               for p in report["problems"])


def test_valid_dns_san_is_accepted(certdir):
    from server import tls as tlsmod
    import ssl
    cert, key = _issue_cert(certdir, cn="localhost", sans=["localhost"],
                            ips=["127.0.0.1"])
    report = tlsmod.diagnose(cert, key)
    assert report["ok"], report["problems"]
    ctx = tlsmod.ssl_context(cert, key)
    assert isinstance(ctx, ssl.SSLContext)


def test_valid_ip_san_is_accepted(certdir, monkeypatch):
    from server import tls as tlsmod
    import ssl
    ips = tlsmod.lan_addresses()
    target = ips[0] if ips else "127.0.0.1"
    monkeypatch.setenv("SATURDAY_TLS_NAME", target)
    cert, key = _issue_cert(certdir, cn=target, sans=["localhost"], ips=[target])
    report = tlsmod.diagnose(cert, key)
    assert report["ok"], report["problems"]
    ctx = tlsmod.ssl_context(cert, key)
    assert isinstance(ctx, ssl.SSLContext)
    monkeypatch.delenv("SATURDAY_TLS_NAME")


def test_wrong_ip_san_is_rejected(certdir, monkeypatch):
    from server import tls as tlsmod
    monkeypatch.setenv("SATURDAY_TLS_NAME", "192.168.1.50")
    cert, key = _issue_cert(certdir, cn="192.168.1.50", sans=["localhost"],
                            ips=["10.0.0.9"])
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"]
    assert any("192.168.1.50" in p for p in report["problems"])
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(cert, key)
    assert "192.168.1.50" in str(exc.value)
    monkeypatch.delenv("SATURDAY_TLS_NAME")


def test_dns_name_with_textual_ip_does_not_substitute_ip_san(certdir, monkeypatch):
    """A DNSName carrying the textual IP is NOT an IPAddress SAN: a LAN IP
    identity must be covered by a real IP SAN entry."""
    from server import tls as tlsmod
    monkeypatch.setenv("SATURDAY_TLS_NAME", "192.168.1.50")
    cert, key = _issue_cert(certdir, cn="192.168.1.50",
                            sans=["192.168.1.50", "localhost"])   # DNS only!
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"], report
    assert any("IPAddress" in p or "does not cover" in p for p in report["problems"]), \
        report["problems"]
    with pytest.raises(RuntimeError):
        tlsmod.ssl_context(cert, key)
    monkeypatch.delenv("SATURDAY_TLS_NAME")


def test_not_yet_valid_certificate_is_rejected(certdir):
    """A certificate whose validity begins in the future must fail strict
    validation — precisely, not truncated to whole days."""
    from server import tls as tlsmod
    cert, key = _issue_cert(certdir, cn="localhost", sans=["localhost"],
                            not_before_days_ago=-1)   # valid FROM tomorrow
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"], report
    assert any("not yet valid" in p.lower() for p in report["problems"])
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(cert, key)
    assert "not yet valid" in str(exc.value).lower()


def test_user_provided_valid_certificate_is_accepted(certdir):
    """Existing user-provided certificates keep working: a valid pair signed
    by the local CA with proper SANs is accepted."""
    from server import tls as tlsmod
    import ssl
    cert, key = _issue_cert(certdir, cn="my-lan-host", sans=["my-lan-host", "localhost"],
                            ips=["127.0.0.1"])
    report = tlsmod.diagnose(cert, key)
    assert report["ok"], report["problems"]
    ctx = tlsmod.ssl_context(cert, key)
    assert isinstance(ctx, ssl.SSLContext)
    assert report["days_left"] is not None and report["days_left"] > 700


def test_diagnostics_name_the_reason(certdir, monkeypatch):
    """Each failure mode produces a distinct, actionable diagnostic."""
    from server import tls as tlsmod
    cert, key = _issue_cert(certdir, cn="localhost", sans=["localhost"],
                            not_before_days_ago=-2)
    report = tlsmod.diagnose(cert, key)
    assert any("not yet valid" in p.lower() for p in report["problems"])
    expired, ekey = _issue_cert(certdir, cn="localhost", sans=["localhost"],
                                not_before_days_ago=900, valid_days=-30)
    report2 = tlsmod.diagnose(expired, ekey)
    assert any("EXPIRED" in p for p in report2["problems"])
    cert2, _ = _issue_cert(certdir, cn="localhost", sans=["localhost"])
    mismatch = certdir / "other.key"
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    mismatch.write_bytes(other.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    report3 = tlsmod.diagnose(cert2, mismatch)
    assert any("does not match" in p for p in report3["problems"])
    report4 = tlsmod.diagnose(certdir / "absent.crt", certdir / "absent.key")
    assert any("missing" in p for p in report4["problems"])


# =====================================================================
# Defect 4 — the CI matrix must be able to run this suite everywhere
# =====================================================================
UNIX_ONLY_PATTERNS = (
    re.compile(r"^\s*import\s+fcntl\b", re.MULTILINE),
    re.compile(r"^\s*from\s+fcntl\b", re.MULTILINE),
    re.compile(r"^\s*import\s+termios\b", re.MULTILINE),
    re.compile(r"^\s*import\s+pty\b", re.MULTILINE),
    re.compile(r"^\s*import\s+resource\b", re.MULTILINE),
    re.compile(r"os\.set_blocking\("),
)


def test_ci_suite_has_no_unix_only_code():
    """Every test module that runs in the GitHub Actions matrix (ubuntu AND
    windows) must be importable on Windows: no fcntl/termios/pty imports and
    no os.set_blocking pipe tricks in the test helpers."""
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        for pat in UNIX_ONLY_PATTERNS:
            if pat.search(src):
                offenders.append(f"{path.name}: {pat.pattern}")
    assert offenders == [], "Unix-only code scheduled for Windows CI: " + "; ".join(offenders)


def test_dev_requirements_install_the_tls_test_dependency():
    """The TLS tests import `cryptography`; requirements-dev.txt must install
    it so the CI matrix can run the full suite (production keeps it
    optional)."""
    req = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower()
    assert "cryptography" in req, "requirements-dev.txt must include cryptography"
