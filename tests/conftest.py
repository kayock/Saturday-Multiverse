import os
os.environ.setdefault("SATURDAY_RATE_MULT", "100")  # tests act fast; keep the limiter off their back
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolated, disposable data directory for the whole test session.
# Must be set BEFORE any server module is imported.
os.environ["SATURDAY_DATA_DIR"] = tempfile.mkdtemp(prefix="smtest_")


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    from server import config, db
    config.ensure_dirs()
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def _ai_disabled():
    """Every test starts with the AI Game Master off — tests opt in.
    Routing stays in manual mode so fleet discovery never runs during the suite.
    """
    from server import ai, routing
    ai.set_ai_config({"enabled": False})
    routing.set_routing({"mode": "manual", "escalation": "off",
                         "advanced_model": "", "advanced_base_url": ""})
    routing.clear_state()
    yield


@pytest.fixture()
def app():
    from server import config
    from server.app import create_app
    # the suite exercises many endpoints in one minute; lift the limiter
    old_api, old_ai = config.RATE_LIMIT_API, config.RATE_LIMIT_AI
    config.RATE_LIMIT_API = 100000
    config.RATE_LIMIT_AI = 100000
    application = create_app()
    application.testing = True
    yield application
    config.RATE_LIMIT_API, config.RATE_LIMIT_AI = old_api, old_ai


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def mock_gm_url():
    """Spin up the OpenAI-compatible mock Game Master on a random port."""
    import socket

    from scripts.mock_gm_server import serve
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = serve(port)
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()


@pytest.fixture()
def campaign():
    from server import gm

    cid = gm.create_campaign("Pytest Voyage", "living_shore", {
        "name": "Test Wanderer", "archetype": "sensitive",
        "specialty": "bind", "portrait_seed": "pytest-seed",
    })
    yield cid
    gm.archive_campaign(cid)

# Browser specs need Playwright + Chromium; CI runs them as a separate job.
collect_ignore_glob = ["browser/*"]
