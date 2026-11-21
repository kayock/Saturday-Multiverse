# Milestone verification report — The Living Multiverse (1.5 / 2.0 / 2.5)

Build under verification: `0.2.5-living-multiverse`, schema
`saturday.core.v2`. This report distinguishes **executed** verification from
anything that could not be run in this environment. Nothing here is
projected or assumed.

## 1. Automated tests — executed, all passing

`python -m pytest tests/ -q` → **81 tests, 0 failures** (plus the
Milestone-1 smoke walk `scripts/smoke_test.py` → 35 checks, passing).

Coverage by area (all executed):

| Area | Tests | Notes |
|---|---|---|
| M1 regression (rules, packs, GM flow, AI adapter, HTTP API) | 50 | all pre-existing tests still pass, incl. the mock-AI end-to-end turn |
| **Database migration** | 2 | a genuine v1 save (built through the engine, pinned to `saturday.core.v1`) migrates to v2 with every row intact and continues playable; newer-schema databases are refused with a loud error |
| **Seeded generation** | 6 | determinism (same seed → identical identity), distinct seeds differ, complete identity (3 locations / 2 NPCs / 2 mysteries / relic / playable scenario with all choice targets resolving), version stamping, storage reuse, world travel + return clearing world context |
| **Signature scenario** | (in gen suite) | arrival → engage → refusal ending → quest done → echo offer created at profile level |
| **GM personalities** | 2 | default classic; noir persists in state, reaches the system prompt, colors fallback outcome lines; custom-without-text rejected; unknown styles rejected |
| **NPC memory & gossip** | 2 | tavern-scoped memory heard by Maren, NOT by Cardo; location guard; deterministic fallback lines; AI-off honesty flag |
| **Tide & wash-ashore** | 3 | exact 12-beat cycle (6 high / 6 low), reproducible spawn (same campaign+drift → same find), single pickup (guarded), no respawn on the same beat |
| **Tactical mechanics** | 5 | Risk declared pre-roll (+2, flag stored); Push band-bump with Vigor cost and once-per-roll; Push refused on Clean and on low Vigor; Resist halves harm with Nerve cost and refund; both rejected when inapplicable |
| **Death & echoes** | 2 | both-lamps-out concludes the character (actions refused), Remembrance echo created; Echo lifecycle: item + trait woven into a new voyage (inventory + skill verified), reuse refused, cap enforced |
| **Omen hand** | 2 | per-rest draw cap (2), hand cap (2), nerve cost, edge/turn play effects, complication refused, unknown card refused |
| **Upgrades & economy** | 2 | purchase requires beads + location; double-buy refused; Camp Kettle visibly changes rest (+5 total for a warden); purchased flag recorded |
| **Consequences & threads** | 5 | dedupe by trigger; surfaced in tavern gossip; Ninth Wave payoff at 4 clues unlocks the location (one-time gifts verified, no farming on re-entry); Wrong Gull payoff grants the rest perk; Salt-Grave ending grants echo offers + consequence + clue |
| **Ledger** | 1 | all eleven sections present and populated |
| **New HTTP endpoints** | 1 | styles, persona, talk, worlds generate/list, seeds, omen hand/draw, upgrades, echoes, ledger over Flask test client |

## 2. Browser-level verification — executed (Chromium, automated)

Flows driven through the real UI at 1440×900 and 1280×720:

- **Save migration live**: an untouched Milestone-1 campaign ("Maren Test")
  resumed through Continue on the v2 build — character, location, journal
  intact; gameplay continued without re-creation.
- **HUD additions**: tide clock dial with progress + beats-to-change,
  glassbead counter, Omens/Shore/Ledger nav buttons all render and function.
- **NPC conversations**: Talk button at camp; Cardo greeting + rumors;
  topic switching re-queries grounded gossip.
- **Seeded world journey (full UI path)**: canvas click on the magenta
  Unstable Door → seed gate modal → suggestion chips → "Clockwork Ocean" →
  *a new world answers* → step through → tinted arrival scene with hotspot,
  signature scenario choices → played to the refusal ending →
  **Echo modal opened automatically** → resume-after-reload lands mid-beat
  ("Arrival") with world context restored.
- **Tactical window**: risky manual roll → Push/Resist/Accept buttons appear
  → Push executed in UI → "1 Vigor spent… rises to clean" → window closes,
  state clean.
- **Shore improvements**: 6 beads granted through the engine → Shore panel
  lists six upgrades with costs/affordability → Camp Kettle built at camp →
  toast, bead deduction (6 → 4), purchase recorded; rate limiting observed
  working when the verification burst exceeded 30 AI-POSTs/min.
- **Wash-ashore**: a turn landing on an eligible beat spawned the find —
  dock strip "Something washed ashore: one perfect glassbead" → Pick it up →
  bead granted, strip cleared. (A state-clobbering bug found here was fixed
  and re-verified.)
- **Memory Ledger**: worlds/people/threads/consequences/echoes sections all
  populated from real play, chronological log intact.
- **GM persona switch** exercised via the Settings persona chips
  (persistence covered by tests).
- **Reduced motion**: calm mode toggle (settings) slows canvas time by 55%,
  suppresses rain particles, and clamps CSS animations; honors
  `prefers-reduced-motion` for UI animations.

Bugs found during browser verification, all **fixed and re-verified**:
stale server process serving v0.1.0 (process hygiene); `unstable` flag
missing from the doors view (hit-test dispatched travel instead of the seed
gate); `panelShore`/`panelWorlds` undefined (all drawers dead) — fixed,
plus **versioned asset URLs** (`?v=NN`) added to prevent stale-module
failures for self-hosters upgrading; world tint too aggressive (softened to
hue-rotate/3 + brightness); wet-sand crash on the 4th door; run_turn
clobbering the wash-ashore spawn.

## 3. Not run in this environment (stated honestly)

- **A live LLM as Game Master.** All AI-path verification ran against the
  bundled OpenAI-compatible mock model server (real HTTP, real JSON
  contract, real retries). Quality of narration with a real model depends
  on the model; the deterministic systems do not.
- **Windows hosting.** The stack is pure Python + Flask with `run.bat`, but
  only Linux was exercised here.
- **Audio** is synthesized and its controls verified in the UI, but no
  listening check was possible — verification is by code review and
  non-crashing playback paths only.
- **Multiplayer** remains schema + contract groundwork (Milestone 3 scope).

## 4. Acceptance criteria self-check

| Criterion | Status |
|---|---|
| Original game remains playable (M1 regression + migrated save) | ✅ |
| Living Shore visibly more interactive (tide clock, wash-ashore, 4th door, upgrade visuals, storm/rain, talk) | ✅ |
| NPCs remember actual events (scoped, grounded gossip) | ✅ |
| GM has distinct configurable personalities (7 + custom, persistent, tone-only) | ✅ |
| Multiple worlds via portals (deterministic seeds, persistent state, signature scenarios) | ✅ |
| Seeds and identities persist (generator version pinned; return visits resume) | ✅ |
| Decisions produce consequences (endings → echoes/consequences/gossip; threads → payoffs) | ✅ |
| Tactical mechanics work without AI authority (Risk/Push/Resist in engine) | ✅ |
| Upgrades persist and visibly affect gameplay (kettle rest, teal beam, map wall) | ✅ |
| Echo legacies work (ending offers → NG+ weaving, caps, reuse-block) | ✅ |
| Cross-universe influence through defined mechanics (consequences, clue threads) | ✅ |
| Journal is interactive (Memory Ledger with cards + chronological log) | ✅ |
| Old saves recoverable and compatible (additive migration, tested; backups) | ✅ |
| Runs without a paid AI provider (Offline Storyteller + deterministic systems) | ✅ |
| Windows/Linux instructions functional (launchers present; Linux executed) | ✅ Linux / ⚠️ Windows untested here |
| Tests and documentation included (81 tests + 8 docs) | ✅ |
| Complete ZIP delivered | ✅ `saturday-multiverse-living-multiverse-m2.5.zip` |

## 5. Known limitations

- Generated worlds share the shore's vignette art (tinted per archetype)
  rather than unique illustrations — a deliberate trade to ship six
  fully-playable archetypes now; hand-drawn per-archetype art is the natural
  Milestone 3 cosmetic.
- Wash-ashore spawns only through gameplay beats (turns/travels), never
  wall-clock time — by design ("do not force players to wait").
- The Relamp upgrade's "seed whispering" is represented by the suggestion
  list rather than dynamic in-fiction seed hints in this release.
- Push/Resist do not open for scripted fate checks (documented in RULES.md).
- Voice narration and multiplayer remain future milestones.
