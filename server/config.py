"""Saturday Multiverse — server configuration.

All paths derive from the project root so the app runs portably from any
directory. User data (database, backups, exports) lives in a writable data
directory that is separate from the code tree by default, configurable with
the SATURDAY_DATA_DIR environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Saturday Multiverse"
APP_VERSION = "0.1.0-milestone1"
SCHEMA_VERSION = "saturday.core.v1"

# Repository root: server/config.py -> server/ -> project root
ROOT_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT_DIR / "server"
CLIENT_DIR = ROOT_DIR / "client"
WORLDPACKS_DIR = ROOT_DIR / "worldpacks"

# Writable user-data directory (created on demand, kept out of git).
DATA_DIR = Path(os.environ.get("SATURDAY_DATA_DIR", ROOT_DIR / "userdata")).resolve()
DB_PATH = DATA_DIR / "saturday.db"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"

# Network defaults: bind to localhost only unless explicitly reconfigured.
# Multiplayer hosting (Milestone 3) is what justifies a wider bind.
HOST = os.environ.get("SATURDAY_HOST", "127.0.0.1")
PORT = int(os.environ.get("SATURDAY_PORT", "8788"))

# Optional shared-secret gate for non-localhost hosting. Empty = open
# (fine for a purely local single-player machine).
HOST_TOKEN = os.environ.get("SATURDAY_TOKEN", "")

# Rate limits (requests per minute per client IP).
RATE_LIMIT_API = 120
RATE_LIMIT_AI = 30

# AI request defaults (per-provider values live in settings; these are the
# safety rails applied to every outgoing call).
AI_TIMEOUT_SECONDS = 120
AI_MAX_RETRIES = 1


def ensure_dirs() -> None:
    """Create the writable directories on demand."""
    for d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
