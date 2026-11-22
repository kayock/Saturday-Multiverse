# Architecture

Saturday Multiverse is a local-first client/server game. One Python process serves
both the REST API and the static browser client on a single port. There is no build
step anywhere.

```
┌───────────────────────── browser ─────────────────────────┐
│  client/ (ES modules, no build)                           │
│   main.js       screens, flow, composer                   │
│   scene.js      animated canvas shore (hub exploration)   │
│   vignettes.js  SVG interior/adventure scenes             │
│   ui.js         drawers: map/journal/pack/quests/dice     │
│   audio.js      WebAudio synthesis (no audio files)       │
│   portraits.js  procedural SVG portraits                  │
│   qr.js         keyboard-wedge scanner listener           │
└──────────────────────┬────────────────────────────────────┘
                       │ fetch() JSON
┌──────────────────────▼────────────────────────────────────┐
│  server/ (Flask)                                          │
│   api.py        REST routes, rate limit, optional token   │
│   gm.py         turn orchestration, adventure state,      │
│                 effects choke-point, views, export        │
│   ai.py         OpenAI-compatible adapter, JSON extract   │
│   rules.py      the Undertow System (2d6, bands, harm)    │
│   worldpacks.py pack loader/validator (data only)         │
│   qr.py         scanned-payload allowlist                 │
│   db.py         SQLite + WAL, FTS5 search, event log      │
└──────────────────────┬────────────────────────────────────┘
        ┌──────────────┴───────────────┐
   userdata/saturday.db          model endpoint
   (SQLite, backups, exports)    (yours, OpenAI-compatible)
```

## The honesty rule (why the AI is boxed in)

Mechanics are **application code**, never the model:

1. The player's free-text action and the current scene/state are assembled into a
   prompt (`gm.build_system_prompt` / `gm.build_user_prompt`). The prompt carries the
   pack lore, character sheet, tide/weather, item catalog (valid `item_id`s), NPCs,
   open quests, known facts, and the last 8 transcript messages.
2. The model replies with **one JSON object** (`ai.extract_json` tolerates fences and
   chatter): narration, optional one check request, optional inventory request,
   memory facts, NPC relationship deltas, suggestion chips, scene hint.
3. `gm.run_turn` validates every field: skills must be known, items must exist in the
   pack catalog, quantities clamp, relationships only touch known NPCs. Check
   requests are rolled by `rules.roll_check` with `secrets` RNG and applied
   (harm to Vigor/Nerve per band). Everything is written to the transcript, dice
   log, and append-only `events` table.
4. If the model is absent, unreachable, or returns garbage twice, the **Offline
   Storyteller** produces templated narration while the same mechanics still run.
   The turn's `meta.ai_used` flag tells the client which mode produced it, and the
   HUD badge shows it at all times.

Hidden story information is stored in the `facts` table with `scope='hidden'` and is
**never** placed in the model prompt nor sent to the client view; it exists for the
host and for long-arc continuity.

## Who chooses the model

`server/routing.py` chooses the Game Master for an ordinary turn. Manual
mode leaves the Settings endpoint alone. Automatic mode prefers a free
lightweight model on a second machine and uses the first machine when that
host is offline or busy. The application classifies the call. A model
response cannot switch endpoints.

`server/forge_ai.py` chooses the Campaign Forge model separately and marks
the call direct, so gameplay routing cannot replace it. Automatic and
selected local conversions stay on loopback or a private address. A larger
local model is used only when it is already loaded. An online provider is
used only when that provider was selected and the operator approved sending
the manuscript. The choice is pinned to the conversion job without the API
key. If the local model fails, the job fails. It is not retried against a
hosted API.

## State model

`campaigns` is the anchor row (pack id, location, beat, drift, state JSON with flags).
Around it: `characters`, `inventory`, `journal`, `quests`, `npcs`, `facts`,
`transcript`, `dicelog`, `locations_state` (discovery), `decks` (omen deck draw/discard),
`events` (append-only audit). Search uses an FTS5 mirror (`search_index`) maintained on
every journal/transcript write.

Time is **drift** — every action, travel or choice advances it by beats. Tide is a pure
function of drift (`tide_for`), weather re-rolls on 5-beat boundaries from the pack's
weighted table. Locations can require a tide or discovery to enter (`travel` gates).

All state mutations funnel through `gm.apply_effects` — one choke-point used by AI
proposals, scripted choices, item uses, and QR events. That is what keeps campaign
continuity deterministic and auditable (`events` records who changed what).

## World packs

Packs are JSON + markdown under `worldpacks/<id>/pack.json` (built-ins) or
`<data dir>/worldpacks/<id>/` (user imports — deliberately separated so user material
is never mistaken for redistributable content). The loader validates required keys and
never executes pack content. See `docs/WORLDPACKS.md` for the full format.

## Multiplayer groundwork (Milestones 3–4)

The database already carries `sessions` and `invites` tables, and every gameplay
endpoint is a single authenticated request against host-authoritative state — the
shape Milestone 3 needs. Nothing about solo play changes when tokens arrive.
Contracts and phasing: `docs/MULTIPLAYER.md`.

## Security posture (Milestone 1)

- Binds `127.0.0.1` by default; `SATURDAY_TOKEN` gates non-loopback clients.
- Per-IP sliding-window rate limits (API 120/min, AI-heavy POSTs 30/min).
- QR payloads are data with a strict `SM:` allowlist; unknown sigils are logged and
  ignored. No eval/exec/shell anywhere near scanned content.
- The API key is stored in the local DB and never echoed back (`masked_ai_config`).
- Backups are whole-database copies (`sqlite3` backup API) with restore.

## Testing

`tests/` covers rules math, pack integrity (every choice target/kit item must exist),
the full GM flow (travel gating, adventure branches, endings, resume, export/import),
the AI adapter (JSON extraction, config validation, real HTTP against the bundled mock
model server), and the HTTP surface (Flask test client). `scripts/smoke_test.py` walks
a campaign end to end without pytest. Run: `python -m pytest tests/ -q`.


## The Shared Shore layer (Milestone 3)

```
browser (mp.js)                         server
  session token (localStorage)  --X-MP-Token-->  api.py _mp_resolve()
  EventSource(ticket, last_seq) <--SSE--------   mp.stream(): mp_events replay + live
  intents (act/choose/trade…)   ----------->    session_lock(cid) -> gm/legacy engine
                                                  |-> mp_events.append (seq, visibility)
                                                  |-> events/dicelog/journal (solo tables)
```

- `server/mp.py` owns sessions, invitations, presence, turn order, chat,
  trades, gifts, contributions, group travel and party memory. It never
  touches dice or effects directly — it calls the same `gm`/`legacy`
  functions solo uses, inside a per-campaign lock.
- `mp_events` is the sync backbone: append-only, globally sequenced per
  campaign, visibility-filtered (`party` / `player:<id>` / `host`). Clients
  reconnect with the last sequence they saw; replay is idempotent because
  the underlying actions are engine-guarded.
- Schema v3 made characters party-capable (per-character beads, death,
  pending rolls, omen decks, inventory ownership) while keeping solo
  single-wanderer semantics identical.
