# QR & scanner cards

Optional. The game is fully playable without ever scanning anything.

USB barcode/QR scanners in "keyboard wedge" mode type their payload as very fast
keystrokes ending with Enter. While the game is open, `client/js/qr.js` detects such
bursts (characters arriving <50 ms apart, ≥8 chars, terminated by Enter) and posts the
payload to the server. Any other typing is unaffected.

You can also paste a code into the composer — same pipeline.

## The allowlist (hard security rule)

A scanned payload is **data**. It is never eval'd, exec'd, templated, or passed to a
shell. It must match one of these forms or it is rejected and logged as an unknown
sigil (which itself becomes part of the story: *"The sigil does nothing here."*):

| Payload | Effect |
|---|---|
| `SM:CMD:INVENTORY` | open the pack panel |
| `SM:CMD:CHARACTER` | open the character panel |
| `SM:CMD:JOURNAL` | open the journal |
| `SM:CMD:MAP` | open the map |
| `SM:CMD:QUESTS` | open quests |
| `SM:CMD:DICE` | open the dice tray |
| `SM:CMD:REST` | rest, if the location allows it |
| `SM:ITEM:<item_id>` | inspect a catalog item (e.g. `SM:ITEM:brass_key`) |
| `SM:LORE:<lore_id>` | discover a lore entry from the pack's `qr_lore` |
| `SM:EVT:<event_id>` | trigger a pack event from `qr_events` (validated effects only) |

Maximum payload length: 256 characters. Hostile or malformed input can only produce a
journal/log entry — the test suite tries an `os.system` payload and a SQL string and
asserts both are inert.

## Making cards

```bash
pip install qrcode pillow
python scripts/make_qr_cards.py            # → userdata/qr_cards/*.png
python scripts/make_qr_cards.py --outdir /tmp/cards
```

Fifteen starter cards are generated for the Living Shore pack, including artifact
inspection and two events ("The Firefly Hour", "The Whisper Tide"). Print, cut,
scatter on the table — a physical deck beside the laptop is the intended use.

World packs extend the deck with their own `qr_lore` / `qr_events` entries; write your
own card text and encode `SM:EVT:<id>` with any QR generator.

## Physical-interaction ideas

- Inspect an artifact card when the table finds a prop.
- "Sigil cards" hidden around a room as a puzzle: scanning the right one triggers an
  approved in-game event.
- Character-card per player (Milestone 3): `SM:CMD:CHARACTER` variants bound to
  session tokens.
