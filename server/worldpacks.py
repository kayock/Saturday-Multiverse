"""Saturday Multiverse — modular world-pack system.

A world pack is a directory containing pack.json (manifest) plus optional
companion markdown lore files. Built-in packs ship in <root>/worldpacks/.
User-imported packs live in <data dir>/worldpacks/ — deliberately separated
from redistributable built-ins so user-supplied material is never mistaken
for public assets and never shipped.

Nothing here executes pack content: packs are pure data, validated on load.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config, db

REQUIRED_KEYS = ["id", "name", "version", "summary", "locations", "archetypes", "items"]


def _builtin_pack_dir(pack_id: str) -> Path:
    return config.WORLDPACKS_DIR / pack_id


def _user_pack_dir(pack_id: str) -> Path:
    d = config.DATA_DIR / "worldpacks" / pack_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_pack_from(dirpath: Path) -> dict | None:
    manifest = dirpath / "pack.json"
    if not manifest.exists():
        return None
    try:
        pack = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    pack["_dir"] = str(dirpath)
    pack["_builtin"] = config.WORLDPACKS_DIR in dirpath.parents or dirpath == config.WORLDPACKS_DIR
    return pack


def load_pack(pack_id: str) -> dict | None:
    """Load and validate a pack by id. Built-ins take precedence."""
    for d in (_builtin_pack_dir(pack_id), _user_pack_dir(pack_id)):
        pack = _load_pack_from(d)
        if pack and pack.get("id") == pack_id:
            _validate(pack)
            return pack
    return None


def _validate(pack: dict) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in pack]
    if missing:
        raise ValueError(f"world pack '{pack.get('id', '?')}' missing keys: {missing}")


def list_packs() -> list[dict]:
    """List all available packs (built-ins and user imports), validated."""
    seen: dict[str, dict] = {}
    roots = [config.WORLDPACKS_DIR, config.DATA_DIR / "worldpacks"]
    for root in roots:
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            pack = _load_pack_from(child)
            if not pack:
                continue
            try:
                _validate(pack)
            except ValueError:
                continue
            seen[pack["id"]] = pack  # user packs override built-ins with same id
    return [_public_view(p) for p in seen.values()]


def _public_view(pack: dict) -> dict:
    """Pack summary safe to send to the client (no full content)."""
    return {
        "id": pack["id"],
        "name": pack["name"],
        "version": pack.get("version", "0"),
        "summary": pack.get("summary", ""),
        "builtin": pack.get("_builtin", False),
        "hub_location": pack.get("hub_location"),
        "locations": [
            {"id": l["id"], "name": l["name"], "short": l.get("short", "")}
            for l in pack.get("locations", [])
        ],
        "portals": pack.get("portals", []),
        "genre_tags": pack.get("genre_tags", []),
    }


def import_pack(pack_json: str) -> dict:
    """Import a user-supplied pack (JSON string) into the user pack area."""
    try:
        pack = json.loads(pack_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid pack JSON: {exc}") from exc
    _validate(pack)
    pid = pack["id"]
    # sanitize id: lowercase alnum + underscore/dash only
    safe = "".join(c for c in pid.lower() if c.isalnum() or c in "-_")
    if not safe or safe != pid:
        raise ValueError("pack id must be lowercase letters, digits, - and _ only")
    d = _user_pack_dir(safe)
    (d / "pack.json").write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    db.log_event("system", "pack_import", {"pack_id": safe})
    return {"id": safe, "name": pack["name"]}


# --------------------------------------------------------------------------
# Accessor helpers used by the GM engine
# --------------------------------------------------------------------------

def get_location(pack: dict, location_id: str) -> dict | None:
    for loc in pack.get("locations", []):
        if loc["id"] == location_id:
            return loc
    return None


def get_adventure(pack: dict, adventure_id: str) -> dict | None:
    for adv in pack.get("adventures", []):
        if adv["id"] == adventure_id:
            return adv
    return None


def get_scene(pack: dict, adventure_id: str, scene_id: str) -> dict | None:
    adv = get_adventure(pack, adventure_id)
    if not adv:
        return None
    return adv.get("scenes", {}).get(scene_id)


def get_item(pack: dict, item_id: str) -> dict | None:
    for item in pack.get("items", []):
        if item["id"] == item_id:
            return item
    return None


def get_npc(pack: dict, npc_id: str) -> dict | None:
    for npc in pack.get("npcs", []):
        if npc["id"] == npc_id:
            return npc
    return None


def get_archetype(pack: dict, archetype_id: str) -> dict | None:
    for arc in pack.get("archetypes", []):
        if arc["id"] == archetype_id:
            return arc
    return None


def get_omens(pack: dict) -> list[dict]:
    return pack.get("omens", [])


def lore_text(pack: dict) -> str:
    """Lore body: either inline or from a sibling markdown file."""
    lore = pack.get("lore", "")
    ref = pack.get("lore_file")
    if ref:
        p = Path(pack["_dir"]) / ref
        if p.exists():
            return p.read_text(encoding="utf-8")
    return lore
