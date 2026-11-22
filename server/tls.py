"""Saturday Multiverse — optional LAN HTTPS support.

A local-certificate workflow for encrypted connections from other devices on
the same network. HTTPS is an explicit, opt-in mode; ordinary HTTP behavior
is untouched when it is not enabled.

Design:
- A small LOCAL certificate authority (CA) is created once in the user's
  data directory (never in the repository, never shipped in the release
  package, never distributed to clients — clients install only the CA's
  public certificate, and only when the user chooses to trust it).
- The server certificate carries Subject Alternative Names for localhost,
  the machine's LAN addresses and hostname, so browsers can complete normal
  certificate verification once the CA is trusted.
- Certificates can also be user-provided (SATURDAY_TLS_CERT / KEY).
- Diagnostics validate files, expiry, key/cert matching and SAN coverage —
  an invalid, expired or mismatched certificate is reported clearly instead
  of failing silently.
- No authentication, accounts or tokens are introduced by this module, and
  no CA is ever installed automatically.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import socket
import ssl
import stat
from pathlib import Path

from .config import DATA_DIR


def _data_dir() -> Path:
    """The live data directory (honors SATURDAY_DATA_DIR set after import)."""
    env = os.environ.get("SATURDAY_DATA_DIR", "").strip()
    return Path(env) if env else DATA_DIR


def certs_dir() -> Path:
    return _data_dir() / "certs"


def ca_cert() -> Path:
    return certs_dir() / "saturday-lan-ca.crt"


def ca_key() -> Path:
    return certs_dir() / "saturday-lan-ca.key"


def server_cert() -> Path:
    return certs_dir() / "saturday-server.crt"


def server_key() -> Path:
    return certs_dir() / "saturday-server.key"


def refresh() -> None:
    """Re-point the compatibility constants at the current data directory."""
    global CERTS_DIR, CA_CERT, CA_KEY, SERVER_CERT, SERVER_KEY
    CERTS_DIR = certs_dir()
    CA_CERT = ca_cert()
    CA_KEY = ca_key()
    SERVER_CERT = server_cert()
    SERVER_KEY = server_key()


CERTS_DIR = certs_dir()
CA_CERT = ca_cert()
CA_KEY = ca_key()
SERVER_CERT = server_cert()
SERVER_KEY = server_key()

CA_DAYS = 3650          # ~10 years for the local root
SERVER_DAYS = 825       # ~27 months; Safari caps server certs at 398/825 days
KEY_BITS = 2048

SERVER_CERT_DAYS_WARN = 30


def _require_crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        return x509, hashes, serialization, rsa, NameOID
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "HTTPS certificate generation needs the 'cryptography' package "
            "(pip install cryptography) — or provide your own certificate via "
            "SATURDAY_TLS_CERT and SATURDAY_TLS_KEY") from exc


def lan_addresses() -> list[str]:
    """The machine's LAN IPv4 addresses (best effort, no network traffic)."""
    out: list[str] = []
    # every non-loopback IPv4 address of this machine serves its own
    # certificate equally well, so all of them belong in the SANs
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = str(info[4][0])
            addr = ipaddress.ip_address(ip)
            if not addr.is_loopback and ip not in out:
                out.append(ip)
    except OSError:
        pass
    # one more common route: the default interface's primary address
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))  # no packets are delivered
            ip = probe.getsockname()[0]
            addr = ipaddress.ip_address(ip)
            if not addr.is_loopback and ip not in out:
                out.append(ip)
        finally:
            probe.close()
    except OSError:
        pass
    return out


def _cert_identities(cert_path: Path) -> dict:
    """The certificate's identities, strictly separated (hotfix 3).

    Returns {san_dns: [str], san_ips: [ipaddress], cn: str | None,
    has_san: bool, readable: bool}. The Common Name is diagnostics-only and
    is NEVER part of the SAN lists: a CN must not substitute for a Subject
    Alternative Name — modern browsers require real SAN identities. A
    DNSName that merely contains a textual IP address stays a DNS name and
    never satisfies an IPAddress identity."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    out = {"san_dns": [], "san_ips": [], "cn": None, "has_san": False,
           "readable": False}
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    except Exception:
        return out
    out["readable"] = True
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        out["san_dns"] = [str(v) for v in ext.value.get_values_for_type(x509.DNSName)]
        out["san_ips"] = list(ext.value.get_values_for_type(x509.IPAddress))
        out["has_san"] = True
    except x509.ExtensionNotFound:
        pass
    except Exception:  # malformed extension: treat as no usable SANs
        pass
    try:
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        out["cn"] = cn[0].value if cn else None
    except Exception:
        pass
    return out


def _cert_names(cert_path: Path) -> list[str]:
    """Backwards-compatible SAN-only name list (DNS names + IP addresses as
    text). The Common Name is deliberately excluded — it is diagnostics
    information only and never a validated identity."""
    ident = _cert_identities(cert_path)
    return ident["san_dns"] + [str(i) for i in ident["san_ips"]]


def generate(local_ips: list[str] | None = None, hostname: str | None = None,
             days: int = SERVER_DAYS, ca_days: int = CA_DAYS,
             force: bool = False) -> dict:
    """Create (or renew) the local CA and a server certificate covering the
    machine's LAN addresses. Returns the written paths and metadata."""
    x509, hashes, serialization, rsa, NameOID = _require_crypto()
    refresh()
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    if local_ips is None:
        local_ips = lan_addresses()
    if hostname is None:
        hostname = socket.gethostname() or "localhost"

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key_path, ca_cert_path = CA_KEY, CA_CERT
    if force or not (ca_cert_path.exists() and ca_key_path.exists()):
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
        ca_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Saturday Multiverse Local CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Home LAN"),
        ])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=ca_days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        ca_key_path.write_bytes(ca_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        _restrict(ca_key_path)

    # server key + certificate signed by the local CA
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    san_names: list[x509.GeneralName] = [x509.DNSName("localhost"),
                                         x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        san_names.append(x509.DNSName(hostname))
    except Exception:
        pass
    for ip in local_ips:
        try:
            san_names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    server_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, hostname or "Saturday Multiverse"),
    ])
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_encipherment=True, content_commitment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    SERVER_KEY.write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    SERVER_CERT.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    _restrict(SERVER_KEY)
    return {
        "ca_cert": str(ca_cert_path), "ca_key": str(ca_key_path),
        "server_cert": str(SERVER_CERT), "server_key": str(SERVER_KEY),
        "sans": [str(n.value) if hasattr(n, "value") else str(n) for n in san_names],
        "expires": (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d"),
    }


def _restrict(path: Path) -> None:
    """Private-key permissions where the OS supports them (POSIX)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass  # Windows: rely on the per-user profile directory ACLs


def client_facing_candidates() -> list[str]:
    """Names a browser on the LAN would actually use to reach this server:
    the explicitly configured HTTPS name (SATURDAY_TLS_NAME) first, then the
    machine's non-loopback addresses and hostname, then localhost. The bind
    address 0.0.0.0 is NOT a client-facing identity and is never a candidate."""
    out: list[str] = []
    configured = os.environ.get("SATURDAY_TLS_NAME", "").strip()
    if configured:
        out.append(configured)
    for ip in lan_addresses():
        if ip not in out:
            out.append(ip)
    try:
        host = socket.gethostname()
        if host and host not in out:
            out.append(host)
    except OSError:
        pass
    for n in ("localhost", "127.0.0.1"):
        if n not in out:
            out.append(n)
    return out


def days_left(cert_path: Path) -> int | None:
    from cryptography import x509
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
        expiry = cert.not_valid_after_utc
        return (expiry - datetime.datetime.now(datetime.timezone.utc)).days
    except Exception:
        return None


def _utc_validity(cert) -> tuple[datetime.datetime, datetime.datetime]:
    """The certificate's exact validity window as timezone-aware UTC datetimes
    (never truncated to whole days — a certificate near a validity boundary
    must not be misclassified)."""
    nb = getattr(cert, "not_valid_before_utc", None)
    na = getattr(cert, "not_valid_after_utc", None)
    if nb is None:
        nb = cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
    if na is None:
        na = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    return nb, na


def diagnose(cert_path: Path | str | None = None,
             key_path: Path | str | None = None,
             expect_ip: str | None = None) -> dict:
    """Certificate health check: existence, exact validity window, key match,
    and STRICT SAN coverage — real Subject Alternative Name identities only
    (the Common Name is reported separately as diagnostics information and
    never satisfies a SAN requirement). Returns {ok, problems[], warnings[],
    sans, cn, san_dns, san_ips, days_left, ...}."""
    refresh()
    cert_path = Path(cert_path or SERVER_CERT)
    key_path = Path(key_path or SERVER_KEY)
    problems: list[str] = []
    warnings: list[str] = []
    if not cert_path.exists() or not key_path.exists():
        problems.append(f"certificate files missing (expected {cert_path} and {key_path}); "
                        "run: python scripts/cert_setup.py generate")
        return {"ok": False, "problems": problems, "warnings": warnings,
                "sans": [], "san_dns": [], "san_ips": [], "cn": None,
                "has_san": False, "days_left": None}
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    ident = _cert_identities(cert_path)
    if not ident["readable"]:
        problems.append("certificate unreadable (not a valid PEM certificate)")
        return {"ok": False, "problems": problems, "warnings": warnings,
                "sans": [], "san_dns": [], "san_ips": [], "cn": ident["cn"],
                "has_san": False, "days_left": None}
    san_dns = ident["san_dns"]
    san_ips = ident["san_ips"]
    sans = san_dns + [str(i) for i in san_ips]
    left = days_left(cert_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    not_before, not_after = _utc_validity(cert)
    now = datetime.datetime.now(datetime.timezone.utc)
    if now < not_before:
        problems.append(
            "certificate NOT YET VALID — becomes valid "
            f"{not_before.strftime('%Y-%m-%d %H:%M:%S')} UTC; check the system clock "
            "or re-issue the certificate")
    elif now > not_after:
        problems.append(f"certificate EXPIRED {-left} day(s) ago — run: "
                        "python scripts/cert_setup.py renew")
    elif left is not None and left <= SERVER_CERT_DAYS_WARN:
        warnings.append(f"certificate expires in {left} day(s) — consider: "
                        "python scripts/cert_setup.py renew")
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if cert.public_key().public_numbers() != key.public_key().public_numbers():
            problems.append("private key does not match the certificate")
    except Exception as exc:
        problems.append(f"key/certificate check failed: {type(exc).__name__}")

    # strict identity coverage: real SAN entries only. A name that parses as
    # an IP address is satisfied ONLY by an IPAddress SAN — a DNSName carrying
    # the textual IP address is not an IP SAN (hotfix 3, browser semantics).
    # A DNS identity matches case-insensitively.
    def _covered(name: str) -> bool:
        try:
            ip = ipaddress.ip_address(name)
            return ip in san_ips
        except ValueError:
            return name.lower() in (d.lower() for d in san_dns)

    def _is_ip(name: str) -> bool:
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return False

    # client-facing coverage: which names browsers could actually use are in
    # the SANs, and which are missing (the bind address is not a candidate)
    candidates = client_facing_candidates()
    covered = [c for c in candidates if _covered(c)]
    missing = [c for c in candidates if not _covered(c)]
    configured = os.environ.get("SATURDAY_TLS_NAME", "").strip()
    if configured and not _covered(configured):
        problems.append(
            f"certificate does not cover the configured HTTPS name '{configured}' "
            f"(SANs: {', '.join(sans) or 'none'}); confirm the intended HTTPS "
            "hostname or renew with: python scripts/cert_setup.py renew --ip "
            + configured)
    if not ident["has_san"]:
        problems.append("certificate has no Subject Alternative Names; browsers "
                        "require SANs — renew with: python scripts/cert_setup.py renew")
    elif expect_ip and not _covered(expect_ip):
        problems.append(
            f"certificate does not cover {expect_ip} with a matching "
            f"{'IPAddress' if _is_ip(expect_ip) else 'DNS'} SAN "
            f"(SANs: {', '.join(sans) or 'none'}); "
            "renew after the LAN address changed: python scripts/cert_setup.py renew --ip "
            + expect_ip)
    elif not covered:
        problems.append(
            "certificate covers NONE of the client-facing names ("
            + ", ".join(candidates[:6]) + f"); SANs: {', '.join(sans) or 'none'}. "
            "Renew with: python scripts/cert_setup.py renew --ip <your LAN IP>")
    if sans and missing:
        warnings.append("not covered by this certificate: " + ", ".join(missing))
    key_mode = None
    try:
        key_mode = stat.S_IMODE(key_path.stat().st_mode)
        if key_mode & 0o077:
            warnings.append(f"private key permissions are {oct(key_mode)} (0600 recommended)")
    except OSError:
        pass
    return {"ok": not problems, "problems": problems, "warnings": warnings,
            "sans": sans, "san_dns": san_dns, "san_ips": [str(i) for i in san_ips],
            "cn": ident["cn"], "has_san": ident["has_san"],
            "days_left": left, "key_mode": key_mode,
            "covered": covered, "missing": missing}


def ssl_context(cert_path: Path | str | None = None,
                key_path: Path | str | None = None,
                expect_ip: str | None = None,
                strict: bool = True) -> ssl.SSLContext:
    """A TLS context for the chosen certificate.

    With strict=True (the default whenever HTTPS is enabled), clearly invalid
    configurations REJECT the certificate before the server ever accepts a
    connection: missing files, unreadable certificates, certificates whose
    validity has not begun yet or that have expired, key mismatches,
    certificates without real SAN identities (a Common Name is never a
    substitute), a certificate that does not cover the configured HTTPS name,
    or one that covers none of the client-facing names. Warnings (partial LAN
    coverage, loose key permissions) print but do not block — a certificate
    that some intended client can verify still serves. Error messages name
    the fix; private-key contents are never logged."""
    refresh()
    cert_path = Path(cert_path or SERVER_CERT)
    key_path = Path(key_path or SERVER_KEY)
    report = diagnose(cert_path, key_path, expect_ip=expect_ip)
    for w in report["warnings"]:
        print(f"[Saturday HTTPS] warning: {w}", flush=True)
    if report["problems"]:
        detail = "; ".join(report["problems"])
        if strict:
            raise RuntimeError(
                "HTTPS refused: the configured certificate is not usable. "
                + detail
                + "  (Set SATURDAY_TLS_CERT/SATURDAY_TLS_KEY to a valid pair, "
                "or fix with scripts/cert_setup.py renew / diagnose.)")
        for p in report["problems"]:
            print(f"[Saturday HTTPS] PROBLEM: {p}", flush=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    return ctx


def ca_fingerprint(ca_cert_path: Path | str | None = None) -> str | None:
    """SHA-256 fingerprint of the local CA certificate — lets a client verify,
    on its own screen, that the certificate it is about to trust is the one
    this machine generated."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    refresh()
    try:
        cert = x509.load_pem_x509_certificate(Path(ca_cert_path or CA_CERT).read_bytes())
        return cert.fingerprint(hashes.SHA256()).hex(":")
    except Exception:
        return None
