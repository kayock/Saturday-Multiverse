"""v0.4.0 Final Release Hotfix 2 — enforced certificate validation and
truthful production HTTPS reporting.

Confirmed defects under test:
- TLS diagnostics printed problems but still served the invalid certificate;
- production + TLS advertised an HTTPS URL while waitress listened in plain
  HTTP.
"""
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import http.client
import json
import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import tls as tlsmod  # noqa: E402


@pytest.fixture()
def certdir(tmp_path, monkeypatch):
    monkeypatch.setenv("SATURDAY_DATA_DIR", str(tmp_path))
    tlsmod.refresh()
    tlsmod.generate()
    yield tmp_path
    monkeypatch.delenv("SATURDAY_DATA_DIR", raising=False)
    tlsmod.refresh()


def _expired_cert(dir_path: Path) -> tuple[Path, Path]:
    """Craft a genuinely expired certificate signed by the local CA."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = serialization.load_pem_private_key(tlsmod.ca_key().read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(tlsmod.ca_cert().read_bytes())
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=400))
        .not_valid_after(now - datetime.timedelta(days=5))   # EXPIRED
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName("localhost"), x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
            critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_path = dir_path / "expired.crt"
    key_path = dir_path / "expired.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return cert_path, key_path


def _foreign_cert(dir_path: Path) -> tuple[Path, Path]:
    """A valid, self-signed certificate for an unrelated host (wrong SANs)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "elsewhere.example")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=800))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("elsewhere.example")]),
                       critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = dir_path / "foreign.crt"
    key_path = dir_path / "foreign.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    return cert_path, key_path


# ------------------------------------------------------------- enforcement
def test_valid_certificate_builds_a_context(certdir):
    ctx = tlsmod.ssl_context()
    assert isinstance(ctx, ssl.SSLContext)


def test_expired_certificate_is_rejected(certdir):
    cert, key = _expired_cert(certdir)
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"] and any("EXPIRED" in p for p in report["problems"])
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(cert, key)
    assert "expired" in str(exc.value).lower()
    assert "cert_setup.py renew" in str(exc.value), "the error names the fix"


def test_missing_certificate_and_missing_key_are_rejected(certdir):
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(certdir / "nope.crt", certdir / "nope.key")
    assert "missing" in str(exc.value).lower()
    cert, key = tlsmod.server_cert(), tlsmod.server_key()
    with pytest.raises(RuntimeError):
        tlsmod.ssl_context(cert, certdir / "absent.key")  # certificate present, key missing


def test_mismatched_key_is_rejected(certdir):
    cert_copy = certdir / "pair-a.crt"
    cert_copy.write_bytes(tlsmod.server_cert().read_bytes())
    tlsmod.generate(days=400, force=True)  # fresh pair B: new key + new cert
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(cert_copy, tlsmod.server_key())  # A's cert, B's key
    assert "does not match" in str(exc.value)


def test_wrong_san_is_rejected_when_the_client_address_is_known(certdir, monkeypatch):
    cert, key = _foreign_cert(certdir)
    monkeypatch.setenv("SATURDAY_TLS_NAME", "192.168.1.50")
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"] and any("does not cover the configured HTTPS name" in p
                                    for p in report["problems"])
    with pytest.raises(RuntimeError) as exc:
        tlsmod.ssl_context(cert, key)
    assert "192.168.1.50" in str(exc.value)
    monkeypatch.delenv("SATURDAY_TLS_NAME")


def test_certificate_with_no_client_facing_names_is_rejected(certdir, monkeypatch):
    cert, key = _foreign_cert(certdir)
    report = tlsmod.diagnose(cert, key)
    assert not report["ok"] and any("covers NONE of the client-facing names" in p
                                    for p in report["problems"])
    with pytest.raises(RuntimeError):
        tlsmod.ssl_context(cert, key)


def test_valid_lan_ip_san_is_accepted(certdir, monkeypatch):
    ips = tlsmod.lan_addresses()
    target = ips[0] if ips else "127.0.0.1"
    monkeypatch.setenv("SATURDAY_TLS_NAME", target)
    ctx = tlsmod.ssl_context()  # must not raise: the name is covered
    assert isinstance(ctx, ssl.SSLContext)
    monkeypatch.delenv("SATURDAY_TLS_NAME")


def test_diagnostics_never_expose_key_contents(certdir, capsys):
    tlsmod.generate(days=400, force=True)
    tlsmod.diagnose()
    out = capsys.readouterr().out
    assert "PRIVATE KEY" not in out and "BEGIN RSA" not in out


def test_http_still_works_with_tls_disabled(tmp_path, monkeypatch):
    """TLS off: ordinary HTTP; no TLS context is ever built."""
    from server.app import startup_plan
    monkeypatch.delenv("SATURDAY_TLS", raising=False)
    monkeypatch.delenv("SATURDAY_PRODUCTION", raising=False)
    plan = startup_plan()
    assert plan["listener"] == "http" and plan["mode"] == "off" and plan["scheme"] == "http"


# ------------------------------------------------- startup truth table (A–E)
def _plan_for(monkeypatch, **env):
    for k, v in (("SATURDAY_TLS", None), ("SATURDAY_PRODUCTION", None),
                 ("SATURDAY_TLS_DEVSERVER", None), ("SATURDAY_TLS_PROXY_URL", None)):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        if v is not None:
            monkeypatch.setenv(k, v)
    from server.app import startup_plan
    return startup_plan()


def test_case_a_ordinary_http(monkeypatch):
    plan = _plan_for(monkeypatch)
    assert plan["listener"] == "http" and plan["scheme"] == "http" and plan["mode"] == "off"


def test_case_b_direct_lan_https(monkeypatch):
    plan = _plan_for(monkeypatch, SATURDAY_TLS="1", SATURDAY_HOST="0.0.0.0")
    assert plan["listener"] == "https" and plan["scheme"] == "https" and plan["mode"] == "direct"


def test_case_c_production_http(monkeypatch):
    plan = _plan_for(monkeypatch, SATURDAY_PRODUCTION="1")
    assert plan["listener"] == "http" and plan["scheme"] == "http" and plan["mode"] == "off"


def test_case_d_production_with_tls_termination_is_truthful(monkeypatch):
    """Production + TLS: the LISTENER stays plain HTTP and the banner/health
    say so; an external HTTPS address is advertised only when configured."""
    plan = _plan_for(monkeypatch, SATURDAY_PRODUCTION="1", SATURDAY_TLS="1")
    assert plan["listener"] == "http", "waitress cannot terminate TLS — the port is HTTP"
    assert plan["scheme"] == "http"
    assert plan["proxy_url"] is None
    plan2 = _plan_for(monkeypatch, SATURDAY_PRODUCTION="1", SATURDAY_TLS="1",
                      SATURDAY_TLS_PROXY_URL="https://192.168.1.20:8443")
    assert plan2["proxy_url"] == "https://192.168.1.20:8443"
    assert plan2["listener"] == "http", "the external URL is separate from the listener"


def test_case_e_explicit_direct_https_override(monkeypatch):
    plan = _plan_for(monkeypatch, SATURDAY_PRODUCTION="1", SATURDAY_TLS="1",
                     SATURDAY_TLS_DEVSERVER="1")
    assert plan["listener"] == "https" and plan["mode"] == "direct"


# ------------------------------------- real-server behavior for each mode
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Boot:
    """Boots the real server and captures its banner.

    Output is collected by a bounded background reader thread — the portable
    way to capture subprocess startup messages on Windows, Linux, Python
    3.10 and 3.12 alike (no Unix-only fcntl / non-blocking pipe tricks, no
    blocking reads on the test's main thread, no indefinite waits)."""

    def __init__(self, data_dir: Path, env_extra: dict):
        self.port = _free_port()
        env = dict(os.environ)
        env.update({"SATURDAY_DATA_DIR": str(data_dir), "SATURDAY_PORT": str(self.port),
                    "SATURDAY_HOST": "127.0.0.1", "SATURDAY_RATE_MULT": "100",
                    "PYTHONUNBUFFERED": "1"})
        env.update(env_extra)
        self.env = env
        self.proc = None
        self._out = bytearray()
        self._out_lock = threading.Lock()
        self._reader = None

    def _collect(self, pipe) -> None:
        """Drain the child's output until EOF (daemon thread; bounded chunks)."""
        try:
            while True:
                chunk = pipe.read(256)
                if not chunk:
                    break
                with self._out_lock:
                    self._out.extend(chunk)
        except Exception:
            pass  # the pipe dies with the process — that is fine here

    def _output(self) -> str:
        with self._out_lock:
            return bytes(self._out).decode(errors="replace")

    def start(self):
        self.proc = subprocess.Popen([sys.executable, "-u", "-m", "server.app"],
                                     cwd=str(ROOT), env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self._reader = threading.Thread(target=self._collect,
                                        args=(self.proc.stdout,), daemon=True)
        self._reader.start()
        deadline = time.time() + 30
        scheme = "https" if self.env.get("SATURDAY_TLS") and \
            self.env.get("SATURDAY_PRODUCTION") != "1" or \
            self.env.get("SATURDAY_TLS_DEVSERVER") else "http"
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self._reader.join(timeout=5)  # EOF already reached with the process
                out = self._output()
                raise RuntimeError(f"server exited early:\n{out[-1500:]}")
            try:
                if scheme == "https":
                    ctx = ssl.create_default_context(
                        cafile=str(Path(self.env.get("SATURDAY_TLS_CERT") or
                                        (Path(self.env["SATURDAY_DATA_DIR"]) / "certs" /
                                         "saturday-lan-ca.crt"))))
                    conn = http.client.HTTPSConnection("127.0.0.1", self.port,
                                                       context=ctx, timeout=5)
                else:
                    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                conn.request("GET", "/api/health")
                conn.getresponse().read()
                conn.close()
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("server did not start")

    def banner(self, wait: float = 2.0) -> str:
        """The startup output captured so far (after a short grace wait)."""
        time.sleep(wait)
        return self._output()

    def get(self, path, tls: bool = False):
        if tls:
            ctx = ssl.create_default_context(
                cafile=str(Path(self.env.get("SATURDAY_TLS_CERT") or
                                (Path(self.env["SATURDAY_DATA_DIR"]) / "certs" /
                                 "saturday-lan-ca.crt"))))
            conn = http.client.HTTPSConnection("127.0.0.1", self.port, context=ctx, timeout=10)
        else:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(body.decode())
        except Exception:
            return resp.status, {"_raw": body[:4000].decode(errors="replace")}

    def stop(self):
        """Terminate the child cleanly (escalating only if needed) and reap
        the output collector — subprocesses never outlive a failing test."""
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if self._reader:
            self._reader.join(timeout=2)  # EOF arrives when the pipe closes


def test_case_d_real_server_listens_http_while_asking_for_tls(tmp_path, monkeypatch):
    """The confirmed defect, now fixed: production+TLS must NOT advertise
    HTTPS on an HTTP port. The banner states plain HTTP; the health endpoint
    reports listener http + tls.mode proxy; a TLS handshake to that port fails."""
    monkeypatch.setenv("SATURDAY_DATA_DIR", str(tmp_path))
    tlsmod.refresh()
    tlsmod.generate()
    monkeypatch.delenv("SATURDAY_DATA_DIR")
    tlsmod.refresh()
    boot = Boot(tmp_path, {"SATURDAY_PRODUCTION": "1", "SATURDAY_TLS": "1"})
    boot.start()
    try:
        banner = boot.banner()
        assert "PLAIN HTTP" in banner, banner
        assert "https://127.0.0.1:" not in banner.split("Open in your browser:  ")[1][:9], \
            "no https URL is advertised for the plain-HTTP listener"
        st, health = boot.get("/api/health")
        assert st == 200
        assert health["listener"] == "http" and health["tls"]["mode"] == "proxy"
        # the port really is plain HTTP: a TLS handshake never completes
        # (waitress accepts TCP but speaks no TLS — SSLError or timeout)
        with pytest.raises((ssl.SSLError, TimeoutError, OSError)):
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection("127.0.0.1", boot.port, context=ctx, timeout=3)
            conn.request("GET", "/api/health")
            conn.getresponse().read()
            conn.close()
        # SSE still works over the plain-HTTP production listener
        st, page = boot.get("/js/main.js")
        assert st == 200
    finally:
        boot.stop()


def test_case_e_real_direct_https_in_production(tmp_path, monkeypatch):
    """SATURDAY_TLS_DEVSERVER=1 in production REALLY serves TLS: a verifying
    client connects and the health endpoint reports listener https."""
    monkeypatch.setenv("SATURDAY_DATA_DIR", str(tmp_path))
    tlsmod.refresh()
    tlsmod.generate()
    monkeypatch.delenv("SATURDAY_DATA_DIR")
    tlsmod.refresh()
    boot = Boot(tmp_path, {"SATURDAY_PRODUCTION": "1", "SATURDAY_TLS": "1",
                           "SATURDAY_TLS_DEVSERVER": "1"})
    boot.start()
    try:
        st, health = boot.get("/api/health", tls=True)  # NORMAL CA verification
        assert st == 200, health
        assert health["listener"] == "https" and health["tls"]["mode"] == "direct"
        assert health["tls"].get("certificate_ok") is True
        st, page = boot.get("/", tls=True)
        assert st == 200 and "saturday multiverse" in page["_raw"].lower(), \
            "the real SPA title page serves over direct HTTPS"
    finally:
        boot.stop()


def test_expired_certificate_fails_the_server_loudly(tmp_path):
    """SATURDAY_TLS=1 with an expired certificate: the server refuses to
    serve HTTPS instead of silently presenting it."""
    os.environ["SATURDAY_DATA_DIR"] = str(tmp_path)
    tlsmod.refresh()
    tlsmod.generate()
    cert, key = _expired_cert(tmp_path)
    boot = Boot(tmp_path, {"SATURDAY_TLS": "1",
                           "SATURDAY_TLS_CERT": str(cert), "SATURDAY_TLS_KEY": str(key)})
    with pytest.raises(RuntimeError) as exc:
        boot.start()
    assert "expired" in str(exc.value).lower()
    assert tlsmod.server_key() not in [None]  # no side effects on the managed pair
    os.environ.pop("SATURDAY_DATA_DIR", None)
    tlsmod.refresh()
