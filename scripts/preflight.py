#!/usr/bin/env python3
"""Saturday Multiverse — preflight diagnostics.

Checks the local environment before playing: Python version, dependencies,
SQLite/FTS5 capability, data-directory writability, schema state, backups,
port availability, world-pack integrity, and (optionally) whether a configured
model endpoint answers. Read-only: never starts or installs a model, never
prints credentials, never mutates game state.

Usage:  python scripts/preflight.py [--port 8085]
Exit codes: 0 = all PASS, 1 = at least one FAIL, 2 = warnings only.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []  # (status, name, detail)


def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> bool:
    status = PASS if ok else (WARN if warn_only else FAIL)
    results.append((status, name, detail))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("SATURDAY_PORT", "8085")))
    args = ap.parse_args()

    print("Saturday Multiverse — preflight diagnostics\n" + "=" * 46)

    # 1. Python compatibility
    v = sys.version_info
    check("Python 3.10+", v >= (3, 10),
          f"{sys.version.split()[0]} at {sys.executable}")

    # 2. Required + optional dependencies
    check("flask installed", _importable("flask"),
          _version("flask") or "missing — pip install -r requirements.txt")
    waitress_ok = _importable("waitress")
    check("waitress (optional production WSGI)", waitress_ok,
          _version("waitress") or "not installed — dev server will be used",
          warn_only=True)
    pypdf_ok = _importable("pypdf")
    check("pypdf (optional PDF import)", pypdf_ok,
          _version("pypdf") or "not installed — PDF imports disabled",
          warn_only=True)

    # 3. SQLite + FTS5 capability
    check("sqlite3 module", True, sqlite3.sqlite_version)
    fts_ok = False
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
        fts_ok = True
    except Exception as exc:  # noqa: BLE001
        check("FTS5 full-text search", False,
              f"unavailable ({exc}); the app will start with LIKE search",
              warn_only=True)
    else:
        check("FTS5 full-text search", True)

    # 4. Data directory, schema, writability, backups
    from server import config, db
    config.ensure_dirs()
    check("data directory writable", os.access(config.DATA_DIR, os.W_OK),
          str(config.DATA_DIR))
    try:
        db.init_db()
        row = db.query_one("SELECT value FROM meta WHERE key='schema_version'")
        check("database opens", True,
              f"schema {row['value'] if row else '?'} at {config.DB_PATH}")
        degraded = not db.fts_available()
        if degraded:
            check("FTS5 in the app database", False, db.fts_warning() or "",
                  warn_only=True)
        n_backups = len(db.query("SELECT id FROM backups"))
        check("backup directory + history", config.BACKUP_DIR.exists(),
              f"{config.BACKUP_DIR} · {n_backups} backup(s) on record",
              warn_only=True)
    except Exception as exc:  # noqa: BLE001
        check("database opens", False, f"{type(exc).__name__}: {str(exc)[:120]}")

    # 5. Port availability
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", args.port))
        check(f"port {args.port} available", True)
    except OSError as exc:
        check(f"port {args.port} available", False, str(exc), warn_only=True)
    finally:
        s.close()

    # 6. World-pack integrity
    try:
        from server import worldpacks
        packs = worldpacks.list_packs()
        check("world packs valid", len(packs) > 0,
              ", ".join(p["id"] for p in packs[:6]) +
              (f" (+{len(packs) - 6} more)" if len(packs) > 6 else ""))
    except Exception as exc:  # noqa: BLE001
        check("world packs valid", False, str(exc)[:120])

    # 7. Configured model endpoint — REACHABILITY ONLY, never started/installed
    try:
        from server import ai
        cfg = ai.get_ai_config()
        if not cfg.get("enabled"):
            check("model endpoint", True,
                  "not configured — the Offline Storyteller will narrate "
                  "(clearly labeled in-game)", warn_only=True)
        else:
            base = (cfg.get("base_url") or "").rstrip("/")
            key = cfg.get("api_key") or ""
            probe = f"{base}/models" if base else ""
            reachable, detail = False, ""
            if probe:
                req = urllib.request.Request(probe,
                                             headers={"Authorization": f"Bearer {key}"
                                                      if key else ""})
                try:
                    with urllib.request.urlopen(req, timeout=4) as r:
                        reachable = r.status < 500
                        detail = f"answered HTTP {r.status}"
                except Exception as exc:  # noqa: BLE001
                    detail = f"unreachable ({type(exc).__name__})"
            model = cfg.get("model") or "?"
            # never print keys or full URLs with credentials
            shown = base.split("//")[-1].split("@")[-1]
            if reachable:
                check("model endpoint", True, f"{model} at {shown} — {detail}")
            else:
                check("model endpoint", False, f"{model} at {shown} — {detail}; "
                      "the Offline Storyteller keeps play going", warn_only=True)
    except Exception as exc:  # noqa: BLE001
        check("model endpoint", False, f"config error: {str(exc)[:100]}",
              warn_only=True)

    # 8. Optional HTTPS certificates (only when configured or already present)
    tls_env = os.environ.get("SATURDAY_TLS", "").strip() in ("1", "true", "yes")
    from server import tls as _tls
    _tls.refresh()
    cert_path = Path(os.environ.get("SATURDAY_TLS_CERT") or _tls.SERVER_CERT)
    if tls_env or cert_path.exists():
        try:
            report = _tls.diagnose(cert_path, expect_ip=config.HOST
                                   if config.HOST not in ("0.0.0.0", "") else None)
            for prob in report["problems"]:
                check("HTTPS certificate", False, prob)
            if report["ok"]:
                check("HTTPS certificate", True,
                      f"{report['days_left']} day(s) left; SANs: "
                      + (", ".join(report["sans"][:5]) or "none"))
            for w in report["warnings"]:
                results.append((WARN, "HTTPS certificate", w))
        except Exception as exc:  # noqa: BLE001
            check("HTTPS certificate", False, str(exc)[:120], warn_only=True)
    else:
        check("HTTPS (optional)", True,
              "not enabled — plain HTTP serving; enable with "
              "SATURDAY_TLS=1 after scripts/cert_setup.py generate", warn_only=True)

    print()
    fails = 0
    warns = 0
    for status, name, detail in results:
        mark = {"PASS": "✔", "WARN": "▲", "FAIL": "✘"}[status]
        line = f"{mark} {status:4s} {name}"
        if detail:
            line += f" — {detail}"
        print(line)
        if status == FAIL:
            fails += 1
        elif status == WARN:
            warns += 1
    print()
    if fails:
        print(f"result: FAIL ({fails} blocking, {warns} warning(s))")
        return 1
    if warns:
        print(f"result: OK with {warns} warning(s)")
        return 2
    print("result: all checks passed")
    return 0


def _importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _version(name: str) -> str:
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", "")
    except Exception:
        return ""


if __name__ == "__main__":
    sys.exit(main())
