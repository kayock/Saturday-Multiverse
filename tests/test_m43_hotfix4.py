"""v0.4.0 Final Release Hotfix 4 — campfire authorization and verified
character knowledge.

Each test targets a confirmed hotfix-4 defect:
- `GET /campaigns/<cid>/campfire/shareable` caught ANY exception from
  `_mp_resolve()` as "solo", so a missing/invalid/revoked multiplayer token
  fell back to the campaign's main character and another player's shareable
  discoveries and memories leaked to an unauthenticated caller;
- shareability was decided by a hearing SCOPE (`kind='heard', ref='tavern'`),
  so a character could share tavern rumors created long after they left —
  a hearing scope is evidence of a past interaction, not proof that the
  character knows every present and future memory in that scope. Knowledge
  is now recorded per specific memory at authoritative delivery points
  (NPC conversations, arrival records, delivered visitor tales, party
  sharing) and both the picker and the sharing engine enforce it.
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


def _mk(api, name, pack="dracula", archetype="occultist", specialty="bind"):
    if pack == "living_shore":
        archetype, specialty = "sensitive", "bind"
    r = api.post(A + "/campaigns", json={"name": f"Voyage {name}", "pack_id": pack,
        "character": {"name": name, "archetype": archetype, "specialty": specialty}})
    body = r.get_json()
    assert r.status_code == 200, body
    return body["campaign_id"]


def _party(api, names=("Aldous", "Brigit", "Corvin"), pack="dracula"):
    """One campaign; first name hosts, the rest join as players."""
    cid = _mk(api, names[0], pack=pack)
    guest_spec = ({"archetype": "doctor", "specialty": "lore"} if pack == "dracula"
                  else {"archetype": "sensitive", "specialty": "bind"})
    host = api.post(A + "/mp/host", json={"campaign_id": cid,
                                          "display_name": names[0]}).get_json()
    ht = {"X-MP-Token": host["token"]}
    api.post(A + "/mp/start", json={"campaign_id": cid}, headers=ht)
    inv = api.post(A + "/mp/invite", json={"campaign_id": cid, "uses": 9},
                   headers=ht).get_json()
    players = [{"id": host["player_id"], "token": host["token"], "name": names[0]}]
    for name in names[1:]:
        res = api.post(A + "/mp/join", json={"campaign_id": cid, "invite_token": inv["token"],
            "display_name": name, "character": {"name": name, **guest_spec}}).get_json()
        assert res.get("token"), res
        players.append({"id": res["player_id"], "token": res["token"], "name": name})
    return cid, players


def _token(t):
    return {"X-MP-Token": t} if t else {}


def _player_rows(cid, players):
    out = {}
    for p in players:
        row = db.query_one("SELECT * FROM mp_players WHERE campaign_id=? AND id=?",
                           (cid, p["id"]))
        out[p["id"]] = dict(row)
    return out


def _picker(api, cid, players, name):
    p = next(p for p in players if p["name"] == name)
    return api.get(A + f"/campaigns/{cid}/campfire/shareable",
                   headers=_token(p["token"]))


def _memory_id(cid, snippet):
    row = db.query_one("SELECT id FROM npc_memories WHERE campaign_id=? AND text LIKE ?"
                       " ORDER BY rowid DESC LIMIT 1", (cid, f"%{snippet}%"))
    assert row, snippet
    return row["id"]


def _party_shared(cid):
    return db.query("SELECT kind, ref FROM char_knowledge WHERE campaign_id=?"
                    " AND character_id='*party*' AND kind='shared'", (cid,))


def _acquired(cid, character_id):
    return {r["ref"] for r in db.query(
        "SELECT ref FROM char_knowledge WHERE campaign_id=? AND character_id=?"
        " AND kind='memory'", (cid, character_id))}


# =====================================================================
# Defect 1 — failed multiplayer authorization must never fall back to
# the campaign's main character on the shareable picker
# =====================================================================
def test_picker_host_token_returns_host_knowledge(api):
    cid, players = _party(api, ("PickHostA", "PickGuestB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = _picker(api, cid, players, "PickHostA")
    assert r.status_code == 200, r.get_json()
    refs = [p["ref"] for p in r.get_json()["places"]]
    assert "whitby_harbour" in refs


def test_picker_guest_token_returns_only_guest_knowledge(api):
    cid, players = _party(api, ("IsoHostA", "IsoGuestB"))
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    experience.note_visit(cid, chb, "demeter")
    rb = _picker(api, cid, players, "IsoGuestB")
    assert rb.status_code == 200
    refs_b = [p["ref"] for p in rb.get_json()["places"]]
    assert "demeter" in refs_b and "whitby_harbour" not in refs_b, \
        "the guest's picker shows the guest's own knowledge, not the host's"


def test_picker_without_token_is_refused(api):
    """Missing token on a multiplayer campaign: 403 — never the campaign
    character's shareable knowledge."""
    cid, players = _party(api, ("NoTokA", "NoTokB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable")
    assert r.status_code == 403, r.get_json()
    blob = json.dumps(r.get_json())
    assert "whitby" not in blob.lower(), "no character-owned knowledge in the refusal"


def test_picker_with_invalid_token_is_refused(api):
    cid, players = _party(api, ("BadTokA", "BadTokB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                headers=_token("forged-token-not-in-any-session"))
    assert r.status_code == 403, r.get_json()
    assert "Whitby Harbour" not in json.dumps(r.get_json())


def test_picker_with_revoked_token_is_refused(api):
    """A banned player's token must no longer open anyone's picker."""
    cid, players = _party(api, ("RevA", "RevB"))
    ht = _token(players[0]["token"])
    r = api.post(A + f"/mp/players/{cid}/remove",
                 json={"player_id": players[1]["id"], "ban": True}, headers=ht)
    assert r.status_code == 200, r.get_json()
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                headers=_token(players[1]["token"]))
    assert r.status_code == 403, r.get_json()
    assert "Whitby Harbour" not in json.dumps(r.get_json())


def test_picker_with_removed_player_token_is_refused(api):
    cid, players = _party(api, ("RemA", "RemB"))
    ht = _token(players[0]["token"])
    r = api.post(A + f"/mp/players/{cid}/remove",
                 json={"player_id": players[1]["id"]}, headers=ht)
    assert r.status_code == 200, r.get_json()
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                headers=_token(players[1]["token"]))
    assert r.status_code == 403, r.get_json()


def test_picker_with_wrong_campaign_token_is_refused(api):
    cid, players = _party(api, ("WrongA", "WrongB"))
    cid2, players2 = _party(api, ("OtherC", "OtherD"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                headers=_token(players2[0]["token"]))
    assert r.status_code == 403, r.get_json()
    assert "whitby" not in json.dumps(r.get_json()).lower()


def test_picker_spectator_receives_no_character_knowledge(api):
    cid, players = _party(api, ("SpecA4", "SpecB4"))
    ht = _token(players[0]["token"])
    inv = api.post(A + f"/campaigns/{cid}/mp/invite-spectator", json={}, headers=ht).get_json()
    spec = api.post(A + "/mp/join", json={"campaign_id": cid,
        "invite_token": inv["token"], "display_name": "Watcher4"}).get_json()
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_discovery(cid, cha, "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable", headers=_token(spec["token"]))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["places"] == [] and body["memories"] == [], \
        "spectators hold no shareable character knowledge"


def test_unauthorized_picker_cannot_fall_back_to_main_character(api):
    """The exact confirmed defect: with a missing token the old endpoint
    served the campaign's original character's knowledge."""
    cid, players = _party(api, ("FallA", "FallB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    experience.note_visit(cid, cha, "whitby_harbour")
    experience.note_discovery(cid, cha, "whitby_harbour")
    for headers in ({}, _token("junk"), _token(players2_token(api))):
        r = api.get(A + f"/campaigns/{cid}/campfire/shareable", headers=headers)
        assert r.status_code == 403, (headers, r.status_code, r.get_json())
        assert "Whitby Harbour" not in json.dumps(r.get_json())


def players2_token(api):
    cid2 = _mk(api, "Unrelated")
    host2 = api.post(A + "/mp/host", json={"campaign_id": cid2,
                                           "display_name": "Unrelated"}).get_json()
    return host2["token"]


def test_unauthorized_requests_produce_no_knowledge_mutations(api):
    cid, players = _party(api, ("MutA", "MutB"))
    before = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?",
                          (cid,))["n"]
    shares_before = db.query_one("SELECT COUNT(*) AS n FROM knowledge_shares")["n"]
    for headers in ({}, _token("forged")):
        api.get(A + f"/campaigns/{cid}/campfire/shareable", headers=headers)
        api.post(A + f"/campaigns/{cid}/campfire",
                 json={"kind": "story", "text": "sneaky", "share": ["whitby_harbour"]},
                 headers=headers)
    after = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?",
                         (cid,))["n"]
    shares_after = db.query_one("SELECT COUNT(*) AS n FROM knowledge_shares")["n"]
    assert after == before, "an unauthorized request must not write knowledge"
    assert shares_after == shares_before, "no ledger entries without authorization"


def test_campfire_post_without_token_is_refused(api):
    cid, players = _party(api, ("PostA", "PostB"))
    r = api.post(A + f"/campaigns/{cid}/campfire",
                 json={"kind": "story", "text": "no token tale"})
    assert r.status_code == 403, r.get_json()
    r2 = api.post(A + f"/campaigns/{cid}/campfire",
                  json={"kind": "story", "text": "forged tale"},
                  headers=_token("forged-token"))
    assert r2.status_code == 403, r2.get_json()


def test_solo_picker_still_works_without_tokens(api):
    """Solo voyages keep working with no multiplayer session at all — access
    is decided by the campaign's actual session state."""
    cid = _mk(api, "SoloPicker", pack="dracula")
    camp = db.query_one("SELECT character_id FROM campaigns WHERE id=?", (cid,))
    experience.note_discovery(cid, camp["character_id"], "whitby_harbour")
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable")
    assert r.status_code == 200, r.get_json()
    assert "whitby_harbour" in [p["ref"] for p in r.get_json()["places"]]
    # solo campfire posting and sharing keep working
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "record", "text": "Found it.",
                         "share": ["whitby_harbour"]})
    assert res.status_code == 200 and res.get_json()["share"]["shared"] == ["whitby_harbour"]


# =====================================================================
# Defect 2 — a hearing scope is not knowledge of every memory in it;
# sharing requires specific, authoritative acquisition
# =====================================================================
def _tavern_party(api, names=("TavA", "TavB")):
    """A living_shore party; the party stands at the tavern (Maren's home)."""
    cid, players = _party(api, names, pack="living_shore")
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    return cid, players


def _maren_rumor(cid, snippet, scope="tavern", kind="gossip"):
    legacy.remember(cid, scope, kind, snippet)
    return _memory_id(cid, snippet)


def test_talk_acquires_exactly_the_delivered_rumors(api):
    """A visits the tavern and hears Rumor 1 through a real conversation:
    the engine records THAT memory as learned."""
    cid, players = _party(api, ("TalkA", "TalkB"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    chb = rows[players[1]["id"]]["character_id"]
    rumor1 = _maren_rumor(cid, "The captain's log mentions a strange cargo.")
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    r = api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
                 headers=_token(players[0]["token"]))
    assert r.status_code == 200, r.get_json()
    assert rumor1 in _acquired(cid, cha), "the conversation delivered the rumor"
    assert rumor1 not in _acquired(cid, chb), "the other player heard nothing"
    picker = _picker(api, cid, players, "TalkA").get_json()
    assert any(m["ref"] == rumor1 for m in picker["memories"]), \
        "the heard rumor is selectable"


def test_future_rumor_is_not_shareable_after_leaving(api):
    """Example B: A leaves the tavern; a rumor created later is not theirs to
    know or share — the picker omits it and a forged share is refused."""
    cid, players = _party(api, ("FutA", "FutB"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    rumor1 = _maren_rumor(cid, "Rumor one: the pilot drinks with the tide.")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    # A leaves; a NEW rumor appears at the tavern
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "camp", "solo": True},
             headers=_token(players[0]["token"]))
    rumor2 = _maren_rumor(cid, "Rumor two: the safe behind the panel holds the chart.")
    assert rumor1 in _acquired(cid, cha) and rumor2 not in _acquired(cid, cha)
    picker = _picker(api, cid, players, "FutA").get_json()
    refs = [m["ref"] for m in picker["memories"]]
    assert rumor1 in refs and rumor2 not in refs, \
        "a hearing scope must not surface later rumors as shareable"
    # a malicious client submits Rumor 2's id directly — refused, no grant
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "Heard at the tavern…",
                         "share": [rumor2]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == [], res.get("share")
    assert any(r["ref"] == rumor2 for r in res["share"]["rejected"])
    assert _party_shared(cid) == [], "no knowledge leaked"


def test_return_visit_acquires_the_new_rumor(api):
    """Example C: A returns to the tavern and actually hears Rumor 2 — the
    engine records the acquisition and Rumor 2 becomes shareable."""
    cid, players = _party(api, ("RetA", "RetB"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "camp", "solo": True},
             headers=_token(players[0]["token"]))
    rumor2 = _maren_rumor(cid, "The whisper broker bought the harbor bell.")
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    r = api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
                 headers=_token(players[0]["token"]))
    assert r.status_code == 200
    assert rumor2 in _acquired(cid, cha), "the return visit delivered the new rumor"
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "Now I heard this one too.",
                         "share": [rumor2]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == [rumor2], res.get("share")


def test_party_share_grants_exactly_that_memory(api):
    """Example D: A shares Rumor 1 with B. B gains THAT memory — not the
    tavern hearing scope, and never access to Rumor 2."""
    cid, players = _party(api, ("ShareA4", "ShareB4"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    rumor1 = _maren_rumor(cid, "Shared one: the cargo manifest was rewritten.")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    rumor2 = _maren_rumor(cid, "Shared two: the bell rings itself on fog nights.")
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "Heard this…", "share": [rumor1]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == [rumor1]
    assert rumor1 in _acquired(cid, chb), "B learned the shared memory"
    assert rumor2 not in _acquired(cid, chb), "B did not gain the whole scope"
    picker_b = _picker(api, cid, players, "ShareB4").get_json()
    refs_b = [m["ref"] for m in picker_b["memories"]]
    assert rumor1 in refs_b and rumor2 not in refs_b
    # B can pass it on; B can NOT pass on what they never heard
    res_b = api.post(A + f"/campaigns/{cid}/campfire",
                     json={"kind": "memory", "text": "Passing it on…",
                           "share": [rumor1, rumor2]},
                     headers=_token(players[1]["token"])).get_json()
    assert res_b["share"]["shared"] == [rumor1], res_b.get("share")
    # recaps: Rumor 1 reaches B; Rumor 2 is not in B's world (A is standing
    # IN the tavern, so A hears live tavern talk — the hearing model; B,
    # who never heard Rumor 2 and cannot share it, sees nothing of it)
    rec_b = api.get(A + f"/campaigns/{cid}/recap",
                    headers=_token(players[1]["token"])).get_json()
    assert any("cargo manifest" in i["text"] for i in rec_b["items"]), \
        "the shared rumor appears in B's authorized recap"
    assert "bell rings itself" not in json.dumps(rec_b), \
        "the rumor B never received stays out of B's recap"


def test_gm_memory_never_shareable_even_with_direct_id(api):
    """Example E: GM-only information is refused even when a malicious client
    submits the exact memory id, and the picker never offers it."""
    cid, players = _party(api, ("GmA4", "GmB4"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    gm_mem = _maren_rumor(cid, "The ADMINISTRATOR KEY rests under the jetty.",
                          kind="gm")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    picker = _picker(api, cid, players, "GmA4").get_json()
    assert gm_mem not in [m["ref"] for m in picker["memories"]], \
        "GM-only memories are never offered as shareable"
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…", "share": [gm_mem]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == []
    assert any("GM-only" in r["reason"] or "never be shared" in r["reason"]
               for r in res["share"]["rejected"])
    assert _party_shared(cid) == []


def test_unacquired_memory_id_is_refused_without_a_scope(api):
    """A memory id submitted directly without any acquisition and without a
    hearing scope produces nothing (no picker entry, no grant)."""
    cid, players = _party(api, ("NoScopeA", "NoScopeB"))
    mid = _maren_rumor(cid, "Tavern whisper nobody heard: the ledger bleeds.")
    picker = _picker(api, cid, players, "NoScopeA").get_json()
    assert mid not in [m["ref"] for m in picker["memories"]]
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…", "share": [mid]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == []
    assert _party_shared(cid) == []


def test_other_character_acquisition_is_not_claimable(api):
    """A player cannot claim another character's learned memory: B never
    talked, so A's rumor id is refused for B (identity comes from the token,
    never from the client)."""
    cid, players = _party(api, ("ClaimA", "ClaimB"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    rumor1 = _maren_rumor(cid, "Only A stayed for the tale of the ninth wave.")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    assert rumor1 in _acquired(cid, cha)
    assert rumor1 not in _acquired(cid, chb)
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…", "share": [rumor1]},
                   headers=_token(players[1]["token"])).get_json()
    assert res["share"]["shared"] == [], res.get("share")


def test_cross_campaign_memory_id_is_refused(api):
    """A memory id from Campaign A cannot be shared in Campaign B."""
    cid_a, players_a = _party(api, ("XcgA", "XcgB"), pack="living_shore")
    cid_b, players_b = _party(api, ("XcgC", "XcgD"), pack="living_shore")
    api.post(A + f"/campaigns/{cid_a}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players_a[0]["token"]))
    rumor_a = _maren_rumor(cid_a, "Campaign A's private tavern whisper.")
    api.post(A + f"/campaigns/{cid_a}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players_a[0]["token"]))
    assert rumor_a in _acquired(cid_a, _player_rows(cid_a, players_a)[players_a[0]["id"]]["character_id"])
    res = api.post(A + f"/campaigns/{cid_b}/campfire",
                   json={"kind": "memory", "text": "…", "share": [rumor_a]},
                   headers=_token(players_b[0]["token"])).get_json()
    assert res["share"]["shared"] == [], res.get("share")
    assert db.query_one("SELECT COUNT(*) AS n FROM knowledge_shares WHERE campaign_id=?",
                        (cid_b,))["n"] == 0
    assert rumor_a not in _acquired(cid_b, _player_rows(cid_b, players_b)[players_b[0]["id"]]["character_id"])


def test_forged_memory_references_produce_no_state_change(api):
    cid, players = _party(api, ("ForgeA", "ForgeB"))
    before = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?",
                          (cid,))["n"]
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…",
                         "share": ["mem_forged123", "kn_forged", " ../../../etc", "all"]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == []
    after = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?",
                         (cid,))["n"]
    assert after == before, "forged references must not write knowledge"


def test_memory_share_retry_is_idempotent(api):
    cid, players = _party(api, ("RetryA4", "RetryB4"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    rumor1 = _maren_rumor(cid, "Retold around many fires: the ninth wave knock.")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    for _ in range(3):
        res = api.post(A + f"/campaigns/{cid}/campfire",
                       json={"kind": "memory", "text": "Again.", "share": [rumor1]},
                       headers=_token(players[0]["token"])).get_json()
        assert res["share"]["shared"] == [rumor1]
    assert len(_party_shared(cid)) == 1, "no duplicate party grants"
    assert db.query_one("SELECT COUNT(*) AS n FROM knowledge_shares WHERE campaign_id=?"
                        " AND ref=?", (cid, rumor1))["n"] == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?"
                        " AND character_id=? AND kind='memory' AND ref=?",
                        (cid, chb, rumor1))["n"] == 1, "no duplicate acquisition rows"
    assert rumor1 in _acquired(cid, chb)
    led = db.query_one("SELECT * FROM knowledge_shares WHERE campaign_id=? AND ref=?",
                       (cid, rumor1))
    assert led["ref_kind"] == "memory" and led["shared_by_player_id"] == players[0]["id"]


def test_acquired_knowledge_survives_restart(api):
    """Acquisition rows and shares live in SQLite: a fresh read over the same
    data directory keeps them (and the picker agrees)."""
    cid, players = _party(api, ("PersA4", "PersB4"), pack="living_shore")
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True},
             headers=_token(players[0]["token"]))
    rumor1 = _maren_rumor(cid, "Durable: the tide table was stolen.")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=_token(players[0]["token"]))
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "memory", "text": "Listen…", "share": [rumor1]},
             headers=_token(players[0]["token"]))
    # 'restart': rows are re-read from disk (no in-memory cache exists)
    row = db.query_one("SELECT ts FROM knowledge_shares WHERE campaign_id=? AND ref=?",
                       (cid, rumor1))
    assert row and row["ts"]
    assert rumor1 in _acquired(cid, cha) and rumor1 in _acquired(cid, chb)
    picker_b = _picker(api, cid, players, "PersB4").get_json()
    assert rumor1 in [m["ref"] for m in picker_b["memories"]]


def test_arrival_memory_is_acquired_at_the_engine_points(api):
    """Campaign creation records the starting character's own arrival tale as
    learned knowledge; a joining character likewise learns theirs."""
    cid, players = _party(api, ("ArrA", "ArrB"), pack="dracula")
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    arrival_a = db.query_one(
        "SELECT id FROM npc_memories WHERE campaign_id=? AND text LIKE '%arrived on the shore%'"
        " ORDER BY rowid ASC LIMIT 1", (cid,))["id"]
    assert arrival_a in _acquired(cid, cha), "the creator learned their arrival tale"
    # B's join creates B's own arrival memory, learned by B only
    arrivals_b = [r["ref"] for r in db.query(
        "SELECT ref FROM char_knowledge WHERE campaign_id=? AND character_id=?"
        " AND kind='memory'", (cid, chb))]
    assert arrivals_b, "the joining character learned their own arrival tale"
    assert all(r != arrival_a for r in arrivals_b), "B did not inherit A's tale"


# =====================================================================
# End-to-end acceptance scenario (assignment §7) — real API + database
# =====================================================================
def test_e2e_acceptance_scenario(api):
    """Two independent characters A and B, the full twelve-step flow from the
    review, against the actual application API and database."""
    cid, players = _party(api, ("E2EA", "E2EB"), pack="living_shore")
    tok_a, tok_b = _token(players[0]["token"]), _token(players[1]["token"])
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]

    # 1-2. A visits the tavern and legitimately hears Rumor 1
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True}, headers=tok_a)
    rumor1 = _maren_rumor(cid, "Rumor 1: the strange cargo came ashore at night.")
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "cargo"},
             headers=tok_a)
    assert rumor1 in _acquired(cid, cha)
    # 3-4. A leaves; Rumor 2 is created
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "camp", "solo": True}, headers=tok_a)
    rumor2 = _maren_rumor(cid, "Rumor 2: the pilot's ledger holds a second key.")
    # 5. A's picker includes Rumor 1 but not Rumor 2
    picker_a = _picker(api, cid, players, "E2EA").get_json()
    refs_a = [m["ref"] for m in picker_a["memories"]]
    assert rumor1 in refs_a and rumor2 not in refs_a
    # 6-7. A shares Rumor 1; B learns Rumor 1, not Rumor 2
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "At the tavern…", "share": [rumor1]},
                   headers=tok_a).get_json()
    assert res["share"]["shared"] == [rumor1]
    assert rumor1 in _acquired(cid, chb) and rumor2 not in _acquired(cid, chb)
    # 8. an unauthenticated client requests A's picker and receives 403
    r = api.get(A + f"/campaigns/{cid}/campfire/shareable")
    assert r.status_code == 403
    # 9-10. A returns, legitimately hears Rumor 2, which becomes shareable
    api.post(A + f"/campaigns/{cid}/travel",
             json={"location_id": "tavern", "solo": True}, headers=tok_a)
    api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": "maren", "topic": "ledger"},
             headers=tok_a)
    assert rumor2 in _acquired(cid, cha)
    picker_a_r2 = _picker(api, cid, players, "E2EA").get_json()
    assert rumor2 in [m["ref"] for m in picker_a_r2["memories"]], \
        "the newly learned rumor is now individually shareable"
    # 11-12. both players disconnect and reconnect; knowledge persists
    db.execute("UPDATE mp_players SET status='offline' WHERE campaign_id=?", (cid,))
    mp.auth(cid, players[0]["token"])
    mp.auth(cid, players[1]["token"])
    picker_a2 = _picker(api, cid, players, "E2EA").get_json()
    picker_b2 = _picker(api, cid, players, "E2EB").get_json()
    refs_a2 = [m["ref"] for m in picker_a2["memories"]]
    refs_b2 = [m["ref"] for m in picker_b2["memories"]]
    assert rumor1 in refs_a2 and rumor2 in refs_a2, "A keeps what they learned"
    assert rumor1 in refs_b2 and rumor2 not in refs_b2, \
        "B keeps exactly what was shared with them (and nothing more)"
    rec_b = api.get(A + f"/campaigns/{cid}/recap", headers=tok_b).get_json()
    assert any("strange cargo" in i["text"] for i in rec_b["items"]), \
        "shared knowledge still appears in authorized recaps after reconnect"
    assert "second key" not in json.dumps(rec_b), \
        "what B never received stays out of B's recap"
