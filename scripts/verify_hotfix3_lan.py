#!/usr/bin/env python3
"""Hotfix 3 live LAN verification: real servers, real certificates, real
clients. Extends verify_hotfix2_lan.py with the four hotfix-3 repair areas:

- explicit campfire sharing over direct HTTPS (shareable picker, exact
  grants, durable knowledge_shares ledger);
- strict HTTPS identities: a CN-only certificate and a not-yet-valid
  certificate are refused at startup (no verify=False anywhere — every
  client here verifies the chain against the local CA);
- the cert_setup CLI workflow (generate -> diagnose -> renew);
- a genuine hotfix2 -> hotfix3 save migration: a database created by the
  pristine hotfix2 tree reopens under this tree with every row intact and
  gains the additive knowledge_shares table.
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
                    try:
                        self.banner = self.p.stdout.read().decode(errors="replace")
                    except Exception:
                        self.banner = ""
                    print(self.banner[-800:])
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


def _issue_custom_cert(data: Path, name: str, *, sans=None, ips=None,
                       cn="localhost", not_before_days_ago=1, valid_days=800):
    """Craft a certificate with exact control over identities/validity."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from server import tls as tlsmod
    now = datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    ca_cert = x509.load_pem_x509_certificate(tlsmod.ca_cert().read_bytes())
    ca_key = serialization.load_pem_private_key(tlsmod.ca_key().read_bytes(),
                                                password=None)
    builder = (x509.CertificateBuilder()
               .subject_name(subj).issuer_name(ca_cert.subject)
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - datetime.timedelta(days=not_before_days_ago))
               .not_valid_after(now + datetime.timedelta(days=valid_days))
               .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                              critical=True))
    names = [x509.DNSName(d) for d in (sans or [])]
    names += [x509.IPAddress(ipaddress.ip_address(i)) for i in (ips or [])]
    if names:
        builder = builder.add_extension(x509.SubjectAlternativeName(names),
                                        critical=False)
    cert = builder.sign(ca_key, hashes.SHA256())
    cpath = data / name
    kpath = data / (name + ".key")
    cpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kpath.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return cpath, kpath


def _db_path(data: Path) -> Path:
    hits = list(Path(data).glob("*.db"))
    assert hits, "no sqlite database in the data directory"
    return hits[0]


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
    client_ip = lan_ips[0] if lan_ips else "127.0.0.1"
    os.environ["LANIP"] = client_ip
    print(f"client-facing address for this run: {client_ip}")

    with tempfile.TemporaryDirectory() as td:
        data = Path(td)
        # the parent process resolves certificate paths through server.tls too
        os.environ["SATURDAY_DATA_DIR"] = str(data)
        from server import tls as _tls
        _tls.refresh()

        # ------------- the real user workflow: cert_setup CLI ---------------
        env = dict(os.environ, SATURDAY_DATA_DIR=str(data))
        r = subprocess.run([sys.executable, "scripts/cert_setup.py", "generate"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True)
        ok("cert_setup.py generate", r.returncode == 0, r.stderr[-200:])
        r = subprocess.run([sys.executable, "scripts/cert_setup.py", "diagnose"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True)
        ok("cert_setup.py diagnose (clean bill)", r.returncode == 0
           and "days left" in r.stdout, r.stdout[-160:])
        r = subprocess.run([sys.executable, "scripts/cert_setup.py", "renew"],
                           cwd=str(ROOT), env=env, capture_output=True, text=True)
        ok("cert_setup.py renew", r.returncode == 0, r.stderr[-200:])

        # ------------- Case B: direct HTTPS + explicit campfire sharing -----
        tls_srv = Srv(data, {"SATURDAY_TLS": "1"})
        ok("Case B boots (direct HTTPS)", tls_srv.start())
        cid = None
        try:
            st, h = tls_srv.get("/api/health", tls=True)
            ok("health over HTTPS (CA-verified client)", st == 200 and h["ok"])
            ok("health reports the TRUE listener",
               h.get("listener") == "https" and h["tls"]["mode"] == "direct",
               json.dumps(h.get("tls", {})))
            st, c = tls_srv.post("/api/campaigns",
                                 {"name": "LAN Party HF3", "pack_id": "dracula",
                                  "character": {"name": "Hostess", "archetype": "occultist",
                                                "specialty": "bind"}}, tls=True)
            cid = c["campaign_id"]
            st, host = tls_srv.post("/api/mp/host",
                                    {"campaign_id": cid, "display_name": "Hostess"},
                                    tls=True)
            ht = host["token"]
            tls_srv.post("/api/mp/start", {"campaign_id": cid}, token=ht, tls=True)
            st, inv = tls_srv.post("/api/mp/invite", {"campaign_id": cid, "uses": 4},
                                   token=ht, tls=True)
            st, g = tls_srv.post("/api/mp/join",
                                 {"campaign_id": cid, "invite_token": inv["token"],
                                  "display_name": "Guest",
                                  "character": {"name": "Gwyn", "archetype": "doctor",
                                                "specialty": "lore"}}, tls=True)
            gt = g.get("token")
            ok("guest joins over HTTPS", st == 200 and gt)
            # a freshly joined guest holds no knowledge of their own yet
            st, sh_g = tls_srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                                   token=gt, tls=True)
            ok("the guest's picker holds nothing yet",
               st == 200 and sh_g.get("places") == [], json.dumps(sh_g)[:100])
            # move the party focus directly (the full propose/vote flow is
            # covered by the multiplayer test suite); the visit is recorded
            # for every traveling character
            st, tr = tls_srv.post(f"/api/campaigns/{cid}/travel",
                                  {"location_id": "whitby_harbour", "solo": True},
                                  token=ht, tls=True)
            ok("party travels over HTTPS (the visit is recorded)", st == 200, str(tr)[:80])
            st, sh = tls_srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                                 token=ht, tls=True)
            ok("shareable picker over HTTPS lists the visited place",
               st == 200 and any(p["ref"] == "whitby_harbour"
                                 for p in sh.get("places", [])),
               json.dumps(sh)[:120])
            st, mems = tls_srv.get(f"/api/campaigns/{cid}/campfire/shareable",
                                   token=ht, tls=True)
            rumor = next((m for m in mems.get("memories", [])), None)
            ok("a specific tavern rumor is selectable", rumor is not None)
            # plain story: shares NOTHING
            st, s1 = tls_srv.post(f"/api/campaigns/{cid}/campfire",
                                  {"kind": "story",
                                   "text": "The moon over the harbour was beautiful."},
                                  token=ht, tls=True)
            ok("plain story posts over HTTPS", st == 200 and "error" not in s1)
            # explicit share of exactly one rumor
            st, s2 = tls_srv.post(f"/api/campaigns/{cid}/campfire",
                                  {"kind": "memory", "text": "Heard at the tavern…",
                                   "share": [rumor["ref"]]}, token=ht, tls=True)
            ok("explicit share grants exactly the selected rumor",
               st == 200 and s2.get("share", {}).get("shared") == [rumor["ref"]],
               json.dumps(s2.get("share", {}))[:140])
            st, rec = tls_srv.get(f"/api/campaigns/{cid}/recap", token=gt, tls=True)
            ok("the guest's recap now carries the shared rumor",
               st == 200 and any(rumor["text"][:40] in i["text"] for i in rec["items"]),
               json.dumps(rec["items"])[:160])
            con = sqlite3.connect(_db_path(data))
            ledgers = con.execute(
                "SELECT ref, shared_by_player_id, ts FROM knowledge_shares "
                "WHERE campaign_id=?", (cid,)).fetchall()
            con.close()
            ok("the share ledger records exactly one grant, with who and when",
               len(ledgers) == 1 and ledgers[0][0] == rumor["ref"]
               and ledgers[0][1] == host["player_id"] and bool(ledgers[0][2]),
               str(ledgers))
            # SSE over direct HTTPS: ticket, then a live event-stream read
            st, tick = tls_srv.post(f"/api/mp/stream-ticket",
                                    {"campaign_id": cid}, token=ht, tls=True)
            sse_ok = False
            if st == 200 and tick.get("ticket"):
                conn = tls_srv.conn(tls=True)
                conn.request("GET", f"/api/mp/stream?ticket={tick['ticket']}&last_seq=0")
                resp = conn.getresponse()
                first = resp.read(120)          # the stream's first bytes
                conn.close()
                sse_ok = (resp.status == 200
                          and "text/event-stream" in resp.getheader("Content-Type", "")
                          and b"event" in first or b":" in first)
            ok("SSE streams over direct HTTPS", sse_ok,
               f"status={resp.status if st == 200 and tick.get('ticket') else st}")
        finally:
            tls_srv.stop()

        # ------------- restart: the share survives --------------------------
        srv2 = Srv(data, {"SATURDAY_TLS": "1"})
        ok("application restarts (HTTPS) on the same data directory", srv2.start())
        try:
            con = sqlite3.connect(_db_path(data))
            rows = con.execute("SELECT COUNT(*) FROM knowledge_shares").fetchone()[0]
            con.close()
            ok("knowledge_shares ledger survives the restart", rows == 1, str(rows))
            st, rec = srv2.get(f"/api/campaigns/{cid}/recap", token=gt, tls=True)
            ok("recaps serve after the restart", st == 200 and "items" in rec)
        finally:
            srv2.stop()

        # ------------- strict startup: CN-only certificate refused ----------
        cn_cert, cn_key = _issue_custom_cert(data, "cn-only.crt", cn="localhost",
                                             sans=None, ips=None)
        bad = Srv(data, {"SATURDAY_TLS": "1", "SATURDAY_TLS_CERT": str(cn_cert),
                         "SATURDAY_TLS_KEY": str(cn_key)})
        booted = bad.start()
        ok("CN-only certificate is REFUSED at startup", not booted
           and "san" in bad.banner.lower(), bad.banner[-200:])
        if bad.p and bad.p.poll() is None:
            bad.stop()

        # ------------- strict startup: not-yet-valid certificate refused ----
        ny_cert, ny_key = _issue_custom_cert(data, "not-yet.crt", cn="localhost",
                                             sans=["localhost"], ips=["127.0.0.1"],
                                             not_before_days_ago=-1)
        ny = Srv(data, {"SATURDAY_TLS": "1", "SATURDAY_TLS_CERT": str(ny_cert),
                        "SATURDAY_TLS_KEY": str(ny_key)})
        booted = ny.start()
        ok("not-yet-valid certificate is REFUSED at startup", not booted
           and "not yet valid" in ny.banner.lower(), ny.banner[-200:])
        if ny.p and ny.p.poll() is None:
            ny.stop()

        # ------------- Case A: plain HTTP still unaffected ------------------
        http_srv = Srv(data, {})
        ok("Case A boots (plain HTTP)", http_srv.start())
        try:
            st, h = http_srv.get("/api/health")
            ok("HTTP health truthful (no TLS claimed)",
               h["listener"] == "http" and h["tls"]["mode"] == "off")
            st, camps = http_srv.get("/api/campaigns")
            ok("existing campaign visible over LAN HTTP",
               st == 200 and any(x["name"] == "LAN Party HF3"
                                 for x in camps["campaigns"]))
            # hotfix 4: this campaign carries an active multiplayer session —
            # an unauthenticated picker request must be REFUSED (403), never
            # fall back to the campaign's character
            st, sh = http_srv.get(f"/api/campaigns/{cid}/campfire/shareable")
            ok("unauthenticated picker on a session campaign is refused (hotfix 4)",
               st == 403)
            # a genuine SOLO campaign needs no token: the session state alone
            # decides the fallback
            st, c2 = http_srv.post("/api/campaigns",
                                   {"name": "LAN Solo HF4", "pack_id": "dracula",
                                    "character": {"name": "Loner", "archetype": "occultist",
                                                  "specialty": "bind"}})
            st, sh2 = http_srv.get(f"/api/campaigns/{c2['campaign_id']}/campfire/shareable")
            ok("solo shareable answers over plain HTTP without a token",
               st == 200 and "places" in sh2, json.dumps(sh2)[:80])
        finally:
            http_srv.stop()

        # ------------- Case D: production + TLS truthfulness ----------------
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

        # ------------- genuine hotfix2 -> hotfix3 save migration ------------
        hf2_zip = os.environ.get("SM_HOTFIX2_ZIP", "")
        if hf2_zip and Path(hf2_zip).exists():
            with tempfile.TemporaryDirectory() as h2d:
                import zipfile
                with zipfile.ZipFile(hf2_zip) as zf:
                    zf.extractall(h2d)
                h2root = Path(h2d) / "saturday-multiverse"
                mig_data = Path(td) / "migration-save"
                mig_data.mkdir()
                mkenv = dict(os.environ, SATURDAY_DATA_DIR=str(mig_data),
                             SATURDAY_RATE_MULT="100")
                snippet = ("import sys; sys.path.insert(0, '.');"
                           "from server import gm, db;"
                           "db.init_db();"
                           "cid = gm.create_campaign('HF2 Legacy Save', 'dracula',"
                           "{'name': 'Ester', 'archetype': 'occultist', 'specialty': 'bind'});"
                           "db.log_event(cid, 'combat_victory', {'monster': 'wolf'});"
                           "print(cid)")
                r = subprocess.run([sys.executable, "-c", snippet], cwd=str(h2root),
                                   env=mkenv, capture_output=True, text=True)
                mig_cid = r.stdout.strip().splitlines()[-1] if r.returncode == 0 else ""
                ok("hotfix2 tree creates a legacy save", r.returncode == 0 and mig_cid,
                   r.stderr[-160:])
                mig = Srv(mig_data, {})
                ok("hotfix3 tree opens the hotfix2 save (migration)", mig.start())
                try:
                    st, camps = mig.get("/api/campaigns")
                    ok("migrated save lists its campaign",
                       st == 200 and any(x["id"] == mig_cid for x in camps["campaigns"]))
                    st, v = mig.get(f"/api/campaigns/{mig_cid}")
                    ok("migrated campaign state intact (turn, victory event)",
                       st == 200 and v.get("turn") is not None)
                    con = sqlite3.connect(_db_path(mig_data))
                    tables = {t[0] for t in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    evs = con.execute("SELECT COUNT(*) FROM events WHERE campaign_id=?",
                                      (mig_cid,)).fetchone()[0]
                    ver = con.execute(
                        "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
                    con.close()
                    ok("additive knowledge_shares table present after migration",
                       "knowledge_shares" in tables)
                    ok("existing rows preserved (events intact)",
                       evs >= 2, f"{evs} events")
                    ok("schema version still v8 (additive, no rewrite)",
                       ver == "saturday.core.v8", ver)
                finally:
                    mig.stop()
        else:
            print("  SKIP hotfix2->hotfix3 migration (set SM_HOTFIX2_ZIP)")

    passed = sum(1 for _, c in OK if c)
    print(f"\nLAN verification: {passed}/{len(OK)} checks passed")
    return 0 if passed == len(OK) else 1


if __name__ == "__main__":
    sys.exit(main())
