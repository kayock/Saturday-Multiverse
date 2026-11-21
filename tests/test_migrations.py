"""Save compatibility: Milestone 1 and 2.5 saves must migrate with zero loss.

These tests run against the normal session database through the regular
engine — no module reloads, no environment juggling — so they can never
poison other tests. Migration is exercised by pinning the version marker and
re-opening, exactly what an upgraded install experiences.
"""
import sqlite3

import pytest

from server import db, gm


def _pin(cid: str, version: str) -> None:
    db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (version,))
    db._CONN = None  # force a fresh open: the migration runs on re-init
    db.init_db()


def test_v25_save_migrates_to_v3_and_preserves_everything(campaign):
    """A Living-Multiverse (v2.5) save opens under the Shared Shore build."""
    from server import legacy
    # give the wanderer state that v3 must move into the character record
    gm.travel(campaign, "camp")
    legacy.draw_to_hand(campaign)
    ch0 = gm.get_character(campaign)
    gm.ch_set(ch0, "beads", 7)
    inv_before = {i["item_id"] for i in gm.get_inventory(campaign)}
    name_before = ch0["name"]

    _pin(campaign, "saturday.core.v2")
    marker = db.query_one("SELECT value FROM meta WHERE key='schema_version'")
    assert marker["value"] == "saturday.core.v3"

    view = gm.campaign_view(campaign)
    assert view["character"]["name"] == name_before
    assert view["beads"] == 7, "the purse moved into the character record"
    assert view["character"]["id"] == ch0["id"]
    assert {i["item_id"] for i in gm.get_inventory(campaign)} >= inv_before
    # gameplay continues seamlessly on the migrated save
    res = gm.run_turn(campaign, "I raise a glass to old friends.")
    assert res["narration"]
    assert gm.get_campaign(campaign) is not None


def test_v1_pin_migrates_through_the_full_chain(campaign):
    """Pinning the oldest marker walks v1 → v2 → v3 in one open."""
    _pin(campaign, "saturday.core.v1")
    assert db.query_one("SELECT value FROM meta WHERE key='schema_version'")["value"] \
        == "saturday.core.v3"
    view = gm.campaign_view(campaign)
    assert view["character"]["name"]
    assert gm.run_turn(campaign, "The old road still holds.")["narration"]


def test_newer_schema_is_refused(tmp_path):
    """A database from a NEWER build is refused loudly, never downgraded."""
    conn = sqlite3.connect(str(tmp_path / "future.db"))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', 'saturday.core.v999')")
    conn.commit()
    with pytest.raises(RuntimeError):
        db._migrate(conn, "saturday.core.v999")
    conn.close()
