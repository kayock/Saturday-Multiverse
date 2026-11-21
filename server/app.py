"""Saturday Multiverse — application entry point.

Run directly (python -m server.app or via run.sh / run.bat) to serve both
the API and the static browser client on one local port.
"""
from __future__ import annotations

import os

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


if __name__ == "__main__":
    main()
