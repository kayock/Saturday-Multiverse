#!/usr/bin/env python3
"""Hotfix 5 live LAN acceptance: real servers, real certificates, real
conversations — over direct HTTPS with a CA-verifying client (no verify=False
anywhere). Exercises the two hotfix-5 repairs end-to-end:

- recap entitlement: a past visit no longer discloses rumors created later;
  recaps use the same specific-memory entitlement as the sharing engine;
- NPC secret protection: the Drowned Lampkeeper's GM-only deep secret never
  appears in the conversation response, the transcripts, the game events,
  the character's knowledge, the campfire picker or a share attempt — and a
  genuine tavern conversation still discloses and records exactly what was
  spoken, with party sharing, future-rumor privacy, restart persistence and
  solo flows over plain HTTP.
"""
import http.client
import json
import os
import socket
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SECRET = "The ADMINISTRATOR KEY rests beneath the ninth stair."
OK = []


def ok(name, cond, detail=""):
    OK.append((name, bool(cond)))
    print(("  PASS " if cond else "  FAIL ") + name + (f" — {detail}" if detail else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Srv:
    def __init__(self, data_dir, env):
        self.port = free_port()
        self.data = data_dir
        e = dict(os.environ)
        e.update({"SATURDAY_DATA_DIR": str(data_dir), "SATURDAY_PORT": str(self.port),
                  "SATURDAY_HOST": "0.0.0.0", "SATURDAY_RATE_MULT": "100",
                  "PYTHONUNBUFFERED": "1"})
        e.update(env)
        self.env = e
        self.p = None

    def start(self):
        self.p = subprocess.Popen([sys.executable, "-u", "-m", "server.app"],
                                  cwd=str(ROOT), env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        tls_probe = self.env.get("SATURDAY_TLS") in ("1", "true", "yes")
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                self.get("/api/health", tls=tls_probe)
                return True
            except Exception:
                if self.p.poll() is not None:
                    try:
                        print(self.p.stdout.read().decode(errors="replace")[-600:])
                    except Exception:
                        pass
                    return False
                time.sleep(0.3)
        return False

    def stop(self):
        if self.p:
            self.p.terminate()
            try:
                self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.p.kill()

    def conn(self, tls=False):
        host = os.environ.get("LANIP") or "127.0.0.1"
        if tls:
            ctx = ssl.create_default_context(
                cafile=str(self.data / "certs" / "saturday-lan-ca.crt"))
            return http.client.HTTPSConnection(host, self.port, context=ctx, timeout=15)
        return http.client.HTTPConnection(host, self.port, timeout=15)

    def req(self, method, path, body=None, token=None, tls=False):
        c = self.conn(tls)
        h = {"Content-Type": "application/json"}
        if token:
            h["X-MP-Token"] = token
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw.decode())
        except Exception:
            return r.status, {"_raw": raw[:300].decode(errors="replace")}

    def get(self, path, token=None, tls=False):
        return self.req("GET", path, token=token, tls=tls)

    def post(self, path, body=None, token=None, tls=False):
        return self.req("POST", path, body, token=token, tls=tls)


def _db_path(data: Path) -> Path:
    hits = list(Path(data).glob("*.db"))
    assert hits, "no sqlite database in the data directory"
    return hits[0]


def _acquired(con, cid, character_id):
    return {r[0] for r in con.execute(
        "SELECT ref FROM char_knowledge WHERE campaign_id=? AND character_id=?"
        " AND kind='memory'", (cid, character_id)).fetchall()}


def main():
    lan_ips = []
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if ip != "127.0.0.1" and ip not in lan_ips:
                lan_ips.append(ip)
    except OSError:
        pass
    os.environ["LANIP"] = lan_ips[0] if lan_ips else "127.0.0.1"
    print(f"client-facing address for this run: {os.environ['LANIP']}")

    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        os.environ["SATURDAY_DATA_DIR"] = str(data)
        from server import tls as _tls
        _tls.refresh()
        r = subprocess.run([sys.executable, "scripts/cert_setup.py", "generate"],
                           cwd=str(ROOT), env=dict(os.environ),
                           capture_output=True, text=True)
        ok("cert_setup.py generate", r.returncode == 0, r.stderr[-160:])

        srv = Srv(data, {"SATURDAY_TLS": "1"})
        ok("Case B boots (direct HTTPS)", srv.start())
        cid = gm_mid = rumor1 = rumor2 = ""
        try:
            st, h = srv.get("/api/health", tls=True)
            ok("health over HTTPS (CA-verified client)", st == 200 and h["ok"])

            st, c = srv.post("/api/campaigns",
                             {"name": "LAN HF5 Secrets", "pack_id": "living_shore",
                              "character": {"name": "Annora", "archetype": "sensitive",
                                            "specialty": "bind"}}, tls=True)
            cid = c["campaign_id"]
            st, host = srv.post("/api/mp/host", {"campaign_id": cid,
                                                 "display_name": "Annora"}, tls=True)
            ht = host["token"]
            srv.post("/api/mp/start", {"campaign_id": cid}, token=ht, tls=True)
            st, inv = srv.post("/api/mp/invite", {"campaign_id": cid, "uses": 4},
                               token=ht, tls=True)
            st, g = srv.post("/api/mp/join",
                             {"campaign_id": cid, "invite_token": inv["token"],
                              "display_name": "Bren",
                              "character": {"name": "Bren", "archetype": "sensitive",
                                            "specialty": "bind"}}, tls=True)
            gt = g.get("token", "")
            ok("guest joins over HTTPS", st == 200 and bool(gt))

            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            rows = dict(con.execute(
                "SELECT id, character_id FROM mp_players WHERE campaign_id=?",
                (cid,)).fetchall())
            cha, chb = rows[host["player_id"]], rows[g["player_id"]]
            con.commit()
            con.close()

            from server import legacy as _lg
            # step 1: a GM-only deep-scoped memory only the Lampkeeper knows
            gm_mid = _lg.remember(cid, "deep", "gm", SECRET)
            # steps 2-5: A talks to the Lampkeeper about an unrelated topic
            srv.post(f"/api/campaigns/{cid}/travel",
                     {"location_id": "saltgrave_gate", "solo": True},
                     token=ht, tls=True)
            st, talk = srv.post(f"/api/campaigns/{cid}/talk",
                                {"npc_id": "drowned_lampkeeper", "topic": "weather"},
                                token=ht, tls=True)
            ok("A talks with the Lampkeeper over HTTPS", st == 200, str(talk)[:70])
            ok("the secret is absent from the conversation response",
               SECRET not in json.dumps(talk)
               and gm_mid not in [m.get("id") for m in talk.get("memories", [])])
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            ok("the secret is absent from A's char_knowledge",
               gm_mid not in _acquired(con, cid, cha))
            blob = json.dumps([dict(x) for x in con.execute(
                "SELECT role, content, data_json FROM transcript WHERE campaign_id=?",
                (cid,)).fetchall()])
            ok("the secret is absent from the player-facing transcript",
               SECRET not in blob)
            ev = json.dumps([dict(x) for x in con.execute(
                "SELECT type, data_json FROM events WHERE campaign_id=?",
                (cid,)).fetchall()])
            ok("the secret is absent from game events (Engine Trace)",
               SECRET not in ev)
            con.commit()
            con.close()
            st, picker = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                                 token=ht, tls=True)
            ok("the campfire picker never offers the secret",
               gm_mid not in [m["ref"] for m in picker.get("memories", [])])
            st, sh = srv.post(f"/api/campaigns/{cid}/campfire",
                              {"kind": "memory", "text": "…", "share": [gm_mid]},
                              token=ht, tls=True)
            ok("sharing the secret at the fire is refused",
               sh.get("share", {}).get("shared") == [])

            # steps 7-9: a legitimate tavern rumor; A travels and hears it
            rumor1 = _lg.remember(cid, "tavern", "gossip",
                                  "Rumor A5: the strange cargo came ashore.")
            srv.post(f"/api/campaigns/{cid}/travel",
                     {"location_id": "tavern", "solo": True}, token=ht, tls=True)
            st, talk2 = srv.post(f"/api/campaigns/{cid}/talk",
                                 {"npc_id": "maren", "topic": "cargo"}, token=ht, tls=True)
            ok("A talks with Maren over HTTPS", st == 200, str(talk2)[:70])
            ok("the response carries exactly the disclosed rumor",
               [m.get("id") for m in talk2.get("memories", [])] == [rumor1],
               json.dumps(talk2.get("memories", []))[:100])
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            ok("that specific rumor is recorded as acquired",
               rumor1 in _acquired(con, cid, cha))
            ok("B does not automatically know it",
               rumor1 not in _acquired(con, cid, chb))
            con.commit()
            con.close()

            # steps 11-12: A shares it explicitly; B now knows that rumor
            st, s1 = srv.post(f"/api/campaigns/{cid}/campfire",
                              {"kind": "memory", "text": "At the tavern…",
                               "share": [rumor1]}, token=ht, tls=True)
            ok("A shares the rumor over HTTPS",
               s1.get("share", {}).get("shared") == [rumor1])
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            ok("B now knows exactly that rumor",
               rumor1 in _acquired(con, cid, chb))
            con.commit()
            con.close()
            st, rec_b = srv.get(f"/api/campaigns/{cid}/recap", token=gt, tls=True)
            ok("the shared rumor reaches B's recap",
               "strange cargo" in json.dumps(rec_b))

            # steps 13-16: a later rumor stays hidden until actually heard
            rumor2 = _lg.remember(cid, "tavern", "gossip",
                                  "Rumor B5: the bell rings itself on fog nights.")
            st, rec_a0 = srv.get(f"/api/campaigns/{cid}/recap", token=ht, tls=True)
            ok("a past visit does not reveal the later rumor (recap unified)",
               "bell rings itself" not in json.dumps(rec_a0))
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            ok("neither character has learned the later rumor",
               rumor2 not in _acquired(con, cid, cha)
               and rumor2 not in _acquired(con, cid, chb))
            con.commit()
            con.close()
            srv.post(f"/api/campaigns/{cid}/talk",
                     {"npc_id": "maren", "topic": "ledger"}, token=ht, tls=True)
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            ok("the return visit delivers and records the new rumor",
               rumor2 in _acquired(con, cid, cha)
               and rumor2 not in _acquired(con, cid, chb))
            con.commit()
            con.close()
            st, picker_a = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                                   token=ht, tls=True)
            ok("the new rumor is now individually shareable by A",
               rumor2 in [m["ref"] for m in picker_a.get("memories", [])])
            st, rec_a1 = srv.get(f"/api/campaigns/{cid}/recap", token=ht, tls=True)
            ok("the recap now shows what A genuinely knows",
               "bell rings itself" in json.dumps(rec_a1)
               and SECRET not in json.dumps(rec_a1))
        finally:
            srv.stop()

        # steps 17-18: restart; legitimate knowledge persists, secrets stay
        srv2 = Srv(data, {"SATURDAY_TLS": "1"})
        ok("application restarts (HTTPS) on the same data directory", srv2.start())
        try:
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            rows = dict(con.execute(
                "SELECT id, character_id FROM mp_players WHERE campaign_id=?",
                (cid,)).fetchall())
            cha, chb = rows[host["player_id"]], rows[g["player_id"]]
            ok("legitimate acquisitions survive the restart",
               rumor1 in _acquired(con, cid, cha) and rumor2 in _acquired(con, cid, cha)
               and rumor1 in _acquired(con, cid, chb)
               and rumor2 not in _acquired(con, cid, chb)
               and gm_mid not in _acquired(con, cid, cha)
               and gm_mid not in _acquired(con, cid, chb))
            con.commit()
            con.close()
        finally:
            srv2.stop()

        # solo flows over plain HTTP: disclosure-tracked conversations too
        http_srv = Srv(data, {})
        ok("Case A boots (plain HTTP)", http_srv.start())
        try:
            st, c2 = http_srv.post("/api/campaigns",
                                   {"name": "Solo HF5", "pack_id": "living_shore",
                                    "character": {"name": "Wander", "archetype": "sensitive",
                                                  "specialty": "bind"}})
            cid2 = c2["campaign_id"]
            http_srv.post(f"/api/campaigns/{cid2}/travel",
                          {"location_id": "tavern", "solo": True})
            st, t = http_srv.post(f"/api/campaigns/{cid2}/talk",
                                  {"npc_id": "maren", "topic": "cargo"})
            ok("solo conversation works over plain HTTP", st == 200)
            con = sqlite3.connect(_db_path(data))
            con.row_factory = sqlite3.Row
            solo_char = con.execute("SELECT character_id FROM campaigns WHERE id=?",
                                    (cid2,)).fetchone()[0]
            solo_talked = _acquired(con, cid2, solo_char)
            con.commit()
            con.close()
            ok("solo talk acquires exactly the disclosed memories",
               bool(solo_talked) and len(solo_talked) == len(t.get("memories", [])),
               f"{len(solo_talked)} acquired / {len(t.get('memories', []))} disclosed")
            st, sh3 = http_srv.get(f"/api/campaigns/{cid2}/campfire/shareable")
            ok("solo picker works without any multiplayer token",
               st == 200 and sh3.get("memories"))
        finally:
            http_srv.stop()

    passed = sum(1 for _, c in OK if c)
    print(f"\nLAN HF5 verification: {passed}/{len(OK)} checks passed")
    return 0 if passed == len(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
