"""Saturday Multiverse — application entry point.

Run directly (python -m server.app or via run.sh / run.bat) to serve both
the API and the static browser client on one local port.
"""
from __future__ import annotations

import logging
import os
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


def main() -> None:
    app = create_app()
    _start_watchdog()
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"""
  SATURDAY MULTIVERSE — the shore is listening.
  Open in your browser:  {url}
  Data directory:        {config.DATA_DIR}
  Stop with Ctrl+C.
""")
    if os.environ.get("SATURDAY_PRODUCTION", "").strip() in ("1", "true", "yes"):
        # Production serving: waitress is a pure-Python, Windows- and
        # Linux-friendly WSGI server with real threading (SSE needs it).
        # Still put a TLS-terminating reverse proxy in front for remote play.
        from waitress import serve
        print("  (production mode: waitress WSGI server)")
        serve(app, host=config.HOST, port=config.PORT, threads=12,
              channel_timeout=300)
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
        job = busy.get("job")
        if job is None or not job.is_alive():
            row = db.query_one("SELECT id FROM forge_jobs WHERE status='queued'"
                               " AND cancel=0 ORDER BY created_at LIMIT 1")
            if row:
                worker = threading.Thread(target=forge.run_job, args=(row["id"],),
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
