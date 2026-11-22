#!/usr/bin/env python3
"""Hotfix 4 live LAN acceptance: real servers, real certificates, real
conversations. Exercises the two hotfix-4 repairs end-to-end over direct
HTTPS with a CA-verifying client (no verify=False anywhere):

- picker authorization: missing/invalid tokens are refused (403) on a
  session-bearing campaign and NEVER fall back to the campaign's character;
  spectators receive no character-owned knowledge; a genuine solo campaign
  needs no token;
- verified knowledge: a character shares exactly what a conversation
  delivered to them — a later rumor at the same place is not shareable until
  the character returns and hears it; party sharing grants exactly the shared
  memory; everything survives an application restart.

The living_shore pack provides the real flow: travel to the tavern, talk to
Maren, hear tavern rumors, retell one at the campfire.
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
        self.banner = ""
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
                        self.banner = self.p.stdout.read().decode(errors="replace")
                    except Exception:
                        self.banner = ""
                    print(self.banner[-600:])
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
        cid = rumor1 = rumor2 = mid_host = ""
        try:
            st, h = srv.get("/api/health", tls=True)
            ok("health over HTTPS (CA-verified client)", st == 200 and h["ok"])

            # a living_shore party; tavern is a real place, Maren lives there
            st, c = srv.post("/api/campaigns",
                             {"name": "LAN HF4 Tavern", "pack_id": "living_shore",
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
            rows = dict(con.execute(
                "SELECT id, character_id FROM mp_players WHERE campaign_id=?",
                (cid,)).fetchall())
            cha, chb = rows[host["player_id"]], rows[g["player_id"]]
            con.commit()
            con.close()

            # steps 1-2: A visits the tavern and hears Rumor 1 from Maren
            st, tr = srv.post(f"/api/campaigns/{cid}/travel",
                              {"location_id": "tavern", "solo": True},
                              token=ht, tls=True)
            ok("party travels to the tavern over HTTPS", st == 200, str(tr)[:80])
            # seed two tavern rumors through the engine's own recorder: one
            # BEFORE the conversation, one after A leaves
            con = sqlite3.connect(_db_path(data))
            from server import legacy as _lg  # engine-side seeding, ids verifiable
            rumor1 = _lg.remember(cid, "tavern", "gossip",
                                  "Rumor 1: the strange cargo came ashore at night.")
            con.commit()
            con.close()
            st, talk = srv.post(f"/api/campaigns/{cid}/talk",
                                {"npc_id": "maren", "topic": "cargo"}, token=ht, tls=True)
            ok("A talks with Maren over HTTPS (real delivery)", st == 200
               and talk.get("npc", {}).get("id") == "maren", str(talk)[:80])
            con = sqlite3.connect(_db_path(data))
            ok("the conversation recorded A's acquisition",
               rumor1 in _acquired(con, cid, cha))
            ok("B learned nothing of A's conversation",
               rumor1 not in _acquired(con, cid, chb))
            con.commit()
            con.close()
            # step 3-4: A leaves; Rumor 2 is created
            srv.post(f"/api/campaigns/{cid}/travel",
                     {"location_id": "camp", "solo": True}, token=ht, tls=True)
            rumor2 = _lg.remember(cid, "tavern", "gossip",
                                  "Rumor 2: the whisper broker bought the bell.")

            # step 5: A's picker includes Rumor 1, not Rumor 2
            st, sh_a = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                               token=ht, tls=True)
            refs_a = [m["ref"] for m in sh_a.get("memories", [])]
            ok("A's picker: Rumor 1 in, Rumor 2 out (hearing scope ≠ knowledge)",
               st == 200 and rumor1 in refs_a and rumor2 not in refs_a,
               json.dumps(refs_a)[:140])

            # step 8 (asked early because the session exists): unauthenticated
            # and forged-token pickers are REFUSED over HTTPS
            st0, b0 = srv.get(f"/api/campaigns/{cid}/campfire/shareable", tls=True)
            st1, b1 = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                              token="forged-token", tls=True)
            ok("missing/invalid tokens are refused over HTTPS (403, no fallback)",
               st0 == 403 and st1 == 403
               and "Rumor" not in json.dumps(b0) and "Rumor" not in json.dumps(b1),
               f"{st0}/{st1}")
            st, inv2 = srv.post(f"/api/campaigns/{cid}/mp/invite-spectator",
                                {}, token=ht, tls=True)
            st, spec = srv.post("/api/mp/join",
                                {"campaign_id": cid, "invite_token": inv2["token"],
                                 "display_name": "Watch4"}, tls=True)
            st, sh_s = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                               token=spec.get("token"), tls=True)
            ok("spectator picker carries no character knowledge",
               st == 200 and sh_s.get("places") == [] and sh_s.get("memories") == [])

            # step 6-7: A shares Rumor 1; B learns exactly that memory
            st, s1 = srv.post(f"/api/campaigns/{cid}/campfire",
                              {"kind": "memory", "text": "At the tavern…",
                               "share": [rumor1]}, token=ht, tls=True)
            ok("A shares Rumor 1 over HTTPS",
               st == 200 and s1.get("share", {}).get("shared") == [rumor1],
               json.dumps(s1.get("share", {}))[:120])
            con = sqlite3.connect(_db_path(data))
            ok("B's acquisition now holds exactly the shared memory",
               rumor1 in _acquired(con, cid, chb) and rumor2 not in _acquired(con, cid, chb))
            con.commit()
            con.close()
            st, sh_b = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                               token=gt, tls=True)
            refs_b = [m["ref"] for m in sh_b.get("memories", [])]
            ok("B's picker: Rumor 1 in, Rumor 2 out", rumor1 in refs_b
               and rumor2 not in refs_b)
            # B cannot share what they never heard; B can pass on what they did
            st, sb2 = srv.post(f"/api/campaigns/{cid}/campfire",
                               {"kind": "memory", "text": "…", "share": [rumor2]},
                               token=gt, tls=True)
            ok("B cannot share Rumor 2 (never heard)", sb2.get("share", {})
               .get("shared") == [])
            st, sb3 = srv.post(f"/api/campaigns/{cid}/campfire",
                               {"kind": "memory", "text": "Passing it on…",
                                "share": [rumor1]}, token=gt, tls=True)
            ok("B can re-share the memory they genuinely hold",
               sb3.get("share", {}).get("shared") == [rumor1])

            # forged references mutate nothing
            con = sqlite3.connect(_db_path(data))
            before = con.execute("SELECT COUNT(*) FROM knowledge_shares WHERE campaign_id=?",
                                 (cid,)).fetchone()[0]
            con.commit()
            con.close()
            st, sf = srv.post(f"/api/campaigns/{cid}/campfire",
                              {"kind": "memory", "text": "…",
                               "share": ["mem_forged_xyz", "kn_forged"]},
                              token=ht, tls=True)
            con = sqlite3.connect(_db_path(data))
            after = con.execute("SELECT COUNT(*) FROM knowledge_shares WHERE campaign_id=?",
                                (cid,)).fetchone()[0]
            con.commit()
            con.close()
            ok("forged references are refused and write nothing",
               sf.get("share", {}).get("shared") == [] and before == after)

            # steps 9-10: A returns and hears Rumor 2 — it becomes shareable
            srv.post(f"/api/campaigns/{cid}/travel",
                     {"location_id": "tavern", "solo": True}, token=ht, tls=True)
            st, talk2 = srv.post(f"/api/campaigns/{cid}/talk", {"npc_id": "maren", "topic": "ledger"},
                                 token=ht, tls=True)
            ok("A's return visit delivers the new rumor over HTTPS", st == 200)
            con = sqlite3.connect(_db_path(data))
            ok("the engine recorded the return-visit acquisition",
               rumor2 in _acquired(con, cid, cha))
            con.commit()
            con.close()
            st, sh_a2 = srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                                token=ht, tls=True)
            refs_a2 = [m["ref"] for m in sh_a2.get("memories", [])]
            ok("Rumor 2 is now individually shareable by A", rumor2 in refs_a2)
        finally:
            srv.stop()

        # steps 11-12: restart; knowledge persists
        srv2 = Srv(data, {"SATURDAY_TLS": "1"})
        ok("application restarts (HTTPS) on the same data directory", srv2.start())
        try:
            con = sqlite3.connect(_db_path(data))
            rows = dict(con.execute(
                "SELECT id, character_id FROM mp_players WHERE campaign_id=?",
                (cid,)).fetchall())
            cha, chb = rows[host["player_id"]], rows[g["player_id"]]
            acquired_ok = (rumor1 in _acquired(con, cid, cha)
                           and rumor2 in _acquired(con, cid, cha)
                           and rumor1 in _acquired(con, cid, chb)
                           and rumor2 not in _acquired(con, cid, chb))
            con.commit()
            con.close()
            ok("acquisition and shares survive the restart", acquired_ok)
        finally:
            srv2.stop()

        # solo flows over plain HTTP: no token needed, knowledge still verified
        http_srv = Srv(data, {})
        ok("Case A boots (plain HTTP)", http_srv.start())
        try:
            st, c2 = http_srv.post("/api/campaigns",
                                   {"name": "Solo HF4", "pack_id": "living_shore",
                                    "character": {"name": "Wander", "archetype": "sensitive",
                                                  "specialty": "bind"}})
            cid2 = c2["campaign_id"]
            http_srv.post(f"/api/campaigns/{cid2}/travel",
                          {"location_id": "tavern", "solo": True})
            st, t = http_srv.post(f"/api/campaigns/{cid2}/talk", {"npc_id": "maren", "topic": "cargo"})
            ok("solo conversation works over plain HTTP", st == 200)
            con = sqlite3.connect(_db_path(data))
            solo_char = con.execute("SELECT character_id FROM campaigns WHERE id=?",
                                    (cid2,)).fetchone()[0]
            solo_talked = _acquired(con, cid2, solo_char)
            con.commit()
            con.close()
            ok("solo talk acquires the delivered rumors", bool(solo_talked),
               f"{len(solo_talked)} memories")
            st, sh3 = http_srv.get(f"/api/campaigns/{cid2}/campfire/shareable")
            ok("solo picker works without any multiplayer token",
               st == 200 and sh3.get("memories"), json.dumps(sh3)[:100])
        finally:
            http_srv.stop()

    passed = sum(1 for _, c in OK if c)
    print(f"\nLAN HF4 verification: {passed}/{len(OK)} checks passed")
    return 0 if passed == len(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
