"""World-pack validation for CI: every shipped pack must load and validate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import worldpacks  # noqa: E402


def main() -> int:
    failed = []
    packs = worldpacks.list_packs()
    if not packs:
        print("FAIL: no world packs found")
        return 1
    for p in packs:
        print(f"ok   {p['id']:24s} v{p.get('version', '?')} · {len(p.get('locations', []))} locations")
    # force a full load+validate of every directory, not just the public view
    roots = [worldpacks.config.WORLDPACKS_DIR,
             worldpacks.config.DATA_DIR / "worldpacks"]
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in seen:
                continue
            seen.add(child.name)
            try:
                pack = worldpacks._load_pack_from(child)
                if pack:
                    worldpacks._validate(pack)
            except Exception as exc:  # noqa: BLE001
                failed.append((child.name, str(exc)[:120]))
    if failed:
        for name, err in failed:
            print(f"FAIL {name}: {err}")
        return 1
    print(f"all {len(seen)} world pack(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
