"""Fantasy asset pack + cinematic catalog integrity (no OpenFilm / AI)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FANTASY = ROOT / "client" / "assets" / "fantasy"
CINE = ROOT / "client" / "assets" / "cinematics"


def test_fantasy_manifest_has_100_unique_ids():
    man = json.loads((FANTASY / "asset-manifest.json").read_text())
    assert man["total_assets"] == 100
    ids = [a["id"] for a in man["assets"]]
    assert len(ids) == 100
    assert len(set(ids)) == 100
    for a in man["assets"]:
        path = FANTASY / a["file"]
        assert path.is_file(), a["id"]
        assert path.stat().st_size > 1000


def test_scene_mapping_does_not_overwrite_tavern():
    mapping = json.loads((FANTASY / "scene-mapping.json").read_text())
    locs = mapping.get("locations") or {}
    assert "tavern" not in locs
    assert mapping["art_library_only"]["TWN-002"]


def test_cinematic_catalog_preserves_v1_and_adds_fantasy():
    cat = json.loads((CINE / "meta" / "game-catalog.json").read_text())
    files = {a["file"] for a in cat["assets"]}
    # original 17
    assert "photoreal-tavern-loop-16s.mp4" in files
    assert "sm-campfire-driftwood-loop-16s.mp4" in files
    # new fantasy four
    for f in [
        "fantasy-gate-of-worlds-loop-16s.mp4",
        "fantasy-shattered-coast-loop-18s.mp4",
        "fantasy-copper-kettle-loop-16s.mp4",
        "fantasy-sky-rift-loop-16s.mp4",
    ]:
        assert f in files
        assert (CINE / "videos" / f).is_file()
    # copper kettle must not be tavern ambient
    tavern = cat["selection"]["locations"]["tavern"]["ambient"]["default"]
    assert tavern == "photoreal-tavern-loop-16s.mp4"
    wreck = cat["selection"]["locations"]["wreck"]["ambient"]["default"]
    assert wreck == "fantasy-shattered-coast-loop-18s.mp4"


def test_original_stills_preserved():
    for name in ["tavern-primary.png", "shore-primary.png", "portal-primary.png", "campfire-primary.png", "saltgrave-primary.png"]:
        assert (CINE / "stills" / name).is_file()
    for name in ["fantasy-gate-of-worlds.png", "fantasy-shattered-coast.png", "fantasy-copper-kettle.png", "fantasy-sky-rift.png"]:
        assert (CINE / "stills" / name).is_file()
