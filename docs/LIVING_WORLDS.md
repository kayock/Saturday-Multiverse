# The Living Worlds — v0.4.0 feature guide

## The Shore Remembers (returning-player recap)

Entering an existing voyage fetches `GET /api/campaigns/<cid>/recap` — a
recap assembled from the **engine event log**: recent victories, story
endings, unresolved quests and Director threads, discoveries, NPC memory
movement, shore upgrades and the current weather. Nothing is invented; if the
AI narrates it later, every line still traces to a recorded event. Dismissing
the banner records the turn, so the next visit only shows what changed since.

## Expedition goals

`party_goals` are shared or personal objectives ("Recover three lost
relics"). Progress comes from **engine events only**: `auto_credit` matches
combat victories, discoveries and quest resolutions to goal titles
deterministically. The Ledger panel shows progress bars; players can add,
advance or abandon goals — goals never force story direction.

## Campfire Stories

`campfire_stories` store a player's retelling with kind (`story`, `memory`,
`memorial`, `record`, `goal_idea`), author and an optional link to a verified
event sequence. They are displayed **explicitly as player-authored** — the
Ledger keeps them beside the mechanically verified records and nothing treats
a story as proof an event happened (continuity checks ignore them).

**Stories reveal nothing (v0.4.0-hotfix3).** Posting an ordinary tale shares
no knowledge. Sharing is a separate, explicit act: the teller ticks specific
discoveries, places or individual rumors in the campfire form, and the engine
validates every selection (only what the character legitimately knows; never
GM-only secrets; never a bare hearing scope — share the one rumor, not the
tavern's future). See `docs/MULTIPLAYER.md` for the full contract.

## Engine Trace

`run_turn` and `choose` return a `trace`: the action, the rule and dice (with
modifiers, difficulty, outcome), each validated engine effect, and the
narration source — AI Game Master or Offline Storyteller, always labeled. The
panel never shows GM-only knowledge or future outcomes. The browser displays
and requests; the engine resolved everything before narrating.

## What-If Timelines

`POST /api/campaigns/<cid>/timelines` branches a checkpoint (or the current
state) into a NEW campaign with its own identity, event stream, inventory and
Director threads. The original campaign is never modified and never receives
branch rewards. `GET .../timelines/compare/<other>` diffs endings, quests,
character fates, inventory and NPC relationships from actual snapshots.

## Workshop playtest portals

`POST /forge/collab/<draft>/playtest` creates a real campaign from the DRAFT
pack — no approval needed — with `playtest_of` isolation. `GET
.../playtest/report` lists validation problems, flow findings, missing item
references and (with a live session) continuity warnings. `POST
.../playtest/stop` archives the portal and removes the temporary pack.
Approved worlds and real saves are never touched.

## Preflight diagnostics

`python scripts/preflight.py` checks Python version, dependencies, SQLite and
FTS5 capability, data-directory writability, schema state, backups, port
availability, world-pack integrity and (optionally) configured-model
reachability. It prints PASS/WARN/FAIL lines and never starts or installs a
model, never prints credentials. Exit code 1 means a blocking failure.

## CI and browser tests

`.github/workflows/ci.yml` runs on Linux and Windows (Python 3.10/3.12):
syntax compilation, JavaScript checks, world-pack validation, the full pytest
suite, a real startup smoke test (`scripts/smoke_startup.py`), plus a Playwright
browser job driving real Chromium sessions through the title screen, a solo
voyage, the Ledger, the Engine Trace and the Workshop. The browser specs live
in `tests/browser/` and are excluded from the plain pytest run.


## Hotfix3 corrections (sharing privacy and recap integrity)

- **Sharing is explicit, bounded and validated.** The hotfix2 behavior
  "a campfire post shares the teller's knowledge" is replaced: a story
  shares nothing; the teller selects individual items and the engine
  validates each one. One shared rumor never unlocks later rumors from the
  same place; party-wide grants cover only what existed at share time;
  historical blanket shares stay readable but stop authorizing future
  private memories (documented conservative policy — nothing deleted).
- **Recap eligibility runs BEFORE the display limit.** The recap collects
  its 8 NPC-memory budget from an eligibility-filtered, bounded backward
  walk, so hidden/unauthorized rows can no longer crowd out an authorized
  rumor. Markers, ordering, dedup and per-player dismissal are unchanged.

## Hotfix2 corrections (player-specific knowledge)

- The Shore Remembers is now **player-aware**: recap items are filtered by
  the viewer character's actual knowledge (`char_knowledge`, schema v8) —
  visited places, personally-made discoveries and things heard in person.
  A memory's hearing scope describes which NPC can hear it; it is not
  permission for every player to read it.
- **The campfire is the sharing mechanism** (superseded by the explicit,
  item-level sharing of hotfix3 — see above; the `char_knowledge` shared-row
  format and the spectator shared feed are unchanged).
- **Dismissal is per player** (`recap_seen` table): your "what changed since
  I last looked" never depends on another player's reading habits.
- Solo play is unchanged in behavior; spectators see public events and
  party-shared tales only.

## Hotfix1 corrections (privacy and integrity)

- **Recap knowledge boundaries.** The Shore Remembers quotes only NPC
  memories whose hearing scope is player-facing (`all`, `camp`, `doors`,
  `tavern`); deep-scoped shore knowledge (the drowned lampkeeper's secrets
  and anything marked hidden/GM-only) never appears. Achievements and
  discoveries are filtered by per-table last-seen rowids recorded at
  dismissal — dismissed history does not reappear as new, and genuinely new
  events after the marker do. Ongoing objectives and current weather are
  marked `novelty: "ongoing"` so returning players can tell persistence from
  news.
- **Goal progress integrity.** `verified_progress` is incremented only by
  engine events (victories, discoveries, quest resolutions). The
  player-facing progress endpoint records voluntary progress as
  player-authored and can never fabricate verified achievements. Goal
  mutations are scoped to the supplied campaign, and personal goals respect
  their owner in multiplayer.
