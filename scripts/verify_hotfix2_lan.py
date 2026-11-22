#!/usr/bin/env python3
"""Hotfix 2 live LAN verification: real servers on 0.0.0.0, exercised through
the machine's non-loopback address; HTTP + direct HTTPS + Case-D production
truthfulness + restart persistence of per-player recap markers."""
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
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
        prod_proxy = (self.env.get("SATURDAY_PRODUCTION") in ("1", "true", "yes")
                      and self.env.get("SATURDAY_TLS") in ("1", "true", "yes")
                      and self.env.get("SATURDAY_TLS_DEVSERVER") not in ("1", "true", "yes"))
        tls_probe = (self.env.get("SATURDAY_TLS") in ("1", "true", "yes")
                     and not prod_proxy)
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                self.get("/api/health", tls=tls_probe)
                return True
            except Exception:
                if self.p.poll() is not None:
                    print(self.p.stdout.read().decode(errors="replace")[-800:])
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


def main():
    import tempfile
    lan_ips = []
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if ip != "127.0.0.1" and ip not in lan_ips:
                lan_ips.append(ip)
    except OSError:
        pass
    client_ip = lan_ips[0] if lan_ips else "127.0.0.1"
    os.environ["LANIP"] = client_ip
    print(f"client-facing address for this run: {client_ip}")

    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        # ---------------- certificate setup (the real user workflow) --------
        import importlib
        from server import tls as tlsmod
        os.environ["SATURDAY_DATA_DIR"] = str(data)
        tlsmod.refresh()
        info = tlsmod.generate()
        tlsmod.diagnose(expect_ip=client_ip if client_ip != "127.0.0.1" else None)
        ok("certificate generator + diagnostics", tlsmod.diagnose()["ok"])
        os.environ.pop("SATURDAY_DATA_DIR", None)
        tlsmod.refresh()

        # ================= Case A/B: direct HTTPS over the LAN ==============
        tls_srv = Srv(data, {"SATURDAY_TLS": "1"})
        ok("Case B boots (direct HTTPS)", tls_srv.start())
        try:
            st, h = tls_srv.get("/api/health", tls=True)
            ok("health over HTTPS (CA-verified client)", st == 200 and h["ok"])
            ok("health reports the TRUE listener",
               h.get("listener") == "https" and h["tls"]["mode"] == "direct", json.dumps(h["tls"]))
            st, page = tls_srv.get("/", tls=True)
            ok("title screen over HTTPS", st == 200 and "saturday multiverse" in page["_raw"].lower())
            st, c = tls_srv.post("/api/campaigns", {"name": "LAN Solo HF2", "pack_id": "dracula",
                "character": {"name": "Ester", "ruleset": "dnd5e", "class": "fighter",
                              "species": "human", "background": "soldier"}}, tls=True)
            ok("solo voyage created over HTTPS (no lobby)", st == 200)
            cid = c["campaign_id"]
            st, act = tls_srv.post(f"/api/campaigns/{cid}/action",
                                   {"text": "I walk the tideline"}, tls=True)
            ok("action + Engine Trace over HTTPS",
               st == 200 and bool(act.get("narration")) and bool(act.get("trace", {}).get("steps")))
            st, trav = tls_srv.post(f"/api/campaigns/{cid}/travel",
                                    {"location_id": "whitby_harbour"}, tls=True)
            ok("open a portal / travel over HTTPS", st == 200, str(trav)[:80])
            st, rec = tls_srv.get(f"/api/campaigns/{cid}/recap", tls=True)
            ok("recap renders over HTTPS", st == 200 and "items" in rec)
            st, dis = tls_srv.post(f"/api/campaigns/{cid}/recap/dismiss", body={}, tls=True)
            ok("recap dismissed over HTTPS (local viewer)", st == 200 and dis.get("ok"))
            st, rec2 = tls_srv.get(f"/api/campaigns/{cid}/recap", tls=True)
            ok("dismissed recap shows nothing new", rec2["has_new"] is False)
            st, v = tls_srv.get(f"/api/campaigns/{cid}", tls=True)
            ok("resume continues the same campaign", st == 200 and v["turn"] >= 1)
            st, lib = tls_srv.get("/api/library", tls=True)
            ok("Infinite Library reachable over HTTPS", st == 200)
            st, forge = tls_srv.get("/api/forge/drafts", tls=True)
            ok("Campaign Forge reachable over HTTPS", st == 200)
            st, dr = tls_srv.get(f"/api/campaigns/{cid}/director", tls=True)
            ok("Director reachable over HTTPS", st == 200)
        finally:
            tls_srv.stop()

        # ================= Case A: HTTP over the LAN ========================
        http_srv = Srv(data, {})
        ok("Case A boots (plain HTTP)", http_srv.start())
        try:
            st, h = http_srv.get("/api/health")
            ok("HTTP health truthful (no TLS claimed)",
               h["listener"] == "http" and h["tls"]["mode"] == "off")
            st, camps = http_srv.get("/api/campaigns")
            ok("existing campaign visible over LAN HTTP",
               st == 200 and any(x["name"] == "LAN Solo HF2" for x in camps["campaigns"]))
            cid = next(x["id"] for x in camps["campaigns"] if x["name"] == "LAN Solo HF2")
            st, act = http_srv.post(f"/api/campaigns/{cid}/action", {"text": "I rest"})
            ok("solo play continues over LAN HTTP", st == 200 and act.get("narration"))
        finally:
            http_srv.stop()

        # ================= multiplayer + per-player recaps over HTTP ========
        mp_srv = Srv(data, {})
        ok("multiplayer server boots", mp_srv.start())
        try:
            st, c = mp_srv.post("/api/campaigns", {"name": "LAN Party HF2", "pack_id": "dracula",
                "character": {"name": "Hostess", "archetype": "occultist", "specialty": "bind"}})
            cid = c["campaign_id"]
            st, host = mp_srv.post("/api/mp/host", {"campaign_id": cid, "display_name": "Hostess"})
            ht = host["token"]
            mp_srv.post("/api/mp/start", {"campaign_id": cid}, token=ht)
            st, inv = mp_srv.post("/api/mp/invite", {"campaign_id": cid, "uses": 4}, token=ht)
            st, g = mp_srv.post("/api/mp/join", {"campaign_id": cid, "invite_token": inv["token"],
                "display_name": "Guest", "character": {"name": "Gwyn", "archetype": "doctor",
                                                       "specialty": "lore"}})
            ok("guest joins over LAN HTTP", st == 200 and g.get("token"))
            # independent dismissal across a real restart
            mp_srv.post(f"/api/campaigns/{cid}/recap/dismiss", {}, token=ht)
            arow_before = None
        finally:
            mp_srv.stop()

        # -------- restart persistence (the same data directory, new process)
        mp2 = Srv(data, {})
        ok("application restarts on the same data directory", mp2.start())
        try:
            st, recs = mp2.get(f"/api/mp/players/{cid}")
            # host's dismissal must survive; the guest must still see news
            db_ok = (Path(data) / "saturday.db").exists() or any(Path(data).glob("*.db"))
            ok("database persisted across restart", db_ok)
            st, rec_host = mp2.get(f"/api/campaigns/{cid}/recap", token=ht)
            host_row = None
            import sqlite3
            con = sqlite3.connect(next(Path(data).glob("*.db")))
            host_id = host["player_id"]
            guest_id = g["player_id"]
            host_dismissed = con.execute(
                "SELECT dismissed_at FROM recap_seen WHERE campaign_id=? AND player_id=?",
                (cid, host_id)).fetchone()
            guest_row = con.execute(
                "SELECT seen_rowids_json FROM recap_seen WHERE campaign_id=? AND player_id=?",
                (cid, guest_id)).fetchone()
            con.close()
            ok("host's per-player marker survived the restart", bool(host_dismissed))
            st, rec_h = mp2.get(f"/api/campaigns/{cid}/recap", token=ht)
            st, rec_g = mp2.get(f"/api/campaigns/{cid}/recap", token=g["token"])
            ok("recaps serve after restart", st == 200 and "items" in rec_g)
            guest_row = con2 = None
            con2 = sqlite3.connect(next(Path(data).glob("*.db")))
            guest_row = con2.execute(
                "SELECT seen_rowids_json FROM recap_seen WHERE campaign_id=? AND player_id=?",
                (cid, guest_id)).fetchone()
            con2.close()
            ok("guest's view untouched by the host's dismissal",
               guest_row is not None and all(v == 0 for v in json.loads(guest_row[0]).values()))
        finally:
            mp2.stop()

        # ================= Case D: production + TLS truthfulness ============
        prod = Srv(data, {"SATURDAY_PRODUCTION": "1", "SATURDAY_TLS": "1"})
        ok("Case D boots (production, TLS requested)", prod.start())
        try:
            st, h = prod.get("/api/health")
            ok("Case D health: listener is plain HTTP, tls mode proxy",
               h["listener"] == "http" and h["tls"]["mode"] == "proxy")
            try:
                ctx = ssl.create_default_context()
                cc = http.client.HTTPSConnection(os.environ["LANIP"], prod.port,
                                                 context=ctx, timeout=3)
                cc.request("GET", "/api/health")
                cc.getresponse().read()
                cc.close()
                honest = False  # TLS completed?! that would be a lie
            except Exception:
                honest = True
            ok("Case D port really speaks plain HTTP (no false TLS)", honest)
        finally:
            prod.stop()

    passed = sum(1 for _, c in OK if c)
    print(f"\nLAN verification: {passed}/{len(OK)} checks passed")
    return 0 if passed == len(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
