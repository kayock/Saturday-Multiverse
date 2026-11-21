# The Undertow System — rules reference (v2)

The engine owns every number. The AI Game Master may request a check and
narrate the result; it may never set a cost, alter a roll, or grant state.

## The baseline roll

`2d6 + stat modifier + skill modifier (+ situational modifiers)`

| Total | Band | Meaning | Harm |
|---|---|---|---|
| 12+ | **Surge** | strong success, minor boon | 0 |
| 10–11 | **Clean** | straightforward success | 0 |
| 7–9 | **Riptide** | success at a cost | 1 |
| ≤6 | **Undertow** | failure with complication | 2 |
| double 6 | **Kicker** | critical — always at least Surge | 0 |
| double 1 | **Wipeout** | catastrophic failure | 4 |

A *hard* check shifts the band one step down; *easy* shifts one up. Harm
lands on **Vigor** (physical: fight, endure) or **Nerve** (mental: the rest)
unless the GM's request specifies otherwise. Rolls use a cryptographic RNG
and every roll is written to the dice log and event log.

## Tactical options (Milestone 2.0)

All optional; the baseline is unchanged. The client shows the available
buttons after each engine-rolled check.

### Risk — *declare before the roll*
- Effect: **+2** to the roll; if the outcome is Undertow or Wipeout, deal
  **+2 extra harm**.
- Declared by the player in the dice tray or (for GM checks) before acting.
- Applied by the engine; visible in the roll text as "(risked)".

### Push — *after seeing the result*
- Effect: raise the band **one** step — Undertow → Riptide or
  Riptide → Clean.
- Cost: **1 Vigor**, and Vigor may not drop below 1 by pushing.
- Limits: once per roll; never on Kicker/Wipeout/Clean/Surge; never on a
  band shift that would exceed Clean.
- The engine settles the harm difference automatically.

### Resist — *when harm lands*
- Effect: **halve** the incoming harm, rounding down (1 → 0).
- Cost: **1 Nerve**.
- Limits: once per roll; only when harm > 0. The engine refunds the
  difference (harm was applied when the roll resolved).

Push and Resist windows exist for GM-called checks and manual rolls.
Scripted adventure "fate checks" resolve atomically with their branch —
they are binding by design.

## Vigor and Nerve

- **Vigor** = 10 + Might. Body. At Vigor 0 you are spent.
- **Nerve** = 10 + Mettle. Mind. At Nerve 0 you are unravelling.
- **Both at 0** → the wanderer's story concludes (death/retirement). The
  multiverse keeps a *Remembrance* echo, the campaign renders an epilogue
  state, and further actions are refused. Begin a new voyage and weave the
  echo in.
- Resting restores: camp 3 Vigor / 2 Nerve (+2 Vigor with the Camp Kettle),
  tavern 4 / 4 (fully with the Back Hammock). Resting also refreshes the
  omen deck's player draws, and a befriended gull grants a one-time +1
  Notice after each rest.

## Glassbeads (Milestone 2.0 economy)

The shore's coin — sea-glass polished by the Beam. Earned by adventure
endings (defined in pack data), wash-ashore finds, and first visits to
seeded worlds. Spent only on shore improvements, and (in the Umbral
Market) as a currency of hours. Engine-managed; the AI never sets prices.

## Shore improvements (Milestone 2.0)

| Upgrade | Location | Cost | Effect |
|---|---|---|---|
| Camp Kettle | camp | ◍ 2 | +2 Vigor when resting at camp |
| Traveler's Guestbook | camp | ◍ 3 | special visitors find the camp |
| Maren's Map Wall | tavern | ◍ 4 | rumors sharpen; a consequence echoes to gossip |
| The Back Hammock | tavern | ◍ 3 | tavern rest restores fully |
| Relamp the Skyless Light | lighthouse | ◍ 5 | teal beam; unlocks the flame-sharing ending |
| Polished Lens Array | lighthouse | ◍ 4 | planned: richer wash-ashore yields |

Purchases require standing at the upgrade's location, are permanent, and
are visible on the canvas (kettle and steam, teal beam, map-wall glow).

## Omen Deck — agent and player modes (Milestones 1.5 / 2.0)

- **Agent draws** (M1 behavior, unchanged): every 3rd turn the tide draws a
  card. Edges grant +1 on their skill until used; complications impose −1
  on your next check and feed the *Wrong Gull* thread.
- **Player hand**: draw for **1 Nerve** — max **2 held**, max **2 draws per
  rest**. Playing an **edge** sets a +1 on its skill until it lands;
  playing a **turn** card steadies you (Nerve +1); **complications cannot
  be played deliberately** — they play themselves.
- All deck state (draw/discard/hand) lives in the engine. The deck is
  pack data; world packs may ship their own 24-card decks.

## Cinematic dice reactions (Milestone 1.5)

Order of operations, always:
1. The engine rolls and resolves.
2. The UI shows the dice and band.
3. The GM (AI or persona fallback) narrates **only the moment of the
   result** — instructed to never contradict it, never grant state.
4. State changes apply through the effects engine only.

## GM personalities (Milestone 1.5)

Seven selectable personas — Classic Fantasy, Grimdark, Cosmic Horror, Noir,
Whimsical, Mythic, and Custom (your own tone text, ≤400 chars). The persona
shapes the system prompt's tone block, the Offline Storyteller's flavor
lines, and the outcome narration lines. It is stored per campaign and
persists between sessions. **Personality never becomes rules authority** —
the persona blocks are tone-only; every mechanical path is unchanged.


## Shared-shore rules (Milestone 3)

Multiplayer changes no baseline numbers. It adds party-level structure:

- **Party travel** — one traveler proposes a door; departure requires every
  connected player's agreement (or the host's direct order). Any refusal
  cancels the proposal. The transition resolves once, through the standard
  travel engine, for the whole party.
- **Turn order (structured mode)** — the host may switch the shore to
  turn-by-turn play. The current traveler holds "the lantern"; actions from
  others are refused server-side; the lantern passes automatically after
  the timeout (240s default), when its holder disconnects, or when passed
  explicitly. Freeform mode remains the default: actions serialize
  server-side in arrival order.
- **Assist / Protect (deterministic forms)** — assistance is expressed
  through the existing economy rather than new rolls: gifting glassbeads
  (1–10, atomic), trading kit items (offer → accept, atomic), or
  contributing beads to shared shore improvements (escrowed pot; the build
  resolves exactly once). There is no unlimited assistance: every transfer
  has hard bounds and every action is logged.
- **Personal fates** — harm, death, omen hands, pending push/resist windows
  and purses are strictly per character. A party member's death never
  spreads to the party, and the Remembrance echo is personal.
- **Party memory** — an adventure ended while a party shares the shore is
  recorded as a company moment (who sailed together, what they did); it
  feeds tavern gossip, the Ledger, and future visitors' discoveries.
