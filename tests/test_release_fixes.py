"""v0.3.6 hotfix regressions: entry-point/watchdog and Workshop privacy."""
import json
import sys
from types import SimpleNamespace

import pytest

from server import db, forge
from server.db import jdumps, jloads


def test_workshop_proposal_secret_never_leaks_in_ops_or_note():
    created = forge.create_collab("Privacy Regression", "creator-1", "Creator")
    draft_id = created["draft_id"]
    secret = "ONLY_AUTHOR_ONE_KNOWS_THE_VAULT_CODE"
    forge.contrib_propose(draft_id, "author-1", "Author One", [
        {"op": "add", "path": "intro_quests", "value": {"id": "q", "title": "Public quest"}},
        {"op": "add", "path": "gm_secrets", "value": secret},
    ], note=f"Reveal: {secret}")

    outsider = forge.collab_view(draft_id, "author-2")
    assert secret not in json.dumps(outsider), "private proposal leaked via operations or note"
    assert outsider["proposals"][0]["ops"][0]["op"] == "redacted"
    assert "gm_secrets" not in outsider["pack"].get("secret_authors", {})

    creator = forge.collab_view(draft_id, "creator-1")
    author = forge.collab_view(draft_id, "author-1")
    assert secret in json.dumps(creator)
    assert secret in json.dumps(author)


def test_workshop_nested_secret_and_unattributed_secret_hidden():
    created = forge.create_collab("Nested Secrets", "creator-2", "Creator")
    draft_id = created["draft_id"]
    secret = "NESTED_SECRET_DO_NOT_REVEAL"
    forge.contrib_propose(draft_id, "author-3", "Author Three", [
        {"op": "set", "path": "nested.gm_secrets.0", "value": secret},
    ], note=f"private {secret}")

    row = db.query_one("SELECT pack_json FROM forge_drafts WHERE id=?", (draft_id,))
    pack = jloads(row["pack_json"], {})
    pack["gm_secrets"].append("UNATTRIBUTED_GM_SECRET")
    db.execute("UPDATE forge_drafts SET pack_json=? WHERE id=?", (jdumps(pack), draft_id))

    outsider = forge.collab_view(draft_id, "author-4")
    assert secret not in json.dumps(outsider)
    assert "UNATTRIBUTED_GM_SECRET" not in json.dumps(outsider)
    assert "UNATTRIBUTED_GM_SECRET" in json.dumps(forge.collab_view(draft_id, "creator-2"))


@pytest.mark.parametrize("production", [False, True])
def test_launcher_calls_main_and_starts_watchdog(monkeypatch, production):
    pytest.importorskip("flask")
    from server import app as entry
    calls = []
    application = SimpleNamespace(run=lambda **kw: calls.append(("development", kw)))
    monkeypatch.setattr(entry, "create_app", lambda: application)
    monkeypatch.setattr(entry, "_start_watchdog", lambda: calls.append(("watchdog", {})))
    monkeypatch.setenv("SATURDAY_PRODUCTION", "1" if production else "0")
    monkeypatch.setitem(sys.modules, "waitress", SimpleNamespace(
        serve=lambda app, **kw: calls.append(("production", kw))))
    entry.main()
    assert calls[0][0] == "watchdog"
    assert calls[1][0] == ("production" if production else "development")


def test_watchdog_sweeps_both_queues(monkeypatch):
    pytest.importorskip("flask")
    from server import app as entry, combat, mp
    calls = []
    monkeypatch.setattr(mp, "sweep_turns", lambda: calls.append("mp"))
    monkeypatch.setattr(combat, "sweep_timeouts", lambda: calls.append("combat"))
    monkeypatch.setattr(db, "query_one", lambda *a, **kw: None)
    entry._watchdog_tick({"job": None})
    assert calls == ["mp", "combat"]
