# The Living Campaign Director

The Director remembers the larger shape of the story so the table does not
have to. It is a continuity and pacing assistant — **never** a second GM.

## What it tracks

Threads live in `director_threads`, one row per quest, mystery, threat,
character arc, faction stance or consequence. Every transition records the
**evidence**: the authoritative event (sequence number included) that caused
it. AI narration is never treated as having happened.

| Kind | Seeded from | Moves when |
| --- | --- | --- |
| quest | pack `intro_quests` | `quest_update` effects, story endings |
| mystery | pack `gm_secrets` | discoveries (evidence-logged) |
| threat | combat events | `combat_start` / `combat_victory` / `combat_defeat` |
| consequence | discoveries | discovery events |

## What it suggests

In **gentle** mode (the default), every fifth turn the Director may add an
optional line to the GM's context: a quest left untouched, a dormant mystery
that could surface a small clue. **Active** halves the cadence. **Off**
silences it completely. Suggestions are printed into the GM prompt as
"LIVING DIRECTOR (optional pacing — ignore if the players drive elsewhere)".
Nothing is forced, no state changes on a suggestion, dice and rewards are
untouched.

## Continuity flags

`server/continuity.py` runs deterministic checks over the event log and
engine state and reports advisory findings:

- a dead character named in narration after their death event
- the same item held twice by one character
- a completed quest re-activated later
- the same creature fought three or more times (a pattern worth acknowledging)
- a fact both visible and hidden

Flags appear in the Director panel and are advisory for the GM.

## Endpoints

- `GET /api/campaigns/<cid>/director` — threads, suggestions, current mode
- `POST /api/campaigns/<cid>/director/mode` — `{"mode": "off|gentle|active"}`
- `GET /api/campaigns/<cid>/continuity` — current findings
