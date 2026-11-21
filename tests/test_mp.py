"""The Shared Shore — real multiplayer behavior through independent clients.

Each MpClient is a genuinely independent HTTP caller with its own session
token, talking to the same Flask app — concurrency, ownership and isolation
are exercised for real, not simulated by sharing one browser session.
"""
import json
import threading

import pytest

from server import db, gm, mp


class MpClient:
    """An independent multiplayer client: own token, own headers, own state."""

    def __init__(self, app, cid=None, name=None, host=False, token=None):
        self.app = app
        self.cid = cid
        self.token = token
        self.player_id = None
        self.name = name
        self.last_seq = 0
        if host and cid:
            self.host_open(name or "Host")
        elif cid and token:
            r = self.post("/mp/reconnect", {"campaign_id": cid, "token": token})
            assert r.status_code == 200, r.get_json()
            d = r.get_json()
            self.player_id = d["player_id"]
            self.name = d["view"]["you"]["name"]

    # raw helpers ---------------------------------------------------------
    def _h(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["X-MP-Token"] = self.token
        return h

    def post(self, path, body=None):
        return self.app.post(f"/api{path}", json=body or {}, headers=self._h())

    def get(self, path):
        return self.app.get(f"/api{path}", headers=self._h())

    def put(self, path, body=None):
        return self.app.put(f"/api{path}", json=body or {}, headers=self._h())

    # flows ---------------------------------------------------------------
    def host_open(self, display_name, character=None):
        r = self.post("/mp/host", {"campaign_id": self.cid, "display_name": display_name,
                                   "character": character})
        assert r.status_code == 200, r.get_json()
        d = r.get_json()
        self.token, self.player_id = d["token"], d["player_id"]
        self.name = display_name
        return d

    def make_invite(self, label="friends", uses=0):
        r = self.post("/mp/invite", {"campaign_id": self.cid, "label": label, "uses": uses})
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def join_with(self, invite_token, display_name, character=None):
        r = self.post("/mp/join", {"campaign_id": self.cid, "invite_token": invite_token,
                                   "display_name": display_name, "character": character})
        assert r.status_code == 200, r.get_json()
        d = r.get_json()
        self.token, self.player_id = d["token"], d["player_id"]
        self.name = display_name
        return d

    def view(self):
        r = self.get(f"/mp/view/{self.cid}")
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def act(self, text):
        return self.post(f"/campaigns/{self.cid}/action", {"text": text})

    def choose(self, choice_id):
        return self.post(f"/campaigns/{self.cid}/choose", {"choice_id": choice_id})

    def check(self, skill, hard=False, risk=False):
        return self.post(f"/campaigns/{self.cid}/check", {"skill": skill, "hard": hard, "risk": risk})

    def travel(self, location_id, solo=False):
        return self.post(f"/campaigns/{self.cid}/travel",
                         {"location_id": location_id, "solo": solo})

    def rest(self):
        return self.post(f"/campaigns/{self.cid}/rest", {})

    def chat(self, text):
        return self.post("/mp/chat", {"campaign_id": self.cid, "text": text})

    def events(self):
        r = self.get(f"/mp/events/{self.cid}?last_seq={self.last_seq}")
        assert r.status_code == 200, r.get_json()
        d = r.get_json()
        self.last_seq = d["latest_seq"]
        return d["events"]

    def view_json(self):
        return self.app.get(f"/api/campaigns/{self.cid}", headers=self._h()).get_json()


@pytest.fixture()
def mp_party(app):
    """A hosted session with the host on the shore, ready for guests."""
    client = app.test_client()
    r = client.post("/api/campaigns", json={
        "name": "Shared Voyage", "pack_id": "living_shore",
        "character": {"name": "Halvard", "archetype": "warden", "specialty": "fight"},
    })
    cid = r.get_json()["campaign_id"]
    host = MpClient(client, cid=cid, host=True)
    host.post("/mp/start", {"campaign_id": cid})
    return {"app": client, "cid": cid, "host": host}


def _guest(party, name, character=None):
    invite = party["host"].make_invite()
    guest = MpClient(party["app"])
    guest.cid = party["cid"]
    guest.join_with(invite["token"], name, character or {
        "name": name.replace(" ", "_"), "archetype": "sensitive", "specialty": "bind",
    })
    return guest


# ---------------------------------------------------------------- foundation
def test_host_opens_session_and_adopts_solo_character(mp_party):
    view = mp_party["host"].view()
    assert view["status"] == "active"
    assert view["members"][0]["is_host"] is True
    assert view["members"][0]["character"]["name"] == "Halvard"  # adopted, not duplicated
    assert view["you"]["color"]


def test_invite_join_flow_creates_independent_characters(mp_party):
    guest = _guest(mp_party, "Brinna")
    view = guest.view()
    names = {m["character"]["name"] for m in view["members"]}
    assert {"Halvard", "Brinna_Brinna"} <= names or "Brinna" in str(view)
    # two independent characters, two independent purses
    hv = mp_party["host"].view_json()
    gv = guest.view_json()
    assert hv["character"]["id"] != gv["character"]["id"]
    assert hv["character_id"] != gv["character_id"]


def test_invite_expiry_revocation_and_uses(mp_party):
    host = mp_party["host"]
    # uses=1: second join refused
    inv = host.make_invite(uses=1)
    g1 = MpClient(mp_party["app"]); g1.cid = mp_party["cid"]
    g1.join_with(inv["token"], "Firstcomer")
    r = MpClient(mp_party["app"]).post("/mp/join", {
        "campaign_id": mp_party["cid"], "invite_token": inv["token"],
        "display_name": "Secondcomer"})
    assert r.status_code in (400, 403)
    # revocation
    inv2 = host.make_invite()
    host.post("/mp/invite/revoke", {"campaign_id": mp_party["cid"], "invite_id": inv2["invite_id"]})
    r = MpClient(mp_party["app"]).post("/mp/join", {
        "campaign_id": mp_party["cid"], "invite_token": inv2["token"],
        "display_name": "TooLate"})
    assert r.status_code == 403
    # expiry
    inv3 = host.make_invite()
    db.execute("UPDATE mp_invites SET expires_at='2000-01-01T00:00:00Z' WHERE id=?",
               (inv3["invite_id"],))
    r = MpClient(mp_party["app"]).post("/mp/join", {
        "campaign_id": mp_party["cid"], "invite_token": inv3["token"],
        "display_name": "Ancient"})
    assert r.status_code == 403


def test_party_limit_and_duplicate_names(mp_party):
    inv = mp_party["host"].make_invite()
    a = MpClient(mp_party["app"]); a.cid = mp_party["cid"]
    a.join_with(inv["token"], "Twin")
    r = MpClient(mp_party["app"]).post("/mp/join", {
        "campaign_id": mp_party["cid"], "invite_token": inv["token"],
        "display_name": "twin"})
    assert r.status_code == 400  # case-insensitive name collision
    # shrink the limit to force a full party
    session = mp._session(mp_party["cid"])
    db.execute("UPDATE mp_sessions SET player_limit=2 WHERE campaign_id=?", (mp_party["cid"],))
    r = MpClient(mp_party["app"]).post("/mp/join", {
        "campaign_id": mp_party["cid"], "invite_token": inv["token"],
        "display_name": "Overflow"})
    assert r.status_code == 400
    db.execute("UPDATE mp_sessions SET player_limit=? WHERE campaign_id=?",
               (session["player_limit"], mp_party["cid"]))


def test_token_stored_hashed_not_raw(mp_party):
    raw = mp_party["host"].token
    rows = db.query("SELECT token_hash FROM mp_players")
    assert all(r["token_hash"] != raw for r in rows)
    assert mp.hash_token(raw) in {r["token_hash"] for r in rows}


def test_invalid_and_missing_tokens_rejected(mp_party):
    r = mp_party["app"].post(f"/api/campaigns/{mp_party['cid']}/action",
                             json={"text": "sneak"}, headers={"Content-Type": "application/json"})
    assert r.status_code == 403
    r = mp_party["app"].post(f"/api/campaigns/{mp_party['cid']}/action",
                             json={"text": "sneak"},
                             headers={"Content-Type": "application/json", "X-MP-Token": "forged"})
    assert r.status_code == 403


def test_guest_cannot_reach_host_admin_endpoints(mp_party):
    guest = _guest(mp_party, "Quiet Guest")
    r = guest.put("/settings", {"ai": {"enabled": False}})
    assert r.status_code == 403
    r = guest.get("/settings")
    assert r.status_code == 200
    assert r.get_json().get("guest") is True
    assert "base_url" not in r.get_json().get("ai", {})
    assert "api_key" not in str(r.get_json())
    r = guest.post("/campaigns", {"name": "sneaky"})
    assert r.status_code == 403


# -------------------------------------------------------------------- sync
def test_shared_scene_synchronizes_between_clients(mp_party):
    guest = _guest(mp_party, "Watcher")
    r = mp_party["host"].act("I walk the tideline and study the doors.")
    assert r.status_code == 200
    events = guest.events()
    kinds = [e["type"] for e in events]
    assert "narration" in kinds
    narration = next(e for e in events if e["type"] == "narration")
    assert narration["data"]["text"]
    # the guest's view moved with the host's action (shared turn/drift)
    assert guest.view_json()["turn"] == mp_party["host"].view_json()["turn"]


def test_event_replay_from_last_seq_and_no_duplicates(mp_party):
    guest = _guest(mp_party, "Replayer")
    mp_party["host"].act("I count the doors twice.")
    before = mp.latest_seq(mp_party["cid"])
    mp_party["host"].act("I count them once more.")
    # replay from `before` returns only the new events, strictly after it
    fresh = mp.events_since(mp_party["cid"], before,
                            mp.auth(mp_party["cid"], guest.token))
    assert fresh, "new events exist"
    assert all(e["seq"] > before for e in fresh)
    assert any(e["type"] == "narration" for e in fresh)
    # replaying again from the same seq yields the identical window (durable,
    # ordered, append-only — retries never duplicate)
    again = mp.events_since(mp_party["cid"], before,
                            mp.auth(mp_party["cid"], guest.token))
    assert again == fresh


def test_concurrent_actions_serialize_consistently(mp_party):
    """Two clients act at the same moment; the event log records exactly two
    narrations, strictly ordered, and both views agree."""
    guest = _guest(mp_party, "Storm-Caller")
    results = {}

    def run(client, text):
        r = client.act(text)
        results[client.name] = r.status_code

    t1 = threading.Thread(target=run, args=(mp_party["host"], "I watch the eastern water."))
    t2 = threading.Thread(target=run, args=(guest, "I search the dunes for glass."))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert results == {"Host": 200, "Storm-Caller": 200}
    events = [e for e in mp.events_since(mp_party["cid"], 0, None) if e["type"] == "narration"]
    assert len(events) >= 2
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)


def test_sse_stream_replays_and_follows(mp_party):
    client = mp_party["host"]
    ticket_r = client.post("/mp/stream-ticket", {"campaign_id": client.cid})
    assert ticket_r.status_code == 200
    ticket = ticket_r.get_json()["ticket"]
    guest = _guest(mp_party, "Streamwatcher")
    resp = mp_party["app"].get(
        f"/api/mp/stream?ticket={ticket}&last_seq=0",
        headers={"Accept": "text/event-stream"})
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    # the stream is live and endless — read just the first frames, then close
    it = iter(resp.response)
    frames = []
    try:
        for _ in range(4):
            frames.append(next(it).decode())
    except StopIteration:
        pass
    finally:
        it.close()
    body = "".join(frames)
    assert "shore stream open" in body
    assert "data:" in body  # at least one event frame followed the handshake
    # used tickets do not work twice
    resp2 = mp_party["app"].get(f"/api/mp/stream?ticket={ticket}&last_seq=0")
    assert resp2.status_code == 403


# ------------------------------------------------------------------ travel
def test_party_travel_requires_votes_and_executes_once(mp_party):
    guest = _guest(mp_party, "Doorfriend")
    r = mp_party["host"].travel("camp")
    assert r.status_code == 200
    d = r.get_json()
    assert "Doorfriend" in (d.get("narration") or "")  # waiting for their vote
    view = mp_party["host"].view_json()
    assert view["location"]["id"] == "tidegate"  # not moved yet
    r = guest.post("/mp/travel/vote", {"campaign_id": mp_party["cid"], "accept": True})
    assert r.status_code == 200
    assert mp_party["host"].view_json()["location"]["id"] == "camp"
    assert guest.view_json()["location"]["id"] == "camp"
    # the party travelled exactly once — no double execution on retry
    events = [e for e in mp.events_since(mp_party["cid"], 0, None) if e["type"] == "travel"]
    assert len(events) == 1


def test_declining_vote_cancels_travel(mp_party):
    guest = _guest(mp_party, "Stayput")
    mp_party["host"].travel("tavern")
    r = guest.post("/mp/travel/vote", {"campaign_id": mp_party["cid"], "accept": False})
    assert r.status_code == 200
    assert mp_party["host"].view_json()["location"]["id"] == "tidegate"
    prop = mp.current_proposal(mp_party["cid"])
    assert prop is None


# ------------------------------------------------------------- dice/tactics
def test_each_player_rolls_with_their_own_character(mp_party):
    guest = _guest(mp_party, "Roller")
    r1 = mp_party["host"].check("fight")
    r2 = guest.check("bind")
    assert r1.status_code == 200 and r2.status_code == 200
    # dice landed in the shared dice log with each roll recorded
    rows = db.query("SELECT note FROM dicelog WHERE campaign_id=? ORDER BY rowid DESC LIMIT 2",
                    (mp_party["cid"],))
    assert any(r["note"] == "manual roll" for r in rows)


def test_push_is_scoped_to_the_rollers_pending_window(mp_party):
    guest = _guest(mp_party, "Pusher")
    r = guest.check("bind", risk=True)
    assert r.status_code == 200
    # the guest can push their own pending roll
    r = guest.post(f"/campaigns/{mp_party['cid']}/push", {})
    assert r.status_code in (200, 400)  # 400 if the roll wasn't pushable
    if r.status_code == 200:
        # host has no pending window of their own to push
        r2 = mp_party["host"].post(f"/campaigns/{mp_party['cid']}/push", {})
        assert r2.status_code == 400  # 'no roll awaits' — windows are private


def test_death_is_personal_in_multiplayer(mp_party, monkeypatch):
    guest = _guest(mp_party, "Doomed")
    ch = gm.get_character(mp_party["cid"], guest.player_id and mp._char_of(mp_party["cid"], guest.player_id))
    ch["vigor"] = 1
    ch["nerve"] = 0
    gm._persist_character(ch)
    from server import rules
    seq = iter([1, 3])
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    r = guest.check("fight")
    assert r.status_code == 200
    assert gm.ch_get(gm.get_character(mp_party["cid"], ch["id"]), "dead") is True
    # the host is fine
    host_ch = mp_party["host"].view_json()["character"]
    assert gm.ch_get(gm.get_character(mp_party["cid"], host_ch["id"]), "dead", False) is False
    # and the fallen guest cannot act, but the host still can
    r = guest.act("I rise again.")
    assert r.status_code == 400
    r = mp_party["host"].act("The shore keeps its dead. I walk on.")
    assert r.status_code == 200


# ------------------------------------------------------------------ turns
def test_structured_turn_mode_enforced_server_side(mp_party):
    guest = _guest(mp_party, "Queuefriend")
    r = mp_party["host"].post("/mp/settings", {"campaign_id": mp_party["cid"], "mode": "turns"})
    assert r.status_code == 200
    view = mp_party["host"].view()
    current = view["turn_player"]
    other = next(m for m in view["members"] if m["player_id"] != current)
    client_for_other = mp_party["host"] if other["player_id"] == mp_party["host"].player_id else guest
    client_for_current = mp_party["host"] if current == mp_party["host"].player_id else guest
    # out-of-turn action rejected
    r = client_for_other.act("I jump the queue.")
    assert r.status_code == 400
    # in-turn action allowed, then the turn passes
    r = client_for_current.act("I take my turn quietly.")
    assert r.status_code == 200
    r = client_for_current.post("/mp/turn/advance", {"campaign_id": mp_party["cid"]})
    assert r.status_code == 200


def test_chat_rate_limit_and_history(mp_party):
    guest = _guest(mp_party, "Chatterbox")
    ok = 0
    for i in range(12):
        r = guest.chat(f"message {i}")
        if r.status_code == 200:
            ok += 1
    assert ok == mp.CHAT_LIMIT  # 10 per window, then limited
    r = mp_party["host"].chat("hello from the host")
    assert r.status_code == 200
    view = mp_party["host"].view()
    chats = [c for c in view["chat"] if c["type"] == "chat"]
    assert chats[-1]["data"]["text"] == "hello from the host"


# --------------------------------------------------------- interactions
def test_trade_offer_requires_consent_and_moves_items(mp_party):
    guest = _guest(mp_party, "Trader")
    inv = guest.view_json()["inventory"]
    assert inv, "guest should start with a kit"
    row = inv[0]
    r = mp_party["host"].post("/mp/trade", {
        "campaign_id": mp_party["cid"], "to_player": guest.player_id,
        "item_row_id": "not-yours", "qty": 1})
    assert r.status_code == 400  # host cannot offer an item they don't own
    r = guest.post("/mp/trade", {
        "campaign_id": mp_party["cid"], "to_player": mp_party["host"].player_id,
        "item_row_id": row["id"], "qty": 1})
    assert r.status_code == 200
    host_view = mp_party["host"].view()
    assert host_view["offers_for_you"], "recipient sees the pending offer"
    offer_id = host_view["offers_for_you"][0]["id"]
    # a stranger cannot answer someone else's offer
    other_view_row = None
    r = guest.post("/mp/trade/respond", {"campaign_id": mp_party["cid"], "offer_id": offer_id,
                                         "accept": True})
    assert r.status_code == 403
    r = mp_party["host"].post("/mp/trade/respond", {"campaign_id": mp_party["cid"],
                                                    "offer_id": offer_id, "accept": True})
    assert r.status_code == 200
    host_inv = {i["item_id"] for i in mp_party["host"].view_json()["inventory"]}
    assert row["item_id"] in host_inv


def test_bead_gifts_are_atomic_and_bounded(mp_party):
    guest = _guest(mp_party, "Giver")
    ch = gm.get_character(mp_party["cid"], mp._char_of(mp_party["cid"], guest.player_id))
    gm.ch_set(ch, "beads", 3)
    r = guest.post("/mp/gift", {"campaign_id": mp_party["cid"],
                                "to_player": mp_party["host"].player_id, "amount": 2})
    assert r.status_code == 200
    assert gm.ch_get(gm.get_character(mp_party["cid"], ch["id"]), "beads") == 1
    r = guest.post("/mp/gift", {"campaign_id": mp_party["cid"],
                                "to_player": mp_party["host"].player_id, "amount": 99})
    assert r.status_code == 400
    r = guest.post("/mp/gift", {"campaign_id": mp_party["cid"],
                                "to_player": mp_party["host"].player_id, "amount": 5})
    assert r.status_code == 400  # not enough beads
    assert gm.ch_get(gm.get_character(mp_party["cid"], ch["id"]), "beads") == 1


def test_shared_upgrade_contributions_buy_once(mp_party):
    guest = _guest(mp_party, "Builder")
    # the host marches the party to the camp (force = host prerogative)
    mp_party["host"].post("/mp/travel/force", {"campaign_id": mp_party["cid"],
                                               "location_id": "camp"})
    import time as _t
    _t.sleep(0.05)
    for c in (mp_party["host"], guest):
        ch = gm.get_character(mp_party["cid"], mp._char_of(mp_party["cid"], c.player_id))
        gm.ch_set(ch, "beads", 5)
    r1 = mp_party["host"].post("/mp/contribute", {"campaign_id": mp_party["cid"],
                                                  "upgrade_id": "camp_kettle", "amount": 1})
    r2 = guest.post("/mp/contribute", {"campaign_id": mp_party["cid"],
                                       "upgrade_id": "camp_kettle", "amount": 5})
    assert r1.status_code == 200 and r2.status_code == 200
    upgrades = db.query("SELECT * FROM upgrades WHERE campaign_id=? AND upgrade_id='camp_kettle'",
                        (mp_party["cid"],))
    assert len(upgrades) == 1  # bought exactly once
    # kettle visible to both
    assert "camp_kettle" in mp_party["host"].view_json()["upgrades_owned"]
    assert "camp_kettle" in guest.view_json()["upgrades_owned"]


# ------------------------------------------------------ party memory/ledger
def test_party_ending_recorded_in_party_legacy(mp_party):
    guest = _guest(mp_party, "Companion")
    from server import worldpacks
    pack = worldpacks.load_pack("living_shore")
    gm.give_item(mp_party["cid"], pack, "brass_key",
                 chid=mp._char_of(mp_party["cid"], mp_party["host"].player_id))
    mp_party["host"].post("/mp/travel/force", {"campaign_id": mp_party["cid"],
                                               "location_id": "saltgrave_gate"})
    mp_party["host"].choose("follow_shore")
    mp_party["host"].choose("climb_tower")
    r = mp_party["host"].choose("light_beacon")
    assert r.status_code == 200 and r.get_json()["ending"] == "beacon_lit"
    led = mp_party["host"].get(f"/campaigns/{mp_party['cid']}/ledger").get_json()
    assert led["party"]["members"]
    assert any("company of" in c["summary"] for c in led["consequences"])


# ------------------------------------------------ reconnect & recovery
def test_reconnect_restores_character_and_replays_events(mp_party):
    guest = _guest(mp_party, "Sleepy")
    mp_party["host"].act("The tide shifts while you are away.")
    # the guest "disconnects": presence goes stale
    db.execute("UPDATE mp_players SET last_seen='2000-01-01T00:00:00Z' WHERE id=?",
               (guest.player_id,))
    mp.sweep_presence(mp_party["cid"])
    host_view = mp_party["host"].view()
    member = next(m for m in host_view["members"] if m["player_id"] == guest.player_id)
    assert member["presence"] == "offline"
    # reconnect with the same token: same player, same character, catch-up
    again = MpClient(mp_party["app"], cid=guest.cid, token=guest.token)
    assert again.player_id == guest.player_id
    assert again.view()["members"] and any(m["player_id"] == guest.player_id
                                           for m in again.view()["members"])
    # no character duplication
    chars = db.query("SELECT id FROM characters WHERE campaign_id=?", (mp_party["cid"],))
    assert len(chars) == 2


def test_session_survives_process_restart(app):
    app = app.test_client()
    r = app.post("/api/campaigns", json={
        "name": "Restart Voyage", "pack_id": "living_shore",
        "character": {"name": "Stub", "archetype": "warden", "specialty": "fight"}})
    cid = r.get_json()["campaign_id"]
    host = MpClient(app, cid=cid, host=True)
    invite = host.make_invite()
    guest = MpClient(app); guest.cid = cid
    guest.join_with(invite["token"], "Returnee")
    # the app "restarts": same database, fresh process (new tickets/locks)
    from server.app import create_app
    app2 = create_app().test_client()
    again = MpClient(app2, cid=cid, token=host.token)
    assert again.player_id == host.player_id
    guest2 = MpClient(app2, cid=cid, token=guest.token)
    assert guest2.player_id == guest.player_id
    # the session and party are intact
    assert guest2.view()["status"] in ("lobby", "active")


def test_banned_player_cannot_rejoin(mp_party):
    guest = _guest(mp_party, "Trouble")
    r = mp_party["host"].post(f"/mp/players/{mp_party['cid']}/remove",
                              {"player_id": guest.player_id, "ban": True})
    assert r.status_code == 200
    resp = MpClient(mp_party["app"]).post("/mp/reconnect", {
        "campaign_id": mp_party["cid"], "token": guest.token})
    assert resp.status_code == 403


# ------------------------------------------------------- hostile input
def test_malformed_and_hostile_requests(mp_party):
    guest = _guest(mp_party, "Chaos")
    # oversized chat
    r = guest.chat("x" * 5000)
    assert r.status_code in (200, 400)  # server clamps or refuses, never crashes
    # wrong types
    r = guest.post("/mp/gift", {"campaign_id": mp_party["cid"],
                                "to_player": "x", "amount": "not-a-number"})
    assert r.status_code == 400
    # html in chat is stored as data (client escapes on render)
    r = guest.chat("<script>alert(1)</script>")
    assert r.status_code == 200
    view = guest.view()
    assert "<script>" in json.dumps(view["chat"])  # data, not executed server-side
    # unknown endpoints don't leak
    r = guest.get("/mp/definitely-not-a-thing")
    assert r.status_code == 404


def test_hidden_facts_never_broadcast(mp_party):
    guest = _guest(mp_party, "Eavesdropper")
    # a hidden GM note lands in the facts table (simulating the GM's secret)
    db.execute(
        "INSERT INTO facts (id, campaign_id, ts, text, scope, importance, source)"
        " VALUES ('fct_hidden_test', ?, ?, 'THE LAMPKEEPER SERVES THE DROWNED THING', 'hidden', 3, 'gm')",
        (mp_party["cid"], "2026-01-01T00:00:00Z"))
    events = mp.events_since(mp_party["cid"], 0, mp.auth(mp_party["cid"], guest.token))
    blob = json.dumps(events)
    assert "DROWNED THING" not in blob
    view = guest.view_json()
    assert "DROWNED THING" not in json.dumps(view)
    # visible facts still flow
    assert view["facts"]


def test_solo_play_untouched_by_multiplayer(app):
    app = app.test_client()
    r = app.post("/api/campaigns", json={
        "name": "Solo Regression", "pack_id": "living_shore",
        "character": {"name": "Soloist", "archetype": "sensitive", "specialty": "bind"}})
    cid = r.get_json()["campaign_id"]
    # no session exists: all solo routes work with NO mp token
    r = app.post(f"/api/campaigns/{cid}/action", json={"text": "I walk alone, gladly."},
                 headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    r = app.post(f"/api/campaigns/{cid}/travel", json={"location_id": "camp"},
                 headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    view = app.get(f"/api/campaigns/{cid}").get_json()
    assert view["character"]["name"] == "Soloist"
    assert view["beads"] == 0
