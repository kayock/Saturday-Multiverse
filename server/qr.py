"""Saturday Multiverse — QR / barcode-scanner input.

USB "keyboard wedge" scanners type their payload as rapid keystrokes ending
with Enter; the client collects such bursts and posts them here.

Security rules (hard requirements, not guidelines):
- A scanned payload is DATA, never code. Nothing is ever eval'd, exec'd,
  templated or passed to a shell.
- Payloads must match a strict allowlist of prefixes and commands.
- Everything else is rejected and logged as an unknown sigil.
- Maximum payload length: 256 characters.
"""
from __future__ import annotations

from . import db, gm, worldpacks

MAX_LEN = 256
PREFIX = "SM:"

UI_COMMANDS = {
    "INVENTORY": "open the inventory panel",
    "CHARACTER": "open the character panel",
    "JOURNAL": "open the journal panel",
    "MAP": "open the map panel",
    "QUESTS": "open the quests panel",
    "DICE": "open the dice tray",
}


def parse_payload(cid: str, payload: str) -> dict:
    """Resolve a scanned payload against the allowlist. Never executes code."""
    payload = (payload or "").strip()[:MAX_LEN]
    if not payload.startswith(PREFIX):
        return _unknown(cid, payload)

    parts = payload.split(":", 2)
    body = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    if body == "CMD":
        cmd = arg.split(":")[0].strip().upper()
        if cmd in UI_COMMANDS:
            db.log_event(cid, "qr_command", {"cmd": cmd})
            return {"ok": True, "kind": "ui", "command": cmd,
                    "desc": UI_COMMANDS[cmd]}
        if cmd == "REST":
            try:
                result = gm.rest(cid)
                return {"ok": True, "kind": "rest", "narration": result["narration"]}
            except ValueError as exc:
                return {"ok": False, "kind": "rest", "detail": str(exc)}
        return _unknown(cid, payload)

    pack = None
    campaign = gm.get_campaign(cid)
    if campaign:
        pack = worldpacks.load_pack(campaign["pack_id"])

    if body == "ITEM" and pack:
        item = worldpacks.get_item(pack, arg.strip())
        if item:
            db.log_event(cid, "qr_item", {"item_id": item["id"]})
            return {"ok": True, "kind": "item", "item": item}
        return _unknown(cid, payload)

    if body == "LORE" and pack:
        for entry in pack.get("qr_lore", []):
            if entry.get("id") == arg.strip():
                db.add_journal(cid, entry.get("text", ""), "discovery")
                db.log_event(cid, "qr_lore", {"lore_id": entry["id"]})
                return {"ok": True, "kind": "lore", "lore": entry}
        return _unknown(cid, payload)

    if body == "EVT" and pack:
        for event in pack.get("qr_events", []):
            if event.get("id") == arg.strip():
                changes: list[str] = []
                gm.apply_effects(cid, pack, event.get("effects", {}), changes)
                db.log_event(cid, "qr_event", {"event_id": event["id"]})
                return {"ok": True, "kind": "event", "event": event, "changes": changes}
        return _unknown(cid, payload)

    return _unknown(cid, payload)


def _unknown(cid: str, payload: str) -> dict:
    db.log_event(cid, "qr_unknown", {"payload": payload[:64]})
    return {"ok": False, "kind": "unknown",
            "detail": "The sigil does nothing here. (Unrecognized QR payload.)"}
