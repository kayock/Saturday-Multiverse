# v0.4.0-hotfix3 — Final Release Hotfix verification (2026-11-22)

Build under verification: `0.4.0-living-worlds`, schema `saturday.core.v8`
(unchanged — the one new table is additive). Authoritative source: the
supplied hotfix2 ZIP
(`c1c943e640bb5fccc8d7ff37554b10b0bf5e5bad014e2fc5c8e7cd737cd40e8e`),
extracted into a clean tree; every hotfix1/hotfix2 correction confirmed
present before any change (their suites are included in the totals below).

## 1. Baseline — executed

- ZIP integrity: `unzip -t` clean, 103 entries, no errors.
- Recorded version `0.4.0-living-worlds`, schema `saturday.core.v8`.
- Full suite before any change: **228 passed** (matches the hotfix2 report;
  browser specs excluded, as before).

## 2. Confirmed defects — reproduced with failing tests first

All four review findings reproduced against the untouched hotfix2 code as
failing regressions in the new `tests/test_m42_hotfix3.py` (25 failures on
first run — every defect assertion failed; 7 preservation-style assertions
already held and pass unchanged):

| # | Defect | Reproduction |
|---|---|---|
| 1 | `share_knowledge()` blanket-copied the teller's entire `char_knowledge` (visited + discovery + heard) into party-wide `shared` rows on EVERY `add_story()` — an ordinary campfire story granted the party the teller's tavern hearing scope, including future rumors | `test_ordinary_story_shares_nothing`, `test_ordinary_story_grants_no_future_rumors`, `test_hearing_scope_cannot_be_shared_directly` |
| 2 | `recap()` fetched the newest 8 `npc_memories` and filtered AFTER the limit — hidden/unauthorized rows starved an older authorized rumor out of the window | `test_hidden_memories_cannot_starve_the_public_rumor` (20 restricted rows), `test_authorized_rumor_found_behind_hundreds_of_rows` (120 rows) |
| 3 | `_cert_names()` merged the CN into the SAN list, and `diagnose()` checked only expiry — CN-only certificates passed strict HTTPS validation, as did not-yet-valid certificates | `test_cn_only_certificate_is_rejected`, `test_dns_name_with_textual_ip_does_not_substitute_ip_san`, `test_not_yet_valid_certificate_is_rejected` |
| 4 | `tests/test_m41_tls.py` imported Unix-only `fcntl` (unimportable on Windows); `requirements-dev.txt` lacked `cryptography`, so the HTTPS tests could not run in CI; the CI browser job collected zero tests (`pytest tests/browser` is swallowed by the suite-level `collect_ignore_glob`) and passed vacuously | `test_ci_suite_has_no_unix_only_code`, `test_dev_requirements_install_the_tls_test_dependency` |

Root causes: (1) the sharing API had no selection concept at all — it
shared by identity, not by item; (2) the SQL window was assembled before
viewer entitlement was known, and entitlement cannot be expressed in that
window's SQL; (3) the certificate identity model conflated "names present
in the certificate" with "identities the certificate vouches for", and the
validity check used `days_left` (expiry only); (4) the test helper relied
on POSIX pipe semantics, and the dev requirements reflected only pytest.

## 3. Exact repairs

1. **`server/experience.py`** — `share_knowledge(cid, character_id, refs, …)`
   is now explicit and bounded: per-ref server-side validation against the
   teller's own `char_knowledge` (visited/discovery places; specific
   `npc_memories` by id, validated as genuinely heard); hearing scopes are
   refused ("select the specific memory instead"); GM/hidden/deep knowledge
   is refused under the same static rules the recap enforces. Grants write
   the existing `'*party*'` shared row format plus an auditable
   `knowledge_shares` ledger row (what, by whom, when, which story —
   `UNIQUE(campaign_id, ref)`, retries idempotent) and a `knowledge_shared`
   event. `add_story()` shares nothing unless `share_refs` is provided; the
   teller resolves through their OWN multiplayer row (spectators hold
   nothing). The recap entitlement gate honors exact shared memory ids and
   caps shared place/scope grants at the grant timestamp — future memories
   stay private. `shareable_knowledge()` powers the picker.
2. **`server/experience.py` (`recap`)** — static scope/kind rules filter in
   SQL; viewer entitlement gates candidates in a bounded backward walk
   (batch 64, hard cap 2000 scanned) that stops at the 8-item display
   budget. Markers, ordering, dedup, dismissal and solo-legacy behavior
   untouched.
3. **`server/tls.py`** — new `_cert_identities()` separates `san_dns`,
   `san_ips` (IP objects) and `cn` (diagnostics only; `_cert_names()` kept
   as a SAN-only compatibility list). `diagnose()` compares the exact
   timezone-aware UTC validity window (`not_valid_before` / `not_valid_after`,
   no day truncation) and matches identities browser-style: a name parsing
   as an IP is satisfied ONLY by an `IPAddress` SAN; DNS names match
   case-insensitively. Report gains `cn`, `san_dns`, `san_ips`, `has_san`.
   `ssl_context()` strict mode (the default whenever HTTPS is enabled)
   refuses not-yet-valid/expired/unreadable/key-mismatched/identity-less
   certificates before binding.
4. **CI** — `tests/test_m41_tls.py`: `Boot` captures subprocess output with
   a bounded background reader thread (no `fcntl`, no `os.set_blocking`, no
   blocking reads); `stop()` reaps child + collector. `requirements-dev.txt`
   installs `cryptography>=3.4` (production stays optional). `ci.yml`: the
   browser job now runs `pytest tests/browser/test_browser_flows.py`
   explicitly; the four flows pass. A regression test scans every CI-scheduled
   test module for Unix-only imports.

Related repairs in the same paths: the campfire browser spec's selectors
were fragile against the real UI (ambiguous accessible names; a
`get_by_role` name that never matched the input's accessible name) — it now
drives stable element ids and passes; the two hotfix2 tests that ENCODED
the blanket-sharing defect were rewritten to the explicit-sharing contract.

## 4. Test totals — executed

- Full suite: **260 passed** (228 baseline + 32 new in
  `tests/test_m42_hotfix3.py`), 0 failures.
- Browser acceptance flows (Chromium, real server): **4 passed**.
- `scripts/validate_packs.py`: all 4 world packs valid.
- `scripts/preflight.py`: all checks passed.
- `scripts/smoke_startup.py`: production WSGI smoke OK.
- `scripts/verify_hotfix3_lan.py`: **35/35 checks passed** — see §5.
- JavaScript: `node --check` clean for every `client/js/*.js`.

## 5. Live LAN verification (real servers, real certificates)

`scripts/verify_hotfix3_lan.py` extends the hotfix2 LAN script: cert_setup
CLI (generate → diagnose → renew), Case B direct HTTPS with a CA-verifying
client (no `verify=False` anywhere), explicit campfire sharing over HTTPS
(picker → exact grant → guest's recap → ledger row), SSE over direct HTTPS,
restart persistence of the share ledger, CN-only and not-yet-valid
certificates REFUSED at startup with actionable banners, Case A plain HTTP
unaffected, Case D production truthfulness, and a genuine
**hotfix2 → hotfix3 migration**: a database created by the pristine hotfix2
tree reopens under this tree — campaigns intact, events intact,
`knowledge_shares` present, schema marker still `saturday.core.v8`.

## 6. Not executed here (honest limitations)

- The GitHub Actions matrix itself (ubuntu/windows × Python 3.10/3.12) did
  not run — no GitHub execution from this environment. The Windows legs are
  verified at the code level: no Unix-only imports remain in any
  CI-scheduled test (enforced by test), the subprocess collector uses only
  portable primitives, and requirements install the TLS dependency. Do not
  report the Windows legs as green until the workflow has run on GitHub.
- Model/AI-provider paths were exercised only via the offline storyteller
  and mock server, as in all prior milestones.

# v0.4.0-hotfix5 — Final Release Hotfix verification (2026-11-22)

Build under verification: `0.4.0-living-worlds`, schema `saturday.core.v8`
(unchanged — hotfix 5 changes disclosure policy, not structure).
Authoritative source: the supplied hotfix4 ZIP
(`b47725a705625976c9c48c1b5f32802e8077bfc6599e1e979b27cf520de8a938`),
extracted into a clean tree; the full hotfix4 suite passed before any
change.

## 1. Baseline — executed

- ZIP integrity clean; SHA-256 above identical to the delivered hotfix4
  package. Versions: app `0.4.0-living-worlds`, schema `saturday.core.v8`.
- Full suite before any change: **285 passed** (matches the hotfix4 report).

## 2. Confirmed defects — reproduced with failing tests first

New `tests/test_m44_hotfix5.py` (25 tests): **13 failed** against the
untouched hotfix-4 source — every defect assertion reproduced the review's
findings; 12 preservation assertions already held.

| # | Defect | Reproduction |
|---|---|---|
| 1 | `recap._mem_entitled` kept `scope in own_places → True`: past presence authorized memories created later — the recap revealed rumors the picker (correctly) refused | `test_earlier_visit_does_not_reveal_later_rumor`, `test_rumor_visible_after_actual_delivery` (first half), `test_split_party_recaps_remain_distinct` |
| 2 | `talk()` used the NPC's whole internal collection for dialogue, AI prompts, acquisition and the API response — a GM-only deep secret was quoted aloud, returned to the browser, and recorded as learned | `test_gm_deep_memory_excluded_from_talk_response` (the response carried the secret verbatim), `test_gm_memory_not_recorded_as_acquired`, `test_merely_retrieving_candidates_grants_nothing`, `test_ai_prompt_contains_no_unauthorized_secret`, `test_conversation_acquisition_is_exact_not_blanket` |

Root causes: (1) the recap entitlement still trusted presence/scope as
knowledge; (2) internal NPC knowledge, conversation candidates, revealed
information and character acquisition were one undifferentiated collection
in `talk()`.

## 3. Exact repairs

1. **`server/experience.py`** — `_mem_entitled` rewritten: a character
   receives a memory they acquired, one exactly party-shared, a
   timestamp-capped historical grant, or truly public news — never based on
   presence or an old hearing scope. Static kind/scope restrictions still
   filter in SQL first (a public scope can never surface a restricted
   kind). New `reveal_memory()` is the explicit engine-authorized story
   event for scripted revelations (optional scope relabel; kind
   restrictions always dominate).
2. **`server/legacy.py`** — `_conversation_candidates()` filters internal
   retrieval through the same static player-facing rules as recap/sharing;
   `_gossip_lines()` returns the exact records quoted into spoken lines
   (tracked by construction); `talk()` builds dialogue and AI prompts from
   candidates only, validates AI-declared `disclosed_ids` against the
   candidate set (restricted/unknown/forged dropped; no declaration → no
   acquisition), records ONLY disclosed memories, returns only disclosed
   entries in `memories` (same entry shape — client unchanged), and logs
   `npc_talk` events with disclosed ids only.
3. **Tests encoding superseded contracts** — four hotfix2/3 tests (presence
   = hears tavern talk) updated to record the engine's delivery; hotfix-4
   talk tests switched to disclosure-triggering topics ("rumors" reaches
   Maren's stock lines, which disclose nothing — by design); the hotfix-4
   LAN script's two talks likewise.

## 4. Unified-knowledge audit (§7) — executed

`_memories_for` (internal only; single caller), `_gossip_lines`
(disclosure-tracked), `talk`, `note_memory`, `_memory_entitlement`,
`shareable_knowledge`, `share_knowledge`, `recap`, `campaign_talk` all
agree: acquisition = delivered/revealed/shared/public; presence never
grants. Secondary flows audited: HTTP response bodies (disclosed entries
only), AI prompts (candidates only), transcripts (spoken lines only),
game events (ids only), multiplayer SSE messages (names only), recaps,
journals, campfire sharing, spectator views, Engine Trace — no internal
record text reaches any of them (asserted in tests and re-verified live).

## 5. Test totals — executed

- Full suite: **310 passed** (285 baseline + 25 new), 0 failures.
- Browser acceptance flows (Chromium, real server): **4 passed**.
- `scripts/validate_packs.py`: all 4 world packs valid.
- `scripts/preflight.py`, `scripts/smoke_startup.py`: passed.
- `scripts/verify_hotfix5_lan.py`: **29/29** — direct HTTPS with a
  CA-verifying client: the Lampkeeper's GM-only deep secret absent from the
  conversation response, char_knowledge, transcripts, events, picker and a
  direct share attempt; Maren's conversation disclosing exactly one record;
  exact party share reaching B's recap; the later rumor hidden until
  actually heard; restart persistence; solo disclosure-tracking over plain
  HTTP.
- `scripts/verify_hotfix4_lan.py`: **26/26**; `verify_hotfix3_lan.py`:
  **36/36**.
- `node --check` clean for every `client/js/*.js`; `compileall` clean.

## 6. Not executed here (honest limitations)

- The GitHub Actions matrix (ubuntu/windows × Python 3.10/3.12) did not
  run — no GitHub execution from this environment; Windows legs remain
  code-verified only.
- Live AI model: unavailable here. AI dialogue paths were exercised via
  monkeypatched `ai.chat` in unit tests (prompt capture, declaration
  validation, malformed responses) — clearly labeled mocks, not live
  results. The offline Storyteller paths run in the standard suite.
- Hotfix-4-era saves may carry over-acquisition rows (documented in
  `docs/MIGRATION.md`): inert for restricted material, ordinary-rumor rows
  left in place rather than risking legitimate progress.

# v0.4.0-hotfix4 — Final Release Hotfix verification (2026-11-22)

Build under verification: `0.4.0-living-worlds`, schema `saturday.core.v8`
(unchanged — hotfix 4 adds a new `char_knowledge` KIND value, not a table).
Authoritative source: the supplied hotfix3 ZIP
(`c0e8df9ef30568e9d2de15e92138177d94f1321e838dc42d406fceec9de183b8`),
extracted into a clean tree; the full hotfix3 suite passed before any
change.

## 1. Baseline — executed

- ZIP integrity clean; SHA-256 recorded above and identical to the
  delivered hotfix3 package.
- Full suite before any change: **260 passed** (matches the hotfix3 report).

## 2. Confirmed defects — reproduced with failing tests first

New `tests/test_m43_hotfix4.py` (25 tests) failed 17-fold against the
untouched hotfix3 code — every defect assertion reproduced the review's
findings; the remaining assertions were preservation checks that already
held.

| # | Defect | Reproduction |
|---|---|---|
| 1 | `campfire_shareable()` caught ANY `_mp_resolve()` exception as "solo" → `teller_character(cid, None)` fell back to the campaign's main character → a missing/invalid/revoked token received another character's shareable discoveries and memories | `test_picker_without_token_is_refused`, `test_picker_with_invalid_token_is_refused`, `test_picker_with_revoked_token_is_refused`, `test_picker_with_removed_player_token_is_refused`, `test_picker_with_wrong_campaign_token_is_refused`, `test_unauthorized_picker_cannot_fall_back_to_main_character` |
| 2 | shareability was decided by a hearing SCOPE — a character with `heard:'tavern'` was offered and could share tavern rumors created after they left | `test_future_rumor_is_not_shareable_after_leaving`, `test_unacquired_memory_id_is_refused_without_a_scope`, `test_other_character_acquisition_is_not_claimable`, plus the picker assertions of `test_talk_acquires_exactly_the_delivered_rumors` |

Root causes: (1) the endpoint conflated "multiplayer authorization failed"
with "this is a solo campaign" in one broad `except Exception`; (2) the
entitlement rule tested scope membership (`scope in own/heard`) instead of
per-memory delivery evidence.

## 3. Exact repairs

1. **`server/api.py`** — `campfire_shareable` now distinguishes session
   state from authorization failure: `_mp_resolve` is called normally;
   `mp.MpDenied` → 403 (no knowledge content in the response); the campaign-
   character fallback runs ONLY when no multiplayer session exists. The
   campfire POST path was audited and already refuses unauthorized tokens
   (403 via the blueprint handler) and resolves the teller through their own
   campaign-scoped player row. `campaign_talk` now resolves the teller by
   session state too (authenticated player's own character; campaign
   character only for a session-less solo request; a spectator's None teller
   learns nothing).
2. **`server/experience.py`** — new `note_memory()` records specific memory
   acquisition (`char_knowledge` kind='memory'); `_memory_entitlement()`
   (acquired record OR existing party-wide memory grant) is the single
   source of truth used by BOTH `shareable_knowledge()` (picker) and
   `share_knowledge()` (engine). `all`-scoped public news stays shareable by
   any party member. Memory grants at the campfire now write acquisition
   rows for every campaign character (idempotent). `_viewer_context` gains
   `own_memory_ids` and the recap entitlement gate honors them (a learned or
   received rumor surfaces in the recipient's recap).
3. **`server/legacy.py` / `server/gm.py`** — authoritative delivery points:
   `talk()` records the memories the conversation delivered (character
   resolved by the caller); `remember()` returns the new memory id;
   campaign-creation and character-join arrival tales and the camp
   guestbook's visitor tale are recorded as learned by the character who
   actually experienced them.
4. **Tests encoding the old contract** — four hotfix2/3 tests that relied
   on scope-based shareability were updated to record acquisition through
   `note_memory` (the same primitive the delivery points call) before
   sharing, with new negative assertions that unacquired memories are
   refused.

## 4. Privacy audit (§6) — executed

- Identity: every knowledge path resolves the character from the session
  token; no endpoint accepts a character id from the request body; player
  row lookups are campaign-scoped.
- Cross-campaign: all `char_knowledge` / `npc_memories` /
  `knowledge_shares` queries are campaign-scoped; a Campaign-A memory id
  shared into Campaign B is refused and writes nothing (tested, and
  re-verified live over HTTPS).
- Forged references: unknown `mem_*`/`kn_*`/garbage refs are refused with
  zero state change (tested, and re-verified live).
- Error responses: 403 messages carry no character ids or knowledge text
  (asserted in tests).
- Spectators: no character row → no acquisition, empty picker, share
  refused (tested live).
- Recap feed: `kind='memory'` rows never render as ledger items; they
  surface through the rumor feed under their own entitlement gate.

## 5. Test totals — executed

- Full suite: **285 passed** (260 baseline + 25 new), 0 failures.
- Browser acceptance flows (Chromium, real server): **4 passed**.
- `scripts/validate_packs.py`: all 4 world packs valid.
- `scripts/preflight.py`, `scripts/smoke_startup.py`: passed.
- `scripts/verify_hotfix4_lan.py`: **26/26** — direct HTTPS with a
  CA-verifying client: real tavern conversation delivering Rumor 1,
  picker authorization (403 without token, no fallback), exact party-share
  grants, forged-reference refusals, return-visit acquisition of Rumor 2,
  restart persistence, and genuine solo flows over plain HTTP without any
  token.
- `scripts/verify_hotfix3_lan.py`: **36/36** (its share step now shares the
  host's own acquired arrival tale; two checks updated to hotfix-4
  authorization semantics).
- `node --check` clean for every `client/js/*.js`; `compileall` clean.

## 6. Not executed here (honest limitations)

- The GitHub Actions matrix (ubuntu/windows × Python 3.10/3.12) did not run
  — no GitHub execution from this environment; the Windows legs remain
  code-verified only (unchanged since hotfix 3: no Unix-only imports,
  portable subprocess handling, dev requirements install the TLS
  dependency).
- Live AI-model paths were exercised only via the offline storyteller and
  the mock server, as in all prior milestones. The AI-enriched talk branch
  is failure-isolated and records the same delivered memory records in both
  modes.

# Milestone verification report — The Infinite Library (3.5)

Build under verification: `0.3.5-infinite-library`, schema `saturday.core.v4`.
Previous milestones' verification (1.5–3.2) remains valid and its suites
are included in the totals below. This report distinguishes **executed**
verification from what could not be run here.

## 1. Automated tests — executed, all passing

`python -m pytest tests/ -q` → **131 tests, 0 failures**
(110 from Milestones 1–3.2 + 21 new for 3.5, including 3 parametrized
starter-pack playthroughs), plus the solo smoke walk passing.

| Area (all executed) | Tests |
|---|---|
| Import of every format — TXT/MD, HTML, DOCX (headings preserved), EPUB (metadata into the record), PDF (reportlab-generated fixture via pypdf) | 1 |
| Source verbatim storage + library delete removes the original | 1 |
| Long-document retrieval: 300-chapter book; the "chapter 217" needle surfaces; rotating-window fallback | 1 |
| Hostile inputs: fake DOCX (not a zip), XXE-entity DOCX, 41 MB upload, garbage base64 — refused or handled, never 500 | 1 |
| Hidden GM secrets from packs become hidden facts, absent from views/streams | 1 |
| Forge pipeline end-to-end with a mock model: extract → synthesize → validate CLEAN → approve → installed pack loads in the engine → the story plays headless to an ending | 1 |
| Forge alternate mode + section regeneration keeps packs valid | 1 |
| Forge refuses to approve a sabotaged draft (validation blocks) | 1 |
| Forge requires a configured model and says so honestly | 1 |
| Private-manuscript flow (Roanoke path): private flag, stored under userdata, host-only visibility | 1 |
| D&D character creation on a library pack; d20 checks; band mapping (nat20/nat1/DC bands) | 1 |
| D&D long rest restores slots + HP; XP → level 2 | 1 |
| Ruleset isolation: Undertow unchanged (omens, views, dnd=None) | 1 |
| Starter packs play to endings: Dracula (beacon), Rue Morgue (exoneration), Time Machine (home) | 3 |
| Starter-pack licensing: author, public-domain status, Gutenberg source URL embedded | 1 |
| Hidden-information boundary on a library pack: secrets absent from events and views | 1 |
| Multiplayer aboard an imported adventure: two clients, serialized actions, chat, party travel by vote | 1 |
| Multiplayer join into a D&D campaign: both sheets correct | 1 |
| v4 migration preserves campaigns and the library tables work | 1 |
| Prior-milestone suites (solo, multiplayer, migrations, security) | unchanged, all passing |

## 2. Live end-to-end gameplay — executed

- **Imported literary adventure, engine-only**: each starter pack was
  created as a campaign and walked choice-by-choice to a real ending
  (sunrise in Whitby, exoneration in Paris, home in 802,701) in the
  parameterized tests above — genuine mechanical playthroughs, not demos.
- **Multiplayer + library pack**: a hosted *Dracula* session with two
  independent clients acting, chatting, and traveling by vote.
- **D&D on a literary pack**: a cleric created directly on *Dracula*,
  d20 checks, long rest at the sanatorium restoring spell slots.
- **Forge with a live model**: NOT run here — the sandbox has no live
  LLM configured. The pipeline was verified with a deterministic mock
  model through every stage, including the honest no-model refusal.
  Live-model verification follows the same contract as the mock (JSON
  contracts, bounded calls) but is explicitly **not claimed**.

## 3. Browser verification — executed (Chromium)

- Title screen shows **The Infinite Library**; the Library screen lists
  installed adventures (starter packs) and the stacks.
- The adventure preview shows places, cast, story shape, and the
  licensing block with source URL.
- Campaign creation offers the **pack picker** (every installed adventure
  is a door) and the **ruleset toggle** (Undertow 2d6 / D&D-compatible)
  with class/species/background fields for D&D.

## 4. Not tested in this environment (stated honestly)

- **A live LLM in the Forge/GM**: mock-model verification only; no live
  model was available in the sandbox.
- **A real large PDF/EPUB** (actual Gutenberg downloads): exercised with
  format-accurate generated fixtures instead; Gutenberg URLs are recorded
  but the books were not downloaded in the sandbox.
- **Windows**: Linux only; launchers and waitress production mode written
  for both but not executed on Windows.
- **Roanoke**: no manuscript was supplied; per instructions nothing was
  fabricated — the private-import flow is built and documented.
- Cross-server federation remains out of scope (Milestone 4).

## 5. Acceptance self-check

| Criterion | Status |
|---|---|
| Ordinary user: import a book without editing code | ✅ (Library → Import) |
| Convert it into a playable campaign | ✅ (Forge → approve → door) |
| Open a portal and begin, solo or multiplayer | ✅ (preview → portal → creation; shared sessions verified) |
| Preserve every existing system (solo, multiplayer, Undertow, saves) | ✅ (131 tests incl. all prior suites) |
| Engine authoritative; AI narrates/proposes only | ✅ (forge drafts require human approval; GM never writes state) |
| Save compatibility | ✅ (additive v4 migration, full chain tested) |
| Licensing recorded and separated (SRD vs literature vs private) | ✅ (LICENSES.md + per-pack blocks) |
| Distribution | ✅ `saturday-multiverse-infinite-library-m3.5.zip` |


# v0.3.6 — Living Campaign verification (2026-11-21)

**159 tests green** (`python3 -m pytest tests/ -q`), including 28 new v0.3.6
tests. Two suites run everything from engine rules to full multiplayer
scenarios with real HTTP clients against a real server instance.

## What was verified

### Critical D&D repairs (Part 2 of the assignment)
- HP persistence: damage carries between encounters; the next encounter
  starts from current HP, never `hp_max` (dedicated test + manual runs).
- Player control: initiative order, own-turn-only actions, attack / cast
  (slot consumption) / defend / item / retreat / stabilize all exercised.
- Death without resurrection: death saves, stabilisation, death, and a dead
  character refused re-entry to combat. The old auto-resolver path is gone.
- Rewards exactly once (XP + level-up), including a direct double-finish probe.
- Timeout: an idle turn is auto-defended by the sweep and the turn passes.
- Restart survival: an active encounter is playable from a brand-new app
  instance (process restart), state intact.
- Coverage table served at `/api/rules/dnd/coverage`; unsupported options are
  never offered.

### Multiplayer (Part 3)
- Split party: per-character locations, location-scoped narration (a split
  character's discovery is invisible to the party focus and to spectators),
  regroup (self and host-forced), shared travel regroups by default.
- Spectators: observe only — action/choose/check/travel refused (400/403);
  reconnect works; secrets never appear in their event stream.
- Shared combat: turn-by-turn multi-player control, forged ownership refused
  (403), reinforcements round one.
- Watchdog: expired structured turns advance server-side; combat idle turns
  auto-defend; both survive restart.
- Duplicate actions: `once`-flagged effects re-applied do not double-grant.

### Infinite Library (Part 4)
- Full-novel coverage: a 300-chapter source processed 300/300 chunks across
  13 windows; early/middle/late material all extracted; the world bible
  records the source's ending; flow validation clean; installed and playable.
- Resumable jobs: a failed bible stage preserves the extraction; retry
  resumes with ≤3 model calls instead of re-reading the book.
- Duplicate characters (name/alias/case variants) merge deterministically.
- Manual editing: ops apply, every save is a revision, restore returns the
  earlier state, compare reports changes; broken flow graphs are detected
  (missing targets, unreachable scenes, no reachable ending).
- Safe retrieval: matching context returns the needle chapter; no-match
  context returns NOTHING (the rotating-window fallback is gone); a story
  horizon blocks future chapters.
- Private content: private imports stay in `userdata/library`, never in the
  redistributable packs.

### Director & continuity (Part 5)
- Threads seeded from quests/secrets move only on authoritative events, with
  evidence; suggestions are advisory and silenced in `off` mode; continuity
  catches dead-then-speaking and quest reversals.

### Collaborative worldbuilding (steering addition)
- Three participants (locations / NPCs / quests) on existing multiplayer
  identities; creator reviews and applies; a review-time conflict is refused
  until explicitly force-applied, and BOTH contributions survive (nothing
  silently overwritten); AI suggestions never auto-apply; a contributor sees
  their own GM secret while another contributor does not; approval is
  creator-only and gated; the installed world appears as a playable pack and
  hosts a multiplayer voyage; contributions persist across a restart; private
  sources stay private and no publishing path exists.

### The Dracula acceptance scenario (phases 1–8)
Four genuine independent API clients (plus a fifth spectator connection) run
the whole mandated scenario: arrival with four owned sheets → split party
with private discoveries → Director tracking → regroup → tactical D&D combat
with individual control and ownership enforcement → spectator observation
with secret filtering → disconnect/reconnect with watchdog recovery and no
duplicated characters → ending path, ledger, memories, checkpoint.

**Reported limitation:** the sandbox has no graphical desktop, so the four
clients are real HTTP/API clients through the production server rather than
four browser windows. Every engine path, permission boundary and persistence
effect they exercise is the same one the browser uses.

## Environment limitations, reported honestly
1. **No live AI model** in this environment. Model-dependent stages (GM
   narration, forge extraction/bible/adventure, suggestions) are verified
   against a deterministic mock bound to the same JSON contracts the real
   client uses; the offline storyteller keeps everything playable without a
   model.
2. **Project Gutenberg was down for maintenance** during the build (all
   mirrors tried: gutenberg.org, files, aleph, uwaterloo — maintenance page
   or 404). The real-book pipeline was therefore verified at novel scale with
   a generated 300-chapter source plus the user-supplied-file import path;
   the attempt is reproducible with `scripts/` once Gutenberg returns, or
   immediately with any local .txt/.md/.pdf/.epub via Library → Import.
3. The four-client acceptance uses API clients (see above), not four
   graphical sessions.


## Independent maintenance review — v0.3.6 startup / Workshop patch

This additional source-level review follows the original release report and does **not** replace its 159-test claim.

Two defects in the shipped code were corrected:

1. `server.app` previously called an undefined module-scope `app.run(host=HOST, port=PORT)` in `__main__`, bypassing `main()` and breaking both normal launch scripts. The patched entrypoint uses `main()` in both serving modes and starts the in-process watchdog before the server blocks.
2. `forge.collab_view()` previously redacted `ops_json` for secret-containing proposals but still exposed the original parsed `ops`. The patched view redacts the returned operations and note for other contributors; nested secret paths are covered and creator/author visibility is retained.

Regression tests added to `tests/test_release_fixes.py`. In the independent review environment, two Workshop privacy tests passed. Three Flask-dependent tests were skipped because Flask was not installed; an isolated startup/watchdog smoke test using stub server interfaces confirmed `main()` calls the watchdog in both development and production modes and the tick calls both timeout sweepers. Python source compilation also passed. This is **not** a substitute for a real Flask/Waitress launch and the full 159+ test suite in a proper runtime, which remain unverified in this environment.


# v0.4.0 — The Living Worlds verification (2026-11-21)

**Development base:** GitHub `main` at
`08f80b3ef5c118fb48b42ab41961680057ca559d` (the published v0.3.6 release with
launcher/watchdog/Workshop-privacy hotfixes). Clone verified; hotfixes
confirmed present (`tests/test_release_fixes.py`, `_start_watchdog` in
`server/app.py`, Workshop proposal redaction).

**Test counts:** 180 automated tests pass (`pytest tests/ -q --ignore=tests/browser`)
— 164 pre-existing (all preserved) + 16 defect regressions + 6 engagement
acceptance tests. Browser specs (Playwright) live in `tests/browser/` and run
as a separate CI job.

## Defect investigation results (A/B of the report)

| Finding | Verdict | Root cause | Repair | Test |
| --- | --- | --- | --- | --- |
| 4.1 Solo combat POST rejected | CONFIRMED (403 reproduced) | `combat_act` resolved chid only from mp sessions | solo fallback to the campaign character; mp ownership unchanged | `test_solo_combat_action_submission` |
| 4.2 Invalid spell target consumed a slot | CONFIRMED (slot 2→1 reproduced) | `cast_spell` ran before target validation | all preconditions validated before consumption | `test_invalid_spell_target_preserves_slot` |
| 4.3 Replay starvation >500 invisible events | CONFIRMED (0 visible returned) | LIMIT 500 fetched then filtered | `events_since_page` cursor-advancing bounded pagination + client cursor | `test_replay_survives_501_invisible_events` |
| 4.4 Interrupted Forge jobs stuck | CONFIRMED (retry refused) | no worker ownership; watchdog claims only `queued` | schema v6 lease (owner/heartbeat), atomic single-winner claims, 15 s heartbeat, 90 s stale recovery preserving artifacts, startup recovery | `test_interrupted_job_recovers_after_restart` |
| 4.5 Rejected actions advanced the clock | CONFIRMED (turn 0→1 while dead) | turn UPDATE preceded the dead check | validation before every state-consuming step | `test_rejected_actions_do_not_advance_the_clock` |
| 4.6 FTS5-less startup failed | CONFIRMED by inspection (unguarded `search_index` creation) | one of two fts5 scripts unguarded | `_try_fts` guards both, warning logged, LIKE fallback, `/api/health` indicator | `test_startup_without_fts5` |
| 4.7 source_horizon never established | CONFIRMED (single read-site, no writes) | mechanism existed but nothing drove it | bind at creation/travel by title/author; advance on scene progress/discoveries/endings | `test_story_horizon_blocks_late_revelation` |
| 4.8 Extraction sampled ~30% of text | CONFIRMED (1399-char chunks, 420-char prefix) | chunk-count windows with `[:420]` slices | character-bounded windows, chunk slicing, honest coverage counters | `test_extraction_beyond_chunk_prefixes` |
| Workshop privacy (5.2) | Already fixed in 08f80b3 | — | re-verified by the existing hotfix tests | `test_workshop_*` (passing) |
| Reward idempotency (5.3) | Already fixed in v0.3.6 | — | re-verified | `test_combat_reward_idempotency` |

## Engagement acceptance (16.4) — verified via API tests AND live browser

- Returning-player recap: real victory cited in the recap; dismissal recorded.
- Goals: engine events auto-credit; personal scope; abandon.
- Campfire: player-authored stories stored separately; continuity ignores them.
- What-If Timelines: branch isolated (trunk turn/beads/inventory untouched,
  separate event streams), comparison shows inventory + turn divergence.
- Engine Trace: action → rule/dice → effects → narration source; no GM-only
  leakage (asserted against the pack's hidden secrets).
- Playtest portal: isolated campaign, report generated, stop archives cleanly.
- Interactive tutorial: renders on first visit in a real browser; skippable.
- Accessibility: reduced-motion/high-contrast body classes, focus-visible
  outlines, aria-live narration.

**Live browser verification (agent-browser/Chromium, this environment):**
title + first-run tutorial, D&D voyage creation, Engine Trace panel after an
action ("TURN 1 — HOW THE RULES RESOLVED IT" with honest narration source),
Ledger sections (Checkpoints/Goals/Campfire/Timelines), timeline branch via
API + campaign-list entry, "The shore remembers" recap banner with dismiss,
Workshop playtest buttons ("Playtest portal open — a test campaign was
created"), screenshots in `docs/screenshots/`.

## Reliability verification

- `scripts/preflight.py`: all checks PASS in this environment (FTS5 present,
  packs valid, data dir writable; model correctly reported unconfigured →
  Offline Storyteller).
- `scripts/validate_packs.py`: all 4 world packs valid.
- `scripts/smoke_startup.py`: the real server process boots, serves
  `/api/health`, terminates cleanly (production startup path, not a test
  client).
- Backup/restore: `POST /backup` snapshot reproduces character state (beads=12)
  and the exact event-sequence maximum; restore endpoint 200 (WAL-safe
  `sqlite3.backup`).
- CI workflow (`.github/workflows/ci.yml`): Linux+Windows × Python 3.10/3.12,
  compile + JS checks + pack validation + pytest + startup smoke + Playwright
  browser job. Runs in GitHub Actions on push; not executed here (no GitHub
  runners locally).

## Honest limitations (G of the report)

- The Playwright specs run in CI but were not executed locally; local browser
  verification used an equivalent real-Chromium tool (agent-browser) as
  documented above. Nothing in this report claims the CI jobs ran.
- No live AI model is configured in this environment: model-dependent stages
  use the deterministic mock bound to the same JSON contracts; the Offline
  Storyteller covers play. No live-model test was performed or claimed.
- GitHub is not pushed by this delivery: the release is a reviewed ZIP + this
  report, per the assignment's publication rule.
- "Use browser clients where possible" for the multiplayer acceptance: the
  eight-phase Dracula scenario uses genuine independent API clients through
  the production server (documented since v0.3.6); the new Playwright specs
  add real browser sessions for solo flows. Four simultaneous graphical
  sessions were not run in this sandbox.


# v0.4.0-hotfix1 — LAN HTTPS & Reliability verification (2026-11-21)

**Base:** the supplied `saturday-multiverse-living-worlds-v0.4.0.zip`, verified
byte-identical to the v0.4.0 development tree before work began (diff: no
differences). Existing suite re-run first: **180 passed**.

**Final counts:** **197 passed** (`pytest tests/ -q --ignore=tests/browser`)
— 180 preserved + 9 privacy/integrity regressions (`tests/test_m40_hotfix.py`)
+ 8 LAN/HTTPS integration tests (`tests/test_m40_lan.py`). Also re-run from a
fresh extraction of the final ZIP.

## Defect investigations

| Finding | Verdict | Root cause | Repair | Test |
| --- | --- | --- | --- | --- |
| Recap leaked deep-scoped NPC secrets | CONFIRMED (memory query had no scope filter) | `SELECT npc_id, text FROM npc_memories` without scope/kind filtering | scope whitelist (`all/camp/doors/tavern`) + blocked kinds (`secret/hidden/gm/host`) | `test_recap_never_leaks_deep_scoped_secrets` |
| Recap replayed pre-dismiss history | CONFIRMED (`_recent()` always True; achievements chosen without a marker) | no last-seen filter; mixed identifier spaces | per-table **rowid** markers written at dismissal; "new" strictly after marker | `test_recap_respects_last_seen_marker` |
| Old recap data migration | REPAIRED proactively | `recap_seen_turn` could not map to event rows | derive the engine-events rowid from the last turn ≤ seen turn; persist once (lazy); never-dismissed campaigns unaffected | `test_recap_marker_migrates_from_old_saves` |
| Cross-campaign goal mutation | CONFIRMED (`UPDATE … WHERE id=?` without campaign) | `abandon_goal` ignored the supplied campaign | every mutation scoped + verified to the campaign; mismatch → rejection, no data change; API returns 404 | `test_cross_campaign_goal_mutation_is_rejected` |
| Fabricated verified progress | CONFIRMED (endpoint accepted arbitrary deltas as engine progress) | no distinction between player-authored and engine-verified progress | schema v7 `verified_progress`/`last_source`; endpoint hard-wired `verified=False`; only `auto_credit` writes verified progress | `test_manual_progress_cannot_fabricate_verified_achievements` |
| Guest could alter another player's personal goal | CONFIRMED (no ownership check) | personal goals had no access control | owner/host/local-only mutations; forged-ownership creation refused | `test_personal_goal_ownership_for_guests` |
| Cross-campaign checkpoint/timeline refs | CONFIRMED (branch accepted foreign checkpoint ids) | no ownership check in `branch_campaign` | checkpoint must belong to the campaign | `test_cross_campaign_checkpoint_and_timeline_references` |
| Duplicate recap entries | CONFIRMED | identical texts appended twice | normalized-text dedup | `test_recap_no_duplicate_entries_and_solo_still_works` |
| Invalid goal requests mutate state | CONFIRMED (malformed delta crashed; missing goal → 400 not 404) | route-level validation | 400 for malformed delta, 404 for missing goal, zero/negative clamped | `test_invalid_goal_requests_leave_state_unchanged` |

## LAN verification (real servers, not the test client)

Boot: `SATURDAY_HOST=0.0.0.0` on free ports; clients connect via the machine's
non-loopback address (`21.0.7.32` in this sandbox — a real network interface,
not `localhost`) or loopback where the server is bound to it.

- HTTP: title/static assets, solo create → act → **resume** (turn increments
  across requests), Engine Trace present, Library/Forge/Workshop/Director
  endpoints reachable — `test_lan_http_solo_full_flow`.
- Multiplayer: host → start → invite → join → guest acts → event replay with
  cursor — `test_lan_http_multiplayer_flow`.
- SSE: stream delivers in-order events; reconnection from the highest seq
  does not replay seen events — `test_lan_http_sse_stream_and_reconnect`.
- **Solo LAN play requires no lobby** (asserted: a plain solo voyage acts and
  resumes via a remote-address client).

## HTTPS verification (normal certificate verification — no `verify=False`)

- `scripts/cert_setup.py generate` creates the local CA + server certificate
  (SANs: localhost, 127.0.0.1, hostname, all non-loopback LAN IPv4 addresses;
  825-day server cert, 10-year CA; key permissions 0600 on POSIX).
- `SATURDAY_TLS=1` boots HTTPS; clients verify with
  `ssl.create_default_context(cafile=CA)`:
  - assets + `/api/health` (`tls.certificate_ok: true, days_left: 824`),
  - solo create/act/resume over HTTPS — `test_https_real_certificate_verification`,
  - multiplayer host/join + SSE reconnection over HTTPS —
    `test_https_multiplayer_and_sse`,
  - invitation links derive scheme/host from `location.origin` (asserted).
- Failure modes: TLS without a certificate fails loudly with the fix command;
  a mismatched key/certificate pair and missing files produce clear
  diagnostics (`test_https_certificate_diagnostics_and_http_compat`,
  `test_https_no_certificate_fails_loudly`).
- HTTP backward compatibility: with `SATURDAY_TLS` unset, the same data
  directory serves plain HTTP normally and `/api/health` carries no TLS
  field; game data untouched.
- Production modes verified: waitress plain HTTP banner; waitress+TLS prints
  the reverse-proxy guidance (or boots the TLS dev server with
  `SATURDAY_TLS_DEVSERVER=1`); `SATURDAY_TRUST_PROXY` is opt-in only.
- Preflight: `scripts/preflight.py` reports the certificate (days left, SANs)
  in both enabled and not-enabled states.

## Trust-model notes (documented for approval, not silently changed)

1. **Read endpoints** (`/recap`, `/goals`, `/campfire`,
   `/timelines/compare`) are readable by any LAN client for a given campaign
   ID — the same access model as `GET /api/campaigns/<cid>` since v0.2.5.
   Player-aware filtering (recap) applies whenever a session token is
   presented. Restricting these to session members would be a NEW
   authentication restriction and is documented here for approval rather
   than implemented silently.
2. **Local-trust boundary:** campaigns without an active multiplayer session
   accept local requests without tokens (solo play from any LAN device relies
   on this); campaigns WITH a session require valid tokens for actions
   (the established CSRF-equivalent). Unchanged.

## Honest limitations

- **Physical LAN devices:** this environment has no second physical device;
  verification used real servers and real network clients through the
  machine's actual non-loopback interface plus loopback. Device-level steps
  (installing the CA on a phone/tablet and confirming a warning-free browser)
  remain for the user's hardware — the exact manual steps are in
  docs/DEPLOYMENT.md §3.3.
- **Publicly trusted certificates** for a private LAN address are outside
  this feature by design (no domain control, no Let's Encrypt accounts); the
  local-CA path is the practical approach, as instructed.
- The CI Playwright job remains CI-side; local browser verification used an
  equivalent real-Chromium tool.


# v0.4.0-hotfix2 — Final Release Hotfix verification (2026-11-21)

**Base:** the supplied `saturday-multiverse-living-worlds-v0.4.0-hotfix1.zip`,
verified byte-identical to the hotfix1 tree before work began. Suite run
first: **197 passed** (recorded baseline, not assumed).

**Final:** **228 passed** (`pytest tests/ -q --ignore=tests/browser`) — 197
preserved + 14 recap-privacy/dismissal regressions (`tests/test_m41_hotfix2.py`)
+ 17 TLS-enforcement/startup-truth regressions (`tests/test_m41_tls.py`).
Also re-run from a fresh extraction of the final ZIP. Schema: `v8`
(additive: `char_knowledge`, `recap_seen`).

## Defect investigations

| Finding | Verdict | Root cause | Repair | Tests |
| --- | --- | --- | --- | --- |
| Recaps not scoped to player knowledge | CONFIRMED | memory hearing-scope was treated as player permission; discoveries were campaign-wide; no per-character visit record | `char_knowledge` (visited/discovery/heard) written at authoritative engine points (discover effect, party + split travel, rests, guestbook, arrival); recap filters memories AND discovery items by the viewer's own knowledge; deep/GM-only still blocked | `test_tavern_gossip_does_not_leak…`, `test_split_subgroups…`, `test_public_world_information…`, `test_deep_and_gm_only…` |
| No party sharing path | (design) | none existed | the campfire: `add_story` shares the teller's knowledge with `*party*` rows; spectators follow the shared feed | `test_campfire_sharing…`, `test_spectators_cannot…` |
| Recap dismissal was campaign-wide | CONFIRMED | markers in shared `state_json` | per-viewer `recap_seen` rows ('local' for solo); dismiss writes only the caller's row; frozen legacy markers prevent re-contamination; `char_knowledge` got its own marker space (borrowing the journal's was a real replay bug found while testing) | `test_independent_dismissal…`, `test_dismissal_survives…`, LAN restart check |
| Legacy marker migration | CONFIRMED as required | hotfix-1 markers were campaign-wide; per-player history never existed | documented conservative policy: seed each viewer once from the shared marker (zeros when never dismissed); history stays seen, new events appear, nothing fabricated; old schemas v2…v7 chain to v8 | `test_hotfix1_campaign_wide_markers…`, `test_never_dismissed…`, `test_v7_hotfix1_database_migrates…` |
| Production HTTPS advertised HTTPS on an HTTP port | CONFIRMED | banner scheme derived from `SATURDAY_TLS` regardless of the actual serving branch | `startup_plan()` single source of truth (cases A–E); banner states plain-HTTP-with-proxy explicitly in case D; external HTTPS URL only via `SATURDAY_TLS_PROXY_URL`; health reports `listener` + `tls.mode` | `test_case_a…`–`test_case_e…`, `test_case_d_real_server…` |
| Diagnostics did not enforce | CONFIRMED | `ssl_context` printed problems then loaded the certificate anyway | strict refusal before binding: missing/unreadable/expired/mismatched/no-SAN/no-coverage; `SATURDAY_TLS_NAME` pins the client-facing name; `0.0.0.0` never validated as an identity; partial coverage = warning listing covered/missing; key contents never logged; user certs never auto-replaced | `test_expired_certificate_is_rejected`, `test_mismatched_key…`, `test_wrong_san…`, `test_valid_lan_ip_san_is_accepted`, `test_expired_certificate_fails_the_server_loudly` |

## LAN verification (real servers; no second physical device available)

`scripts/verify_hotfix2_lan.py` — **29/29 checks**, clients connecting via
the machine's real non-loopback address (`21.0.7.32`) plus loopback:

- Direct HTTPS (Case B): title, solo create (no lobby), action + Engine
  Trace, travel, filtered recap, dismiss, resume, Library, Forge, Director —
  all with a CA-verified client (no `verify=False`).
- Plain HTTP (Case A): same campaign continues; health reports listener http.
- Multiplayer: host/join over HTTP; per-player markers survive a REAL
  application restart on the same data directory (host dismissed, guest's
  view untouched).
- Case D (production + TLS): health says listener=http/mode=proxy; a TLS
  handshake to that port demonstrably fails — no false advertising.
- SSE over HTTP and HTTPS reconnection covered by `tests/test_m40_lan.py`
  (re-run, all green).

## Trust-model notes

Unchanged from hotfix1 (read endpoints follow the campaign-read LAN model;
session campaigns require tokens for actions). Player-awareness now applies
to recap filtering whenever a session token is presented; the local solo
viewer remains fully trusted.

## Honest limitations

- No second physical device in this environment: device-level steps (CA
  install on a phone/tablet, warning-free browser confirmation) remain user
  steps — instructions in docs/DEPLOYMENT.md §3.3.
- CI Playwright job remains CI-side; local verification used real Chromium
  tooling as before.
- Per-player history for pre-hotfix2 saves is derived from the shared
  marker (documented policy), not reconstructed.
