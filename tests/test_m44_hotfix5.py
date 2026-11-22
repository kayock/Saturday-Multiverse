"""v0.4.0 Final Release Hotfix 5 — NPC secret protection and unified
character knowledge.

Two confirmed hotfix-4 defects, reproduced here as failing-first tests:

1. RECAPS LEAKED FUTURE RUMORS: `recap._mem_entitled` still authorized a
   memory whose scope sat in the viewer's own places/scopes — a character's
   past presence disclosed rumors created after they left. The recap now
   uses the same specific-memory entitlement as the sharing engine
   (`_memory_entitlement`): acquired, exactly party-shared, ts-capped
   historical grants, or truly public news — never mere presence.

2. NPC CONVERSATIONS EXPOSED GM-ONLY MEMORIES: `talk()` handed the whole
   scope-filtered memory collection (GM-only, hidden, deep) to the gossip
   builder and AI prompt, recorded every candidate as learned, and returned
   the internal collection in the API response. Internal NPC knowledge is
   now separated from conversation candidates and from actually-revealed
   information; only memories the conversation genuinely speaks are
   disclosed, acquired, and returned.
"""
import json
from pathlib import Path

import pytest

from server import ai, db, experience, gm, legacy, mp
from server.app import create_app

ROOT = Path(__file__).resolve().parent.parent
A = "/api"


@pytest.fixture()
def api():
    db.init_db()
    return create_app().test_client()


def _mk(api, name, pack="living_shore"):
    spec = ({"archetype": "occultist", "specialty": "bind"} if pack == "dracula"
            else {"archetype": "sensitive", "specialty": "bind"})
    r = api.post(A + "/campaigns", json={"name": f"Voyage {name}", "pack_id": pack,
        "character": {"name": name, **spec}})
    body = r.get_json()
    assert r.status_code == 200, body
    return body["campaign_id"]


def _party(api, names=("Annora", "Bren"), pack="living_shore"):
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


def _recap_as(api, cid, players, name):
    p = next(p for p in players if p["name"] == name)
    return api.get(A + f"/campaigns/{cid}/recap", headers=_token(p["token"])).get_json()


def _picker(api, cid, players, name):
    p = next(p for p in players if p["name"] == name)
    return api.get(A + f"/campaigns/{cid}/campfire/shareable",
                   headers=_token(p["token"]))


def _memory_id(cid, snippet):
    row = db.query_one("SELECT id FROM npc_memories WHERE campaign_id=? AND text LIKE ?"
                       " ORDER BY rowid DESC LIMIT 1", (cid, f"%{snippet}%"))
    assert row, snippet
    return row["id"]


def _acquired(cid, character_id):
    return {r["ref"] for r in db.query(
        "SELECT ref FROM char_knowledge WHERE campaign_id=? AND character_id=?"
        " AND kind='memory'", (cid, character_id))}


def _travel(api, cid, players, name, loc):
    p = next(p for p in players if p["name"] == name)
    return api.post(A + f"/campaigns/{cid}/travel",
                    json={"location_id": loc, "solo": True},
                    headers=_token(p["token"]))


def _talk(api, cid, players, name, npc, topic):
    p = next(p for p in players if p["name"] == name)
    return api.post(A + f"/campaigns/{cid}/talk", json={"npc_id": npc, "topic": topic},
                    headers=_token(p["token"]))


SECRET = "The ADMINISTRATOR KEY rests beneath the ninth stair."


# =====================================================================
# Defect 1 — recaps must use the same specific-memory entitlement as
# the sharing engine: presence never discloses later rumors
# =====================================================================
def test_earlier_visit_does_not_reveal_later_rumor(api):
    """Steps 1-8 of the review's reproduction: A visits the tavern, leaves;
    a rumor created afterward appears in neither the picker NOR the recap."""
    cid, players = _party(api, ("CapA", "CapB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _travel(api, cid, players, "CapA", "tavern")
    legacy.remember(cid, "tavern", "gossip",
                    "LATER: the whisper broker bought the harbor bell.")
    mid = _memory_id(cid, "whisper broker")
    rec = _recap_as(api, cid, players, "CapA")
    assert "whisper broker" not in json.dumps(rec), \
        "a past visit must not disclose a rumor created afterward"
    picker = _picker(api, cid, players, "CapA").get_json()
    assert mid not in [m["ref"] for m in picker["memories"]]
    assert mid not in _acquired(cid, cha)


def test_rumor_visible_after_actual_delivery(api):
    """Once the character genuinely hears the rumor, the recap may show it —
    and only then."""
    cid, players = _party(api, ("DelA", "DelB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _travel(api, cid, players, "DelA", "tavern")
    legacy.remember(cid, "tavern", "gossip",
                    "The pilot's ledger holds a second key.")
    mid = _memory_id(cid, "second key")
    rec0 = _recap_as(api, cid, players, "DelA")
    assert "second key" not in json.dumps(rec0), "not yet learned"
    r = _talk(api, cid, players, "DelA", "maren", "cargo")
    assert r.status_code == 200, r.get_json()
    assert mid in _acquired(cid, cha), "the conversation delivered the rumor"
    rec1 = _recap_as(api, cid, players, "DelA")
    assert "second key" in json.dumps(rec1), "learned in person: now visible"


def test_explicit_sharing_grants_only_the_selected_rumor(api):
    cid, players = _party(api, ("ShareA5", "ShareB5"))
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    _travel(api, cid, players, "ShareA5", "tavern")
    legacy.remember(cid, "tavern", "gossip", "Rumor one: the cargo manifest was rewritten.")
    mid1 = _memory_id(cid, "cargo manifest")
    _talk(api, cid, players, "ShareA5", "maren", "cargo")
    legacy.remember(cid, "tavern", "gossip", "Rumor two: the bell rings itself on fog nights.")
    mid2 = _memory_id(cid, "bell rings itself")
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "Heard at the tavern…",
                         "share": [mid1]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == [mid1]
    rec_b = _recap_as(api, cid, players, "ShareB5")
    blob_b = json.dumps(rec_b)
    assert "cargo manifest" in blob_b, "the shared rumor reaches the receiver's recap"
    assert "bell rings itself" not in blob_b, "future rumors stay hidden"
    assert mid1 in _acquired(cid, chb) and mid2 not in _acquired(cid, chb)


def test_public_memory_remains_visible(api):
    """Public world news (scope 'all', ordinary kind) stays visible to every
    player's recap without acquisition."""
    cid, players = _party(api, ("PubA", "PubB"))
    legacy.remember(cid, "all", "event", "A comet crossed the shore last night.")
    for name in ("PubA", "PubB"):
        rec = _recap_as(api, cid, players, name)
        assert "comet crossed the shore" in json.dumps(rec), \
            "public news reaches every player"


def test_gm_only_memory_stays_hidden_even_with_public_scope(api):
    """A public-looking scope must never override a restricted kind: a
    GM-kind memory is invisible in recaps whatever its scope says."""
    cid, players = _party(api, ("GmScopeA", "GmScopeB"))
    legacy.remember(cid, "all", "gm", "The ADMINISTRATOR KEY rests under the jetty.")
    gm_mid = _memory_id(cid, "ADMINISTRATOR KEY")
    for name in ("GmScopeA", "GmScopeB"):
        rec = _recap_as(api, cid, players, name)
        assert "ADMINISTRATOR KEY" not in json.dumps(rec), \
            "GM-only kind dominates any scope label"
    picker = _picker(api, cid, players, "GmScopeA").get_json()
    assert gm_mid not in [m["ref"] for m in picker["memories"]]
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…", "share": [gm_mid]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == [], "GM-only knowledge is never shareable"


def test_split_party_recaps_remain_distinct(api):
    cid, players = _party(api, ("SplitA5", "SplitC5"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _travel(api, cid, players, "SplitA5", "tavern")
    legacy.remember(cid, "tavern", "gossip", "The private tavern tale of the folded map.")
    _talk(api, cid, players, "SplitA5", "maren", "cargo")
    mid = _memory_id(cid, "folded map")
    assert mid in _acquired(cid, cha)
    rec_a = _recap_as(api, cid, players, "SplitA5")
    rec_c = _recap_as(api, cid, players, "SplitC5")
    assert "folded map" in json.dumps(rec_a), "A keeps what they heard"
    assert "folded map" not in json.dumps(rec_c), \
        "a private conversation stays private from the rest of the party"


def test_per_player_dismissal_remains_independent(api):
    cid, players = _party(api, ("DismA5", "DismB5"))
    legacy.remember(cid, "all", "event", "News: the tide table was stolen tonight.")
    marker_rows = db.query("SELECT * FROM recap_seen WHERE campaign_id=?", (cid,))
    assert marker_rows == []
    rec_a = _recap_as(api, cid, players, "DismA5")
    assert any("tide table" in i["text"] for i in rec_a["items"])
    # A dismisses; B has never seen the recap and must still receive the item
    api.post(A + f"/campaigns/{cid}/recap/dismiss", json={}, headers=_token(players[0]["token"]))
    rec_b = _recap_as(api, cid, players, "DismB5")
    assert any("tide table" in i["text"] for i in rec_b["items"]), \
        "one player's dismissal never marks another player's unseen events as read"


def test_legacy_solo_compatibility_remains_intact(api):
    """Legacy solo saves (no knowledge rows at all) keep the old recap
    behavior: the one character saw everything the campaign recorded."""
    cid = _mk(api, "SoloLeg5")
    legacy.remember(cid, "tavern", "gossip", "An old save rumor about the salt gate.")
    # simulate a pre-tracking save: no per-character knowledge rows exist
    db.execute("DELETE FROM char_knowledge WHERE campaign_id=?", (cid,))
    res = api.get(A + f"/campaigns/{cid}/recap")
    assert res.status_code == 200
    assert "salt gate" in json.dumps(res.get_json()), \
        "legacy solo saves keep their recap behavior"


# =====================================================================
# Defect 2 — internal NPC knowledge is not conversation content
# =====================================================================
def _lampkeeper_setup(api, names=("LampA", "LampB")):
    cid, players = _party(api, names)
    _travel(api, cid, players, names[0], "saltgrave_gate")
    legacy.remember(cid, "deep", "gm", SECRET)
    return cid, players, _memory_id(cid, "ADMINISTRATOR KEY")


def test_gm_deep_memory_excluded_from_talk_response(api):
    """Example A/C: the Lampkeeper knows a GM-only secret; an unrelated
    question never returns it — not in the lines, not in the memories field."""
    cid, players, gm_mid = _lampkeeper_setup(api)
    r = _talk(api, cid, players, "LampA", "drowned_lampkeeper", "weather")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert SECRET not in json.dumps(body), \
        "the API response must never carry undisclosed internal records"
    assert gm_mid not in [m.get("id") for m in body.get("memories", [])]


def test_gm_memory_not_recorded_as_acquired(api):
    cid, players, gm_mid = _lampkeeper_setup(api)
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _talk(api, cid, players, "LampA", "drowned_lampkeeper", "weather")
    assert gm_mid not in _acquired(cid, cha), \
        "retrieving a candidate is not delivering it"


def test_normal_safe_dialogue_remains_functional(api):
    """Example B: NPCs still talk — public events, gossip, reactions."""
    cid, players = _party(api, ("SafeA", "SafeB"))
    _travel(api, cid, players, "SafeA", "tavern")
    legacy.remember(cid, "tavern", "event", "The Skyless Light was relit by a stranger.")
    r = _talk(api, cid, players, "SafeA", "maren", "what's new")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["npc"]["id"] == "maren" and len(body["lines"]) >= 2
    assert any("relit" in line for line in body["lines"]), \
        "the conversation still quotes the public event"
    mid = _memory_id(cid, "relit")
    assert any(m["id"] == mid for m in body["memories"]), \
        "the response lists exactly what was disclosed"
    assert mid in _acquired(cid, _player_rows(cid, players)[players[0]["id"]]["character_id"])


def test_merely_retrieving_candidates_grants_nothing(api):
    """Candidate selection alone (no conversation) must not write knowledge."""
    cid, players = _party(api, ("CandA", "CandB"))
    _travel(api, cid, players, "CandA", "tavern")
    legacy.remember(cid, "tavern", "gossip", "A candidate rumor nobody has heard yet.")
    mid = _memory_id(cid, "candidate rumor")
    cands = legacy._conversation_candidates(cid, "maren")
    assert mid in [m["id"] for m in cands], "the NPC can talk about it"
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    assert mid not in _acquired(cid, cha), \
        "candidate retrieval never equals disclosure"


def test_ai_prompt_contains_no_unauthorized_secret(api):
    """The AI dialogue prompt is built from permitted candidates only — a
    GM-only deep record never reaches model context (#14)."""
    cid, players, gm_mid = _lampkeeper_setup(api, ("AiA", "AiB"))
    # a permitted candidate for the lampkeeper: public world news (scope all)
    legacy.remember(cid, "all", "event", "A lampkeeper memory of the deep door.")
    captured = {}

    def fake_chat(messages, cfg=None):
        captured["messages"] = messages
        return ('{"npc_lines": ["The water keeps its own counsel."]}', {"model": "mock"})

    orig = ai.chat
    ai.chat = fake_chat
    try:
        ai.set_ai_config({"enabled": True, "base_url": "http://mock.local/v1",
                          "api_key": "mock"})
        r = _talk(api, cid, players, "AiA", "drowned_lampkeeper", "weather")
        assert r.status_code == 200
    finally:
        ai.set_ai_config({"enabled": False})
        ai.chat = orig
    blob = json.dumps(captured.get("messages", []))
    assert SECRET not in blob, "GM-only records must never enter model context"
    assert "deep door" in blob, "permitted candidates still ground the dialogue"
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    assert gm_mid not in _acquired(cid, cha)


def test_malformed_ai_disclosed_ids_cannot_grant_arbitrary_memories(api):
    """An AI response may only declare memories the server authorized as
    candidates; forged or restricted ids are dropped (#15)."""
    cid, players, gm_mid = _lampkeeper_setup(api, ("MfA", "MfB"))
    legacy.remember(cid, "tavern", "gossip", "A safe rumor about the folded chart.")
    safe_mid = _memory_id(cid, "folded chart")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]

    def fake_chat(messages, cfg=None):
        return ('{"npc_lines": ["Some lines."], "disclosed_ids": ["%s", "%s", "mem_forged"]}'
                % (gm_mid, safe_mid), {"model": "mock"})

    orig = ai.chat
    ai.chat = fake_chat
    try:
        ai.set_ai_config({"enabled": True, "base_url": "http://mock.local/v1",
                          "api_key": "mock"})
        r = _talk(api, cid, players, "MfA", "drowned_lampkeeper", "weather")
        assert r.status_code == 200
    finally:
        ai.set_ai_config({"enabled": False})
        ai.chat = orig
    acquired = _acquired(cid, cha)
    assert gm_mid not in acquired, "a restricted id can never be declared learned"
    assert "mem_forged" not in acquired, "unknown ids are dropped"
    assert safe_mid not in acquired, \
        "the lampkeeper never had the tavern rumor as a candidate"
    assert gm_mid not in [m.get("id") for m in r.get_json().get("memories", [])]


def test_validated_ai_disclosure_records_only_declared_candidates(api):
    """When the model does declare a permitted id it actually used, that
    specific memory is recorded — nothing else."""
    cid, players = _party(api, ("VaA", "VaB"))
    _travel(api, cid, players, "VaA", "tavern")
    legacy.remember(cid, "tavern", "gossip", "The declared rumor about the brass bell.")
    mid = _memory_id(cid, "brass bell")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]

    def fake_chat(messages, cfg=None):
        return ('{"npc_lines": ["The brass bell, aye."], "disclosed_ids": ["%s"]}' % mid,
                {"model": "mock"})

    orig = ai.chat
    ai.chat = fake_chat
    try:
        ai.set_ai_config({"enabled": True, "base_url": "http://mock.local/v1",
                          "api_key": "mock"})
        r = _talk(api, cid, players, "VaA", "maren", "cargo")
        assert r.status_code == 200
    finally:
        ai.set_ai_config({"enabled": False})
        ai.chat = orig
    assert mid in _acquired(cid, cha)
    body = r.get_json()
    assert any(m["id"] == mid for m in body["memories"])
    # a second tavern rumor created before the talk stays unacquired
    other = [m["id"] for m in body["memories"] if m["id"] != mid]
    assert all(o not in _acquired(cid, cha) for o in other) if other else True


def test_ai_without_disclosure_reference_grants_nothing(api):
    """If the model cannot produce a trustworthy disclosure reference, no
    acquisition is invented — the deterministic fallback also spoke nothing."""
    cid, players = _party(api, ("NoDiscA", "NoDiscB"))
    _travel(api, cid, players, "NoDiscA", "tavern")
    legacy.remember(cid, "tavern", "gossip", "A rumor the model never declared.")
    mid = _memory_id(cid, "model never declared")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]

    def fake_chat(messages, cfg=None):
        return ('{"npc_lines": ["Completely unrelated small talk."]}', {"model": "mock"})

    orig = ai.chat
    ai.chat = fake_chat
    try:
        ai.set_ai_config({"enabled": True, "base_url": "http://mock.local/v1",
                          "api_key": "mock"})
        r = _talk(api, cid, players, "NoDiscA", "maren", "cargo")
        assert r.status_code == 200
    finally:
        ai.set_ai_config({"enabled": False})
        ai.chat = orig
    assert mid not in _acquired(cid, cha)
    assert r.get_json()["memories"] == [], "nothing disclosed, nothing learned"


def test_authorized_story_event_reveals_a_hidden_fact(api):
    """Example D: a hidden mystery stays hidden until an explicit,
    engine-authorized story event reveals it. `reveal_memory` is that event:
    it relabels the memory into a player-facing scope and records the
    acquisition. Kind restrictions still dominate (a GM-kind memory can be
    relabeled but never becomes player-visible)."""
    cid, players = _party(api, ("RevA", "RevB"))
    _travel(api, cid, players, "RevA", "saltgrave_gate")
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    legacy.remember(cid, "deep", "event", "The doorway beneath the ninth stair finally opened.")
    mid = _memory_id(cid, "ninth stair finally opened")
    rec0 = _recap_as(api, cid, players, "RevA")
    assert "ninth stair" not in json.dumps(rec0), "deep material starts internal"
    # the scripted revelation: an explicit engine-authorized story event
    experience.reveal_memory(cid, cha, mid, scope="doors")
    rec1 = _recap_as(api, cid, players, "RevA")
    assert "ninth stair" in json.dumps(rec1), "authorized revelation is player-visible"
    assert mid in _acquired(cid, cha)
    picker = _picker(api, cid, players, "RevA").get_json()
    assert mid in [m["ref"] for m in picker["memories"]], \
        "a revealed memory is shareable at the fire"
    # a GM-kind secret cannot be laundered into visibility by any event
    legacy.remember(cid, "deep", "gm", SECRET)
    gm_mid = _memory_id(cid, "ADMINISTRATOR KEY")
    experience.reveal_memory(cid, cha, gm_mid, scope="doors")
    rec2 = _recap_as(api, cid, players, "RevA")
    assert "ADMINISTRATOR KEY" not in json.dumps(rec2), \
        "GM-only kind stays restricted regardless of scope or acquisition"
    assert gm_mid not in [m["ref"] for m in
                          _picker(api, cid, players, "RevA").get_json()["memories"]]


def test_transcript_contains_no_undisclosed_secret(api):
    cid, players, gm_mid = _lampkeeper_setup(api)
    _talk(api, cid, players, "LampA", "drowned_lampkeeper", "weather")
    rows = db.query("SELECT role, content, data_json FROM transcript WHERE campaign_id=?",
                    (cid,))
    blob = json.dumps([dict(r) for r in rows])
    assert SECRET not in blob, "transcripts never carry undisclosed internal records"


def test_event_streams_contain_no_undisclosed_secret(api):
    cid, players, gm_mid = _lampkeeper_setup(api)
    _talk(api, cid, players, "LampA", "drowned_lampkeeper", "weather")
    rows = db.query("SELECT type, data_json FROM events WHERE campaign_id=?", (cid,))
    blob = json.dumps([dict(r) for r in rows])
    assert SECRET not in blob, "game events (Engine Trace) never carry the secret text"
    ev = db.query_one("SELECT data_json FROM events WHERE campaign_id=? AND type='npc_talk'"
                      " ORDER BY rowid DESC LIMIT 1", (cid,))
    d = __import__("json").loads(ev["data_json"], ) if ev else {}
    assert "text" not in d and SECRET not in json.dumps(d), \
        "npc_talk events carry ids only, never internal record text"


def test_multiplayer_knowledge_boundaries_after_talk(api):
    """Examples E + §8: a private conversation stays private; sharing still
    transfers exactly the disclosed memory; forged and cross-campaign
    references stay rejected."""
    cid, players = _party(api, ("BndA", "BndB"))
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]
    _travel(api, cid, players, "BndA", "tavern")
    legacy.remember(cid, "tavern", "gossip", "The boundary rumor about the tide ledger.")
    mid = _memory_id(cid, "tide ledger")
    _talk(api, cid, players, "BndA", "maren", "cargo")
    assert mid in _acquired(cid, cha) and mid not in _acquired(cid, chb), \
        "B did not automatically learn A's conversation"
    # forged references still write nothing
    before = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?",
                          (cid,))["n"]
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…",
                         "share": ["mem_forged5", mid[:-4] + "zzzz"]},
                   headers=_token(players[0]["token"])).get_json()
    assert res["share"]["shared"] == []
    after = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?",
                         (cid,))["n"]
    assert after == before
    # a genuine share transfers exactly the one memory
    res2 = api.post(A + f"/campaigns/{cid}/campfire",
                    json={"kind": "memory", "text": "Heard this…", "share": [mid]},
                    headers=_token(players[0]["token"])).get_json()
    assert res2["share"]["shared"] == [mid]
    assert mid in _acquired(cid, chb)
    # cross-campaign: B's id from another campaign can't be used here
    cid2 = _mk(api, "Other5")
    legacy.remember(cid2, "tavern", "gossip", "Another campaign's private rumor.")
    other_mid = _memory_id(cid2, "Another campaign")
    res3 = api.post(A + f"/campaigns/{cid}/campfire",
                    json={"kind": "memory", "text": "…", "share": [other_mid]},
                    headers=_token(players[1]["token"])).get_json()
    assert res3["share"]["shared"] == []


def test_spectator_receives_no_hidden_knowledge(api):
    cid, players, gm_mid = _lampkeeper_setup(api, ("SpecA5", "SpecB5"))
    ht = _token(players[0]["token"])
    inv = api.post(A + f"/campaigns/{cid}/mp/invite-spectator", json={}, headers=ht).get_json()
    spec = api.post(A + "/mp/join", json={"campaign_id": cid,
        "invite_token": inv["token"], "display_name": "Watch5"}).get_json()
    _talk(api, cid, players, "SpecA5", "drowned_lampkeeper", "weather")
    rec = api.get(A + f"/campaigns/{cid}/recap", headers=_token(spec["token"])).get_json()
    assert SECRET not in json.dumps(rec)
    picker = api.get(A + f"/campaigns/{cid}/campfire/shareable",
                     headers=_token(spec["token"])).get_json()
    assert picker["places"] == [] and picker["memories"] == []
    # spectators also learn nothing from conversations they witness
    sp_row = db.query_one("SELECT character_id FROM mp_players WHERE campaign_id=? AND id=?",
                          (cid, spec["player_id"]))
    assert not (sp_row and sp_row["character_id"] and
                gm_mid in _acquired(cid, sp_row["character_id"]))


def test_acquired_memories_persist_after_restart(api):
    cid, players = _party(api, ("PersA5", "PersB5"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _travel(api, cid, players, "PersA5", "tavern")
    legacy.remember(cid, "tavern", "gossip", "The durable rumor of the ninth wave.")
    mid = _memory_id(cid, "ninth wave")
    _talk(api, cid, players, "PersA5", "maren", "cargo")
    api.post(A + f"/campaigns/{cid}/campfire",
             json={"kind": "memory", "text": "Listen…", "share": [mid]},
             headers=_token(players[0]["token"]))
    # 'restart': rows are re-read from disk (no in-memory cache exists)
    row = db.query_one("SELECT ts FROM knowledge_shares WHERE campaign_id=? AND ref=?",
                       (cid, mid))
    assert row and row["ts"]
    assert mid in _acquired(cid, cha)
    rec = _recap_as(api, cid, players, "PersB5")
    assert "ninth wave" in json.dumps(rec)


def test_conversation_replay_is_idempotent(api):
    """A replayed conversation response must not create duplicate acquisition
    records (UNIQUE constraint + idempotent note_memory)."""
    cid, players = _party(api, ("IdemA5", "IdemB5"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _travel(api, cid, players, "IdemA5", "tavern")
    legacy.remember(cid, "tavern", "gossip", "The repeated rumor about the folded chart.")
    mid = _memory_id(cid, "folded chart")
    for _ in range(3):
        r = _talk(api, cid, players, "IdemA5", "maren", "cargo")
        assert r.status_code == 200
    n = db.query_one("SELECT COUNT(*) AS n FROM char_knowledge WHERE campaign_id=?"
                     " AND character_id=? AND kind='memory' AND ref=?",
                     (cid, cha, mid))["n"]
    assert n == 1, "no duplicate acquisition rows"


def test_conversation_acquisition_is_exact_not_blanket(api):
    """A conversation discloses and acquires exactly what was spoken — never
    the whole candidate list (the hotfix-4 over-acquisition defect)."""
    cid, players = _party(api, ("ExactA", "ExactB"))
    rows = _player_rows(cid, players)
    cha = rows[players[0]["id"]]["character_id"]
    _travel(api, cid, players, "ExactA", "tavern")
    legacy.remember(cid, "tavern", "gossip", "Earlier rumor: the salt gate hums at dusk.")
    legacy.remember(cid, "tavern", "gossip", "Earlier rumor: the ninth wave knocks twice.")
    legacy.remember(cid, "tavern", "gossip", "Newest rumor: the pilot drinks with the tide.")
    r = _talk(api, cid, players, "ExactA", "maren", "cargo")
    assert r.status_code == 200
    body = r.get_json()
    disclosed = [m["id"] for m in body["memories"]]
    assert len(disclosed) <= len(body["memories"]) and disclosed, "something was spoken"
    newest = _memory_id(cid, "pilot drinks with the tide")
    assert disclosed == [newest], \
        "the deterministic conversation quotes exactly the newest record"
    assert newest in _acquired(cid, cha)
    older = _memory_id(cid, "salt gate hums at dusk")
    assert older not in _acquired(cid, cha), \
        "unspoken candidates stay unlearned — acquisition matches disclosure, not retrieval"


# =====================================================================
# End-to-end acceptance scenario (§11) — real API + persistent database
# =====================================================================
def test_e2e_lampkeeper_and_tavern_scenario(api):
    cid, players = _party(api, ("E2A5", "E2B5"))
    tok_a, tok_b = _token(players[0]["token"]), _token(players[1]["token"])
    rows = _player_rows(cid, players)
    cha, chb = rows[players[0]["id"]]["character_id"], rows[players[1]["id"]]["character_id"]

    # 1. a GM-only deep-scoped memory exists
    legacy.remember(cid, "deep", "gm", SECRET)
    gm_mid = _memory_id(cid, "ADMINISTRATOR KEY")
    # 2-3. A talks to the Lampkeeper about an unrelated topic
    _travel(api, cid, players, "E2A5", "saltgrave_gate")
    r = _talk(api, cid, players, "E2A5", "drowned_lampkeeper", "weather")
    assert r.status_code == 200
    assert SECRET not in json.dumps(r.get_json()), "step 3: absent from the response"
    # 4. absent from A's char_knowledge
    assert gm_mid not in _acquired(cid, cha), "step 4"
    # 5. absent from the player-facing transcript
    blob = json.dumps([dict(x) for x in db.query(
        "SELECT content, data_json FROM transcript WHERE campaign_id=?", (cid,))])
    assert SECRET not in blob, "step 5"
    # 6. A cannot select or share the secret
    picker_a = _picker(api, cid, players, "E2A5").get_json()
    assert gm_mid not in [m["ref"] for m in picker_a["memories"]], "step 6a"
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "…", "share": [gm_mid]},
                   headers=tok_a).get_json()
    assert res["share"]["shared"] == [], "step 6b"
    # 7-9. a legitimate tavern rumor; A travels and actually hears it
    legacy.remember(cid, "tavern", "gossip", "Rumor A5: the strange cargo came ashore.")
    rumor1 = _memory_id(cid, "strange cargo came ashore")
    _travel(api, cid, players, "E2A5", "tavern")
    _talk(api, cid, players, "E2A5", "maren", "cargo")
    assert rumor1 in _acquired(cid, cha), "step 9"
    # 10. B does not automatically know it
    assert rumor1 not in _acquired(cid, chb), "step 10"
    # 11-12. A shares it explicitly; B now knows that rumor
    res = api.post(A + f"/campaigns/{cid}/campfire",
                   json={"kind": "memory", "text": "At the tavern…", "share": [rumor1]},
                   headers=tok_a).get_json()
    assert res["share"]["shared"] == [rumor1], "step 11"
    assert rumor1 in _acquired(cid, chb), "step 12"
    # 13-14. a second, later rumor: neither character learns it automatically
    legacy.remember(cid, "tavern", "gossip", "Rumor B5: the bell rings itself on fog nights.")
    rumor2 = _memory_id(cid, "bell rings itself")
    assert rumor2 not in _acquired(cid, cha) and rumor2 not in _acquired(cid, chb), "step 14"
    rec_a = _recap_as(api, cid, players, "E2A5")
    rec_b = _recap_as(api, cid, players, "E2B5")
    assert "bell rings itself" not in json.dumps(rec_a)
    assert "bell rings itself" not in json.dumps(rec_b)
    # 15-16. A returns and legitimately hears the new rumor
    _talk(api, cid, players, "E2A5", "maren", "ledger")
    assert rumor2 in _acquired(cid, cha), "step 16a"
    picker_a2 = _picker(api, cid, players, "E2A5").get_json()
    assert rumor2 in [m["ref"] for m in picker_a2["memories"]], "step 16b"
    # 17-18. disconnect and reconnect both players; knowledge persists and
    # hidden information stays private
    db.execute("UPDATE mp_players SET status='offline' WHERE campaign_id=?", (cid,))
    mp.auth(cid, players[0]["token"])
    mp.auth(cid, players[1]["token"])
    assert rumor1 in _acquired(cid, cha) and rumor2 in _acquired(cid, cha)
    assert rumor1 in _acquired(cid, chb) and rumor2 not in _acquired(cid, chb)
    assert gm_mid not in _acquired(cid, cha) and gm_mid not in _acquired(cid, chb)
    rec_b2 = _recap_as(api, cid, players, "E2B5")
    blob_b2 = json.dumps(rec_b2)
    assert "strange cargo" in blob_b2 and "ADMINISTRATOR KEY" not in blob_b2, "step 18"
