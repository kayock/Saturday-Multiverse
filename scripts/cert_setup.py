#!/usr/bin/env python3
"""Saturday Multiverse — HTTPS certificate setup for a home LAN.

Commands:
  generate   Create the local CA + a server certificate with SANs for this
             machine's LAN addresses (idempotent; skips what already exists).
  renew      Regenerate the server certificate (same local CA) — use this
             after expiry or when the LAN hostname/IP changed.
  diagnose   Check the current certificate: expiry, key match, SAN coverage,
             key permissions. Exit code 1 on problems.
  show       Print the paths, SAN coverage and the CA fingerprint (the value
             a client can compare before choosing to trust it).

User-provided certificates: set SATURDAY_TLS_CERT and SATURDAY_TLS_KEY to
existing PEM files instead of generating anything.

The CA private key stays on the hosting computer. Clients install ONLY the
CA's public certificate, and only when the user deliberately chooses to
(see docs/DEPLOYMENT.md). Nothing is ever installed automatically.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import tls  # noqa: E402


def _env_cert_paths() -> tuple[Path, Path] | None:
    cert = os.environ.get("SATURDAY_TLS_CERT", "").strip()
    key = os.environ.get("SATURDAY_TLS_KEY", "").strip()
    if cert and key:
        return Path(cert), Path(key)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="create the local CA + server certificate")
    g.add_argument("--days", type=int, default=tls.SERVER_DAYS)
    g.add_argument("--force", action="store_true", help="recreate the CA as well")
    g.add_argument("--ip", action="append", default=None,
                   help="extra LAN IP to cover (repeatable)")
    r = sub.add_parser("renew", help="regenerate the server certificate")
    r.add_argument("--days", type=int, default=tls.SERVER_DAYS)
    d = sub.add_parser("diagnose", help="validate the current certificate")
    d.add_argument("--expect-ip", default=None)
    sub.add_parser("show", help="print paths, SANs, expiry and CA fingerprint")
    args = ap.parse_args()
    tls.refresh()

    if args.cmd == "generate":
        user = _env_cert_paths()
        if user:
            print(f"using user-provided certificate: {user[0]}\n"
                  "nothing was generated (SATURDAY_TLS_CERT/SATURDAY_TLS_KEY are set)")
            return 0
        info = tls.generate(days=args.days, force=args.force, local_ips=args.ip)
        print("local CA created/verified:", info["ca_cert"])
        print("server certificate:", info["server_cert"])
        print("server key:", info["server_key"], "(permissions restricted where supported)")
        print("subject alternative names:", ", ".join(info["sans"]))
        print("expires:", info["expires"])
        fp = tls.ca_fingerprint()
        if fp:
            print("CA fingerprint (SHA-256):", fp)
        print("\nHTTPS is off until you enable it:")
        print("  SATURDAY_TLS=1 SATURDAY_HOST=0.0.0.0 python -m server.app")
        print("Then, to make browsers trust it, install the CA CERTIFICATE "
              "(not the key) on each client — see docs/DEPLOYMENT.md.")
        return 0

    if args.cmd == "renew":
        user = _env_cert_paths()
        if user:
            print("user-provided certificates are managed outside this tool")
            return 0
        info = tls.generate(days=args.days, force=False)  # same CA, fresh server cert
        print("server certificate renewed (same local CA):", info["server_cert"])
        print("subject alternative names:", ", ".join(info["sans"]))
        print("expires:", info["expires"])
        return 0

    if args.cmd == "diagnose":
        user = _env_cert_paths()
        cert, key = user if user else (tls.SERVER_CERT, tls.SERVER_KEY)
        report = tls.diagnose(cert, key, expect_ip=args.expect_ip)
        print("certificate:", cert)
        print("key:", key)
        print("subject alternative names:", ", ".join(report["sans"]) or "(none)")
        print("days left:", report["days_left"])
        if "covered" in report:
            print("covers client-facing names:", ", ".join(report["covered"]) or "(none)")
            if report.get("missing"):
                print("NOT covered:", ", ".join(report["missing"]))
        for p in report["problems"]:
            print("PROBLEM:", p)
        for w in report["warnings"]:
            print("warning:", w)
        print("result:", "OK" if report["ok"] else "FAIL")
        return 0 if report["ok"] else 1

    if args.cmd == "show":
        user = _env_cert_paths()
        cert, key = user if user else (tls.SERVER_CERT, tls.SERVER_KEY)
        report = tls.diagnose(cert, key)
        print("certificate:", cert)
        print("subject alternative names:", ", ".join(report["sans"]) or "(none)")
        print("days left:", report["days_left"])
        fp = tls.ca_fingerprint()
        if fp:
            print("CA certificate (to install on clients):", tls.CA_CERT)
            print("CA fingerprint (SHA-256):", fp)
        print("server key (never distribute):", key)
        for w in report["warnings"]:
            print("warning:", w)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
