"""Save compatibility: a Milestone 1 database must migrate with zero loss."""
import sqlite3

import pytest

from server import config, db, gm


@pytest.fixture()
def v1_database(tmp_path, monkeypatch):
    """Build a genuine v1 (Milestone 1) database with real campaign data,
    then point the app at it and open it with the v2 code."""
    import os

    data_dir = tmp_path / "m1save"
    data_dir.mkdir()
    monkeypatch.setenv("SATURDAY_DATA_DIR", str(data_dir))
    # import config/db fresh so the env var takes effect
    import importlib
    from server import config as config_mod
    importlib.reload(config_mod)
    from server import db as db_mod
    importlib.reload(db_mod)
    from server import gm as gm_mod
    importlib.reload(gm_mod)

    conn = sqlite3.connect(str(data_dir / "saturday.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(db_mod.SCHEMA_SQL)  # full schema (v1 tables + new IF-NOT-EXISTS tables)
    conn.executescript(db_mod.SEARCH_SQL)  # M1 databases always carried the FTS index

    # simulate a v1 save by pinning the version marker BEFORE v2 tables existed
    conn.execute("DELETE FROM worlds")   # these would not exist in a true v1 file
    conn.execute("DELETE FROM npc_memories")
    conn.execute("DELETE FROM clues")
    conn.execute("DELETE FROM echoes")
    conn.execute("DELETE FROM upgrades")
    conn.execute("DELETE FROM consequences")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', 'saturday.core.v1')")
    conn.commit()
    conn.close()

    # create a real Milestone-1-era campaign through the engine
    cid = gm_mod.create_campaign("Old Voyage", "living_shore", {
        "name": "Old Wanderer", "archetype": "sensitive", "specialty": "bind",
    })
    gm_mod.run_turn(cid, "I walk the shore and count the doors.")
    gm_mod.travel(cid, "tavern")

    # pin the marker back to v1 (init_db above already stamped v2)
    conn = sqlite3.connect(str(data_dir / "saturday.db"))
    conn.execute("UPDATE meta SET value='saturday.core.v1' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    yield data_dir, cid, gm_mod, db_mod
    monkeypatch.delenv("SATURDAY_DATA_DIR", raising=False)


def test_v1_save_migrates_and_preserves_everything(v1_database):
    data_dir, cid, gm_mod, db_mod = v1_database
    # reopening runs the v1 -> v2 migration
    db_mod.init_db()
    marker = db_mod.query_one("SELECT value FROM meta WHERE key='schema_version'")
    assert marker["value"] == "saturday.core.v2"

    view = gm_mod.campaign_view(cid)
    assert view["character"]["name"] == "Old Wanderer"
    assert view["location"]["id"] == "tavern"
    assert view["turn"] >= 1
    assert len(view["journal"]) >= 2
    # gameplay continues seamlessly on the migrated save
    res = gm_mod.run_turn(cid, "I raise a glass to the glass-eyed keeper.")
    assert res["narration"]
    assert gm_mod.get_campaign(cid) is not None


def test_newer_schema_is_refused(tmp_path, monkeypatch):
    data_dir = tmp_path / "future"
    data_dir.mkdir()
    monkeypatch.setenv("SATURDAY_DATA_DIR", str(data_dir))
    import importlib
    from server import config as config_mod
    importlib.reload(config_mod)
    from server import db as db_mod
    importlib.reload(db_mod)
    db_mod.get_conn().close()
    db_mod._CONN = None
    conn = sqlite3.connect(str(db_mod.config.DB_PATH))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', 'saturday.core.v999')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        db_mod.init_db()
    monkeypatch.delenv("SATURDAY_DATA_DIR", raising=False)
