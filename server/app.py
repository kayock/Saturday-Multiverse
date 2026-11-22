"""Saturday Multiverse — application entry point.

Run directly (python -m server.app or via run.sh / run.bat) to serve both
the API and the static browser client on one local port.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import threading

from flask import Flask, send_from_directory

from . import config, db


def create_app() -> Flask:
    config.ensure_dirs()
    db.init_db()

    app = Flask(__name__, static_folder=str(config.CLIENT_DIR), static_url_path="/")
    app.config["JSON_SORT_KEYS"] = False

    from .api import api
    app.register_blueprint(api)

    @app.get("/")
    def index():
        return send_from_directory(str(config.CLIENT_DIR), "index.html")

    @app.errorhandler(404)
    def not_found(_e):
        # API paths get JSON; everything else falls back to the client shell
        from flask import request, jsonify
        if request.path.startswith("/api/"):
            return jsonify({"error": "no such endpoint"}), 404
        return send_from_directory(str(config.CLIENT_DIR), "index.html")

    @app.errorhandler(500)
    def server_error(e):
        from flask import jsonify
        return jsonify({"error": f"internal error: {e}"}), 500

    return app


def _tls_enabled() -> bool:
    return os.environ.get("SATURDAY_TLS", "").strip() in ("1", "true", "yes")


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip() in ("1", "true", "yes")


def startup_plan() -> dict:
    """Resolve the ACTUAL serving mode from the environment. The startup
    banner, the health endpoint and generated links all report this — the
    advertised protocol always matches the listener protocol.

    Modes:
      off      plain HTTP (default; TLS disabled)
      direct   this process terminates TLS itself (dev server, optional
               SATURDAY_TLS_DEVSERVER=1 in production)
      proxy    production waitress listens on plain HTTP and TLS is
               terminated by a LOCAL reverse proxy in front of it; the
               externally visible HTTPS address is only advertised when the
               operator provides it via SATURDAY_TLS_PROXY_URL"""
    prod = _env_true("SATURDAY_PRODUCTION")
    tls = _tls_enabled()
    devserver = _env_true("SATURDAY_TLS_DEVSERVER")
    proxy_url = os.environ.get("SATURDAY_TLS_PROXY_URL", "").strip()
    if tls and (not prod or devserver):
        return {"mode": "direct", "listener": "https", "scheme": "https",
                "proxy_url": None}
    if prod and tls:
        return {"mode": "proxy", "listener": "http", "scheme": "http",
                "proxy_url": proxy_url or None}
    return {"mode": "off", "listener": "http", "scheme": "http", "proxy_url": None}


def _tls_context():
    """Build the TLS context from user-provided or managed certificates.

    Diagnostics run first and print clear problems (expired, mismatched,
    missing SANs) — a bad certificate is reported, not silently served."""
    from . import tls as tlsmod
    tlsmod.refresh()
    cert = os.environ.get("SATURDAY_TLS_CERT", "").strip()
    key = os.environ.get("SATURDAY_TLS_KEY", "").strip()
    if cert and key:
        paths = (Path(cert), Path(key))
    else:
        if not (tlsmod.SERVER_CERT.exists() and tlsmod.SERVER_KEY.exists()):
            raise RuntimeError(
                "HTTPS enabled (SATURDAY_TLS=1) but no certificate found. "
                "Create one:  python scripts/cert_setup.py generate   "
                "or provide SATURDAY_TLS_CERT / SATURDAY_TLS_KEY.")
        paths = (tlsmod.SERVER_CERT, tlsmod.SERVER_KEY)
    ctx = tlsmod.ssl_context(paths[0], paths[1],
                             expect_ip=config.HOST if config.HOST not in ("0.0.0.0", "") else None)
    return ctx


def main() -> None:
    # ensure the schema exists before any startup sweep touches the tables
    try:
        from . import db as _db
        _db.init_db()
    except Exception:
        logging.exception("Saturday Multiverse: startup schema check failed")
    # recover conversions interrupted by a previous process death
    try:
        from . import forge as _forge
        recovered = _forge.recover_stale_jobs()
        if recovered:
            logging.info("Saturday Multiverse: %d interrupted conversion job(s) marked resumable", recovered)
    except Exception:
        logging.exception("Saturday Multiverse: forge startup recovery failed")
    app = create_app()
    _start_watchdog()
    plan = startup_plan()
    url = f"{plan['scheme']}://{config.HOST}:{config.PORT}"
    print(f"""
  SATURDAY MULTIVERSE — the shore is listening.
  Open in your browser:  {url}
  Data directory:        {config.DATA_DIR}
  Stop with Ctrl+C.
""")
    if plan["mode"] == "proxy":
        print("  NOTE: this port serves PLAIN HTTP (waitress cannot terminate"
              " TLS itself).")
        print("        TLS happens at your local reverse proxy in front of"
              " this listener.")
        if plan["proxy_url"]:
            print(f"  External HTTPS address (terminated at the proxy):  {plan['proxy_url']}")
        else:
            print("        Set SATURDAY_TLS_PROXY_URL to display the external"
                  " HTTPS address here.")
            print("        For direct HTTPS from this process instead, set"
                  " SATURDAY_TLS_DEVSERVER=1.")
    if os.environ.get("SATURDAY_TRUST_PROXY", "").strip() in ("1", "true", "yes"):
        # Explicit opt-in: honor X-Forwarded-Proto/Host from a local reverse
        # proxy (e.g. Caddy terminating TLS in front of waitress). Forwarded
        # headers are trusted only when the user enables this.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
        print("  (reverse-proxy headers trusted: SATURDAY_TRUST_PROXY=1)")
    prod = _env_true("SATURDAY_PRODUCTION")
    if prod and plan["mode"] != "direct":
        # Production serving: waitress is a pure-Python, Windows- and
        # Linux-friendly WSGI server with real threading (SSE needs it).
        # In proxy mode this listener is plain HTTP by design — the banner
        # above says so; direct HTTPS requires SATURDAY_TLS_DEVSERVER=1.
        from waitress import serve
        print("  (production mode: waitress WSGI server)"
              + (" — plain HTTP listener; TLS at your reverse proxy"
                 if plan["mode"] == "proxy" else ""))
        serve(app, host=config.HOST, port=config.PORT, threads=12,
              channel_timeout=300)
    elif plan["mode"] == "direct":
        ctx = _tls_context()  # strict: invalid certificates fail before binding
        print("  (HTTPS enabled: this process terminates TLS with the"
              " configured certificate)")
        app.run(host=config.HOST, port=config.PORT, threaded=True, debug=False,
                ssl_context=ctx)
    else:
        app.run(host=config.HOST, port=config.PORT, threaded=True, debug=False)




def _watchdog_tick(busy: dict) -> None:
    """Run one sweep, keeping each subsystem's failures independent.

    Imports belong here rather than in a hidden exception: the production
    watchdog must resolve both multiplayer and combat modules before use.
    """
    from . import combat, forge, mp

    for label, sweep in (("multiplayer turns", mp.sweep_turns),
                         ("combat turns", combat.sweep_timeouts)):
        try:
            sweep()
        except Exception:
            logging.exception("Saturday Multiverse watchdog: %s sweep failed", label)

    try:
        # interrupted conversions (dead worker lease) become resumable failures
        forge.recover_stale_jobs()
        job = busy.get("job")
        if job is None or not job.is_alive():
            claimed = forge.claim_next_job("watchdog")
            if claimed:
                worker = threading.Thread(target=forge.run_job,
                                          args=(claimed, "watchdog"),
                                          name="sm-forge-job", daemon=True)
                busy["job"] = worker
                worker.start()
    except Exception:
        logging.exception("Saturday Multiverse watchdog: Forge job scheduling failed")


def _start_watchdog() -> None:
    """Background turn and queued-Forge-job sweeps in both launch modes.

    The launcher owns one daemon thread per process; no external service
    or new configuration is required.
    """
    import time as _time

    def _loop():
        busy = {"job": None}
        while True:
            _time.sleep(15)
            _watchdog_tick(busy)

    t = threading.Thread(target=_loop, name="sm-watchdog", daemon=True)
    t.start()


if __name__ == "__main__":
    main()
