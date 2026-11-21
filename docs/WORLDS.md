# Worlds beyond the Beam — seeded portals & world packs (Milestone 2.0)

## Seeded portal generation

The **Unstable Door** stands at the far end of the Beam (magenta, iridescent).
Click it, whisper a *seed* — a word, a name, a short phrase — and the
generator produces a world. Rules:

- **Deterministic.** `sha256(normalized_seed + "|" + generator_version)`
  drives every choice. The same seed under the same generator version always
  yields the same world (name, archetype, locations, NPCs, mysteries,
  signature scenario, relic). `Clockwork Ocean` is the same world every
  time, for every campaign on your machine.
- **Versioned.** The generator version is stamped into the world record
  (`living-multiverse.gen.v1`). If the generator changes in a later release,
  existing worlds keep their stored identity and stay playable unchanged.
- **Canonical.** The generated identity is stored in the `worlds` table.
  The AI may enrich narration; it cannot alter the structure.
- **Persistent.** Visit counters, world flags, scenario progress and
  endings live in `worlds.state_json`. Return through the door (or the
  Ledger / the seed gate's "Worlds already discovered") and the world
  remembers you — the scenario resumes mid-beat, exactly like the shore's
  adventures.

## What a generated world contains

- A generated name built from archetype wordbanks (e.g. *The Hollow Orbit*,
  *Salt Cathedral*, *Glass Wilderness*).
- Three locations with hotspots, two NPCs with greetings and rumors, two
  mysteries, threats, atmospheric properties.
- One unique relic item (engine-validated, given only through defined
  effects).
- A playable **signature scenario** — the world's small, permanent request:
  observe → engage → answer/refuse. Three endings; the successful one pays
  3 glassbeads and the world's relic; refusal is honored and recorded.
- Echo offers on its endings (see Echoes).

## Visiting

1. Click the Unstable Door (or Ledger → Known worlds → *The door remembers*).
2. Enter or pick a seed. New worlds are created; existing ones are returned to.
3. Step through — first visits record intro facts, tint the scene, and start
   the signature scenario. The map shows discovered worlds; the dock, journal
   and dice all work inside a world as they do on the shore.

World suggestions are built in (`/api/seeds/suggest`); the lighthouse
*Relamp* upgrade will add more over time.

## Extending worlds (world-pack authors)

Generated worlds are data-shaped exactly like pack adventures — a pack may
also ship **handcrafted** worlds by adding locations with
`"adventure": "<id>"` and a matching adventure entry. Nothing in the
generator is special: `worldpacks/living_shore/pack.json` plus
`scripts/extend_pack.py` demonstrate the format end to end. See
`docs/WORLDPACKS.md` for the pack format, and `docs/MULTIPLAYER.md` for how
worlds will be shared between hosts in later milestones.

## Cross-world consequences & foreshadowing (Milestone 2.5)

- **Consequences** are registered by the engine on defined triggers
  (adventure endings, world discoveries, upgrades, thread payoffs), deduped,
  and surfaced in tavern gossip and the Ledger. The AI may reference them;
  only the engine creates them.
- **Clue threads**: pack-defined threads (e.g. *The Ninth Wave*, threshold 4
  clues; *The Wrong Gull*, threshold 3). Clues arrive from wash-ashore
  finds, adventure endings, omen complications and choices. At threshold the
  thread **pays off** through the standard effects engine — the Ninth Wave
  unlocks a hidden shore location with one-time gifts; the Wrong Gull
  becomes a companion with a mechanical perk.
- **Echoes**: eligible endings offer echoes (items, traits, achievements,
  reputations, portal knowledge). They are saved at profile level, shown in
  the Ledger, and up to **two** can be woven into a newly created voyage at
  character creation. Each echo can be woven once, ever. Reputation echoes
  pre-seed NPC relationships; portal echoes pre-generate a world.

## The Memory Ledger

The Ledger panel (HUD → Ledger) is the visual journal: known worlds as
cards, people with relationship state, mystery threads with clue progress,
cross-world consequences, echo shelf, tavern-talk memories, and the full
chronological log underneath. Everything in it is grounded in recorded
events — it is a view, not a narrative.
