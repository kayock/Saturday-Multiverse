#!/usr/bin/env python3
"""Generate printable QR cards for Saturday Multiverse's scanner feature.

Requires the `qrcode` package (pip install qrcode) and Pillow. Cards are
written to <data dir>/qr_cards/ as PNG files. The payloads map to the
server's strict allowlist — scanned codes are data-only, never executable.

    python3 scripts/make_qr_cards.py [--outdir DIR]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
except ImportError:
    print("Missing dependency: pip install qrcode pillow")
    raise SystemExit(1)


CARDS = [
    ("SM:CMD:INVENTORY", "Open your pack"),
    ("SM:CMD:CHARACTER", "Open your character"),
    ("SM:CMD:JOURNAL", "Open the journal"),
    ("SM:CMD:MAP", "Open the map"),
    ("SM:CMD:QUESTS", "Open quests"),
    ("SM:CMD:DICE", "Open the dice tray"),
    ("SM:CMD:REST", "Rest, if this place allows it"),
    ("SM:ITEM:salt_charm", "Inspect: Salt-charm"),
    ("SM:ITEM:keepers_lantern", "Inspect: Keeper's lantern"),
    ("SM:ITEM:brass_key", "Inspect: Brass key, nine lamps"),
    ("SM:ITEM:callers_name", "Inspect: The Caller's Name"),
    ("SM:ITEM:marrow_bell_shard", "Inspect: Marrow Bell shard"),
    ("SM:LORE:cardo_song", "Lore: Cardo's door-song"),
    ("SM:EVT:firefly_hour", "Event: The Firefly Hour"),
    ("SM:EVT:whisper_tide", "Event: The Whisper Tide"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()
    outdir = Path(args.outdir) if args.outdir else (ROOT / "userdata" / "qr_cards")
    outdir.mkdir(parents=True, exist_ok=True)

    for payload, title in CARDS:
        qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=12, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#141126", back_color="white")
        safe = payload.replace(":", "_").lower()
        path = outdir / f"{safe}.png"
        img.save(path)
        print(f"  {path.name:34s} {title}")
    print(f"\n{len(CARDS)} cards written to {outdir}")
    print("Print them, cut them out, and scan them while playing.")
    print("A scan is data only: unknown codes do nothing, always.")


if __name__ == "__main__":
    main()
