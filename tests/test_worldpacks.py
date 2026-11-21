"""World pack loading, validation and content integrity."""
import pytest

from server import worldpacks


def test_builtin_pack_loads():
    pack = worldpacks.load_pack("living_shore")
    assert pack and pack["id"] == "living_shore"
    assert pack["_builtin"] is True


def test_missing_pack_returns_none():
    assert worldpacks.load_pack("does_not_exist") is None


def test_living_shore_content():
    pack = worldpacks.load_pack("living_shore")
    locs = {l["id"] for l in pack["locations"]}
    assert {"tidegate", "camp", "tavern", "lighthouse", "seacave", "wreck",
            "saltgrave_gate", "umbral_reach"} <= locs
    assert len(pack["portals"]) == 3
    assert len(pack["omens"]) == 24
    assert all(o["kind"] in ("edge", "complication", "turn") for o in pack["omens"])
    ids = [i["id"] for i in pack["items"]]
    assert len(ids) == len(set(ids)), "item ids must be unique"
    # every adventure choice target must exist
    adv = worldpacks.get_adventure(pack, "salt_grave_signal")
    assert adv and adv["entry"] in adv["scenes"]
    for scene in adv["scenes"].values():
        for choice in scene.get("choices", []):
            for branch in (choice.get("on_pass"), choice.get("on_fail")):
                if branch and branch.get("goto"):
                    assert branch["goto"] in adv["scenes"], branch["goto"]
    # every item referenced by kits/effects exists in the catalog
    catalog = set(ids)
    for arc in pack["archetypes"]:
        for item_id in arc.get("kit", []):
            assert item_id in catalog, item_id
    for qr_event in pack.get("qr_events", []):
        for g in qr_event.get("effects", {}).get("item_give", []):
            assert g["item_id"] in catalog, g["item_id"]


def test_lore_file_loaded():
    pack = worldpacks.load_pack("living_shore")
    lore = worldpacks.lore_text(pack)
    assert "Lantern Law" in lore
    assert "Beam" in lore


def test_accessors():
    pack = worldpacks.load_pack("living_shore")
    assert worldpacks.get_location(pack, "camp")["id"] == "camp"
    assert worldpacks.get_item(pack, "brass_key")["kind"] == "key"
    assert worldpacks.get_npc(pack, "maren")["name"] == "Maren"
    assert worldpacks.get_archetype(pack, "sensitive")["stats"]["bind"] == 2
    assert worldpacks.get_scene(pack, "salt_grave_signal", "sg_arrival")["title"] == "The Nine Lanterns"
    assert worldpacks.get_scene(pack, "salt_grave_signal", "nope") is None


def test_import_pack_roundtrip(tmp_path):
    pack = worldpacks.load_pack("living_shore")
    import json
    mini = {
        "id": "testmini", "name": "Mini Pack", "version": "0.1", "summary": "test",
        "locations": [{"id": "only", "name": "Only", "desc": "d"}],
        "archetypes": [{"id": "a1", "name": "One", "stats": {"wits": 1}, "kit": []}],
        "items": [{"id": "thing", "name": "Thing", "kind": "tool", "desc": "d"}],
    }
    out = worldpacks.import_pack(json.dumps(mini))
    assert out["id"] == "testmini"
    loaded = worldpacks.load_pack("testmini")
    assert loaded and loaded["name"] == "Mini Pack" and loaded["_builtin"] is False


def test_import_rejects_bad_ids():
    import json
    bad = {"id": "Bad Id!", "name": "x", "version": "0", "summary": "",
           "locations": [], "archetypes": [], "items": []}
    with pytest.raises(ValueError):
        worldpacks.import_pack(json.dumps(bad))
