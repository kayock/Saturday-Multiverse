# Changelog

## 0.5.1-cinematics — Living Shore cinematic integration (2026-11-22)

Pre-rendered atmospheric videos from the OpenFilm Saturday Multiverse
Cinematic Asset Pack v1 play as an optional presentation layer.

- Location ambience for Tide Gate / Beam, shore weather variants, Driftwood
  Camp, Salt & Lantern (including storm / supernatural variants), and the
  Skyless Light emphasis loop.
- Non-blocking portal activations for Door of Salt, Door of Ash, Unstable
  Door, and a default violet activation.
- One-time Salt-Grave / Drowned Bay introduction per campaign.
- Settings: enable/disable, volume, ambient vs one-shot audio, skip / replay.
- Respects calm mode and `prefers-reduced-motion`; canvas and SVG vignettes
  remain the fallback.
- Assets live under `client/assets/cinematics/` (MP4s via Git LFS). No
  OpenFilm, Juggernaut, or AI video work runs during gameplay.
- Multiplayer unchanged: each client plays locally; skipping never mutates
  shared state.

## 0.5.0-forge-ai — Campaign Forge model choice (2026-11-22)

The Game Master that narrates play and the model that converts a book are
now separate. A lightweight local model can keep running the game while
Campaign Forge uses a chosen local model, an already-running larger local
model, or an optional hosted OpenAI-compatible provider.

- **Automatic local** uses the configured local Game Master endpoint
  directly, or a larger local model that is already loaded. It does not
  start a large model and it does not send a manuscript to the public
  internet.
- **Select local model** uses one discovered endpoint. A large model is
  used only when it is already running.
- **Online provider** is optional. The conversion is refused until the
  operator approves sending that manuscript off the local network. A failed
  local conversion never falls through to a paid service.
- API keys stay in the local database, are not returned to the browser, and
  are not stored on the conversion job.
- Conversion modes are Faithful Adaptation, Alternate History, and Expanded
  Universe. Extraction still walks the whole document in bounded windows.
  A larger context may widen a window, never shrink the existing
  9,000-character bound. Failed windows stay listed and can be retried
  without repeating the windows that succeeded. A finished scan is not
  reported as a successful extraction.
- Gameplay routing between two home machines is unchanged. The gameplay
  model is not rewritten when the Forge model changes.

## 0.4.0-living-worlds-hotfix5 — Final Release Hotfix (2026-11-22)

Corrections release on top of hotfix4, addressing the independent review's
two reproducible privacy defects. **310 tests pass** (285 prior + 25 new
regressions in `tests/test_m44_hotfix5.py`), all four browser flows, the
36-check hotfix-3 and 26-check hotfix-4 LAN verifications, and a new
29-check hotfix-5 LAN acceptance over real HTTPS. No feature was removed;
every hotfix1–4 repair is preserved. No schema change (stays
`saturday.core.v8`).

### Recaps use the same specific-memory entitlement as sharing (unified)
- **Confirmed defect:** the recap's `_mem_entitled()` still authorized a
  memory whose scope sat in the viewer's own places/scopes — a character's
  PAST PRESENCE disclosed rumors created after they left, even though the
  hotfix-4 campfire picker correctly excluded them.
- **New behavior:** the recap grants a memory only when the character
  genuinely acquired it (a delivery record exists), that exact memory was
  legitimately shared with them or the party, a historical broad grant
  covers it (timestamp-capped, never future content), or it is truly public
  world news. Visiting a location, holding an old hearing scope, or another
  player having heard it never authorizes disclosure. Static kind and scope
  restrictions still filter candidates in SQL first — a public-looking
  scope can never surface a `gm`/`secret`/`hidden`/`host` memory.
- Legacy solo saves keep their recap behavior (documented conservative
  policy); per-player dismissal stays independent; reconnects and restarts
  preserve legitimate acquisitions.

### NPC conversations no longer expose internal knowledge
- **Confirmed defect:** `talk()` built dialogue, AI prompts, acquisition
  records and the API response from the NPC's whole scope-filtered memory
  collection — including GM-only, hidden and deep records. A conversation
  with the Drowned Lampkeeper returned the internal secret in the response,
  quoted it into dialogue, and recorded it as learned by the player.
- **New model (internal ≠ candidates ≠ revealed ≠ acquired):**
  - `_memories_for()` stays INTERNAL retrieval (what the NPC knows);
  - `_conversation_candidates()` filters it through the same static
    player-facing rules the recap and sharing engine apply (scope whitelist
    + kind restrictions) — this is the only set used for dialogue, AI
    prompts and responses;
  - `_gossip_lines()` tracks exactly which records were quoted into spoken
    lines (engine-tracked by construction, no keyword matching);
  - AI-assisted conversations: the prompt contains only permitted
    candidates (with their ids); the model may declare `disclosed_ids`,
    which are validated against the server-authorized candidate set —
    restricted, unknown or forged ids are dropped, and no declaration means
    nothing was learned. The AI can never reveal GM-only information or
    declare arbitrary memories learned.
  - Only actually-disclosed memories are recorded via `note_memory` and
    returned in the response's `memories` field (same entry shape as before
    — the client keeps working). The `npc_talk` event records disclosed
    ids only, never internal record text.
- Mysteries are not lost: `experience.reveal_memory()` is the explicit,
  engine-authorized story event that reveals one specific memory (with an
  optional scope relabel). Kind restrictions dominate — a GM-kind secret
  stays restricted whatever the event does.

### Tests and compatibility
- `tests/test_m44_hotfix5.py`: 25 failing-first regressions (13 failed
  against the untouched hotfix-4 source), covering recap entitlement,
  conversation safety, AI prompt hygiene, malformed disclosure validation,
  authorized revelation, transcripts/events, multiplayer boundaries,
  persistence and an end-to-end Lampkeeper + tavern scenario.
- Four hotfix2/3 tests encoding the old "presence = hears tavern talk"
  recap model were updated to record the delivery (the engine's own
  acquisition primitive); hotfix-4 talk tests now use conversation topics
  that actually disclose a memory ("rumors" reaches Maren's stock lines,
  which disclose nothing — by design).
- Old saves: no migration needed. Hotfix-4-era over-acquisition rows for
  restricted memories are inert (static rules dominate everywhere); the
  limitation is documented in `docs/MIGRATION.md`.

## 0.4.0-living-worlds-hotfix4 — Final Release Hotfix (2026-11-22)

Corrections release on top of hotfix3, addressing the independent review's
two reproducible privacy defects in the explicit campfire knowledge-sharing
system. **285 tests pass** (260 prior + 25 new regressions in
`tests/test_m43_hotfix4.py`), plus all four browser acceptance flows, the
36-check hotfix-3 LAN verification (updated with hotfix-4 checks) and a new
26-check hotfix-4 LAN acceptance over real HTTPS. No feature was removed;
every hotfix1–3 repair is preserved.

### Campfire picker authorization (no unauthorized fallback)
- **Confirmed defect:** `GET /campaigns/<cid>/campfire/shareable` caught ANY
  exception from `_mp_resolve()` as if the request were a legitimate solo
  request, and the character lookup fell back to the campaign's main
  character — so a request with a missing, invalid or revoked multiplayer
  token received ANOTHER character's shareable discoveries and memories.
- **New behavior:** failed multiplayer authorization is never treated as
  solo. On a campaign with an active session, a valid player token is
  required (`mp.auth`); missing, invalid, banned, removed or wrong-campaign
  tokens are refused with **403** and no character-owned knowledge in the
  response. The solo fallback to the campaign's own character is reached
  ONLY when no multiplayer session exists — decided by the campaign's actual
  session state, not by catching an auth failure. Spectators (valid tokens,
  no character) receive an empty picker.
- **No new authentication** was introduced: the existing multiplayer session
  model (`_mp_resolve` → `mp.auth`) is used exactly as designed. The same
  review of `teller_character()` and the campfire POST path confirmed the
  POST endpoint already refuses unauthorized tokens (403) and resolves the
  teller through their own campaign-scoped player row.

### Verified character knowledge (a hearing scope is not knowledge)
- **Confirmed defect:** shareability was decided by a hearing SCOPE — a
  character with `kind='heard', ref='tavern'` was offered and could share
  tavern rumors created long after they left the tavern.
- **New behavior:** a character may share a specific memory only when the
  engine can establish they actually learned it. Knowledge is recorded per
  specific memory id (`char_knowledge` kind='memory') at authoritative
  delivery points only:
  - an NPC conversation that delivers the memory (`legacy.talk`, with the
    authenticated player's own character);
  - the character's own arrival tale at campaign creation or on joining;
  - a visitor tale told while the character rests (camp guestbook);
  - a party member sharing it at the campfire (the whole party hears the
    tale — each character gains exactly that memory, never the scope).
- Both `shareable_knowledge()` (the picker) and `share_knowledge()` (the
  engine) enforce the same rule; the picker never offers what the engine
  would reject, and the engine independently validates every submitted id
  even when a malicious client bypasses the picker. Memories scoped `all`
  (public world news the engine already delivers to every recap) remain
  shareable by any party member. GM-only, hidden and deep-scope memories
  stay unshareable and unlisted. Forged, unknown, cross-campaign and other
  characters' memory ids are refused and write nothing.
- **Recap reading is unchanged** (the hotfix2 hearing model: a character who
  was at a place still hears that place's talk in their recap; shared grants
  stay timestamp-capped), with one addition: specifically acquired memories
  — learned in a conversation or received at the fire — now surface in the
  recipient's recap even when their scope is elsewhere.

### Legacy save compatibility (documented, conservative)
- No schema change and no version bump: `kind='memory'` is a new VALUE in
  the existing `char_knowledge` table (schema stays `saturday.core.v8`).
  Old saves open unchanged; all visited/discovery/heard rows and hf3-era
  party-shared memory records keep working (a historical party-wide memory
  grant still counts as delivery to the party).
- Memories that cannot be proven heard are NOT exposed as individually
  verified shareable knowledge: on old saves the picker offers places,
  public news, and whatever specific acquisitions the save itself records —
  honestly narrower than hotfix3's scope-based offer, by design.

### Preservation
- Sharing stays optional and explicit; an ordinary campfire story still
  shares nothing. The picker UI, `knowledge_shares` ledger, idempotent
  retries, per-character privacy, split parties, spectators, reconnection,
  persistent recaps and per-player dismissal are unchanged and re-verified.
- The solo `/talk` flow resolves the campaign's own character (session
  state decides — an unauthenticated solo request is legitimate, an
  unauthenticated request on a session campaign is not).

## 0.4.0-living-worlds-hotfix3 — Final Release Hotfix (2026-11-22)

Corrections release on top of hotfix2, addressing the independent review's
four findings: multiplayer knowledge privacy, recap integrity, HTTPS
certificate identity enforcement, and Windows CI portability.
**260 tests pass** (228 prior + 32 new regressions in
`tests/test_m42_hotfix3.py`), plus all four browser acceptance flows and a
35-check live LAN verification (real HTTP and HTTPS servers, CA-verified
clients, a genuine hotfix2 → hotfix3 save migration). No feature was
removed; every hotfix1 and hotfix2 correction is preserved.

### Campfire knowledge sharing is now explicit, bounded and validated
- **Confirmed defect:** every campfire story blanket-shared the teller's
  ENTIRE knowledge scope — all visited places, all discoveries, and every
  hearing scope — with the whole party. An ordinary tale ("the moon over
  Whitby was beautiful") silently granted everyone the teller's tavern
  hearing scope, including rumors introduced AFTER the story was told.
- **New behavior:** a story shares NOTHING by itself. When the teller wants
  to share, they explicitly select individual items (a discovered or visited
  place, or one specific memory they heard) via the campfire form's share
  picker (`share` field on `POST /campaigns/<cid>/campfire`; picker data
  from `GET /campaigns/<cid>/campfire/shareable`).
- **The engine validates every selection server-side.** Only what the
  character legitimately holds may be shared: GM-only, hidden and deep
  knowledge can never be shared; another character's discovery is refused;
  a bare hearing scope ('tavern') is NEVER granted — share the specific
  memory instead, so a past rumor does not unlock future rumors. Rejected
  selections are reported with a reason; nothing is partially granted.
- **Sharing is auditable.** The additive `knowledge_shares` table (schema
  stays `saturday.core.v8`; created by the standard idempotent `CREATE
  TABLE IF NOT EXISTS` pass) records exactly what was shared, by whom, when,
  and from which story; a `knowledge_shared` event appears in the campaign
  stream. Retries are idempotent — a ref already granted is never duplicated.
- **Future secrets stay private.** A party-wide grant covers only what was
  already recorded at grant time: rumors and discoveries created later stay
  private until heard in person or explicitly shared. Split-party
  discoveries remain isolated; spectators follow the shared feed only.
- **Documented conservative legacy policy:** historical blanket `shared`
  rows written by hotfix2 are NOT deleted or rewritten (nothing is erased
  from a save, and no historical sharing event is fabricated). They remain
  readable as the fire-tales they were, but — having no evidence of exactly
  which facts were communicated — they no longer authorize memories created
  after the grant timestamp.

### Recap: eligibility is applied BEFORE the display limit
- **Confirmed defect:** `recap()` fetched the newest 8 NPC memories and
  filtered afterwards, so 8 hidden/unauthorized rows consumed the whole
  window and an older authorized rumor never appeared, however entitled the
  player was.
- **New behavior:** static rules (the scope whitelist and blocked kinds —
  independent of any viewer) filter in SQL; viewer-dependent entitlements
  gate each candidate inside a bounded backward walk that stops as soon as
  the 8-item display budget is met (hard cap: 2000 candidate rows scanned).
  An authorized rumor behind 120 newer restricted rows still appears.
- **Preserved:** per-player last-seen markers, one player's dismissal never
  affecting another's, viewing a recap never silently dismissing it, stable
  ordering, duplicate suppression, spectator limits, and the solo-legacy
  unrestricted behavior.

### Strict HTTPS identities and validity windows
- **Confirmed defect:** certificate diagnostics merged the certificate's
  Common Name into the SAN list and checked only expiry — a CN-only
  certificate (no Subject Alternative Name extension) passed strict
  validation, and a certificate whose validity had not begun yet also
  passed.
- **New behavior:** identities are inspected strictly separated — real SAN
  DNS names, real SAN IP addresses, and the Common Name reported separately
  as diagnostics-only information that never satisfies a SAN requirement.
  Coverage checks use real SAN entries only; an IP identity is satisfied
  ONLY by an `IPAddress` SAN (a `DNSName` carrying the textual IP address is
  not an IP SAN — browser semantics). Validity is compared exactly in
  timezone-aware UTC (no whole-day truncation): not-yet-valid, expired,
  unreadable, key-mismatch and missing-identity certificates are refused
  before the server binds when HTTPS is enabled.
- **Preserved:** local CA generation, renewal, user-provided certificates,
  LAN IPv4 SANs, hostname SANs, direct HTTPS, production HTTP behind an
  HTTPS reverse proxy, optional plain HTTP. Nothing regenerates
  automatically; no trust store is touched; verification is never disabled.

### Cross-platform CI
- **Confirmed defect:** the TLS suite's `banner()` helper imported the
  Unix-only `fcntl` module and used non-blocking pipe reads — unimportable
  on Windows — and `requirements-dev.txt` never installed `cryptography`,
  so the HTTPS tests could not run in CI at all.
- **New behavior:** subprocess output is captured by a bounded background
  reader thread (portable across Windows/Linux, Python 3.10/3.12; no
  Unix-only imports, no blocking reads, no indefinite waits); failing tests
  reap the child process and the collector thread. `requirements-dev.txt`
  now installs `cryptography>=3.4` (it remains OPTIONAL for players — only
  HTTPS users need it).
- **CI truthfulness fixes found while verifying:** the browser job's
  `pytest tests/browser` collected ZERO tests (the suite-level
  `collect_ignore_glob` swallows the directory), so the job passed
  vacuously — it now runs `pytest tests/browser/test_browser_flows.py`
  explicitly (all four flows pass, including the campfire flow, whose
  selectors were repaired against the real UI element ids).
- **Honest limitation:** the GitHub Actions matrix (ubuntu/windows ×
  Python 3.10/3.12) could not be executed from this environment — the
  Windows legs are verified by code-level portability (no Unix-only imports
  remain in any test; a regression test enforces this) and must be confirmed
  by the workflow's first run on GitHub.

### Preservation
- The Living Shore, Infinite Library, Campaign Forge, Collaborative
  Workshop, solo play, multiplayer, party splitting, spectators, Undertow,
  D&D-compatible play, persistent combat, the Living Campaign Director,
  Engine Trace, Expedition Goals, Campfire Stories, What-If Timelines,
  returning-player recaps, the tutorial, all four world packs, save
  migrations, optional LAN HTTPS and existing HTTP operation are unchanged.
- Model endpoints, contexts and timeouts are untouched; no new accounts,
  tokens, API keys, authentication gates or login requirements.
- A database created by hotfix2 opens under hotfix3 with every row intact
  and gains `knowledge_shares` automatically (verified live against the
  pristine hotfix2 tree).

## 0.4.0-living-worlds-hotfix2 — Final Release Hotfix (2026-11-21)

Corrections release on top of hotfix1, addressing the independent review's
three findings. **228 tests pass** (197 prior + 31 new regressions). All
hotfix1 repairs are preserved.

### Player-specific recap privacy (The Shore Remembers)
- **Knowledge, not just scope.** Hotfix1 filtered NPC memories by hearing
  scope, but any player could read place-scoped gossip regardless of where
  their character had actually been. Schema v8 adds `char_knowledge` — an
  authoritative per-character record of visited places, discoveries made and
  things heard in person — written at the engine's own knowledge points:
  the discover effect, party travel, split-party travel, shore rests, the
  camp guestbook and a new character's arrival. A tavern-scoped memory now
  reaches only characters who were there (or were told at the campfire).
- **Discoveries belong to their discoverer.** A discovery appears in the
  discoverer's recap; other players' recaps do not include it.
- **The campfire is the sharing mechanism.** Telling a tale at the fire
  shares the teller's places, discoveries and things heard with the whole
  party (spectators follow the shared feed). Public world events (victories,
  endings, shore upgrades, surfaced consequences) remain visible to everyone.
- **Spectators stay restricted**: private discoveries and place-scoped
  gossip are withheld until shared; global news still flows.
- Deep-scoped/GM-only/hidden memories remain blocked for every viewer
  (hotfix1 behavior preserved); solo saves keep their established behavior.

### Per-player recap dismissal
- **Campaign-wide markers were wrong.** One player dismissing the recap
  marked every other player's unseen events as read. Schema v8 adds the
  `recap_seen` table: each viewer (multiplayer player id, or 'local' for
  solo) owns their last-seen rowids, turn, timestamp and dismissal time in
  SQLite — one player's dismissal does not affect another's, markers survive
  reconnects and full application restarts.
- **Conservative legacy migration (documented).** Hotfix-1 campaign-wide
  markers seed each viewer's row once at first read: history under the
  shared marker stays seen, genuinely newer events appear, and campaigns
  that never dismissed keep showing recent activity as new. Per-player
  history never existed before this release and is not fabricated. The
  legacy campaign-wide markers are frozen (never rewritten) so a late
  dismissal cannot re-contaminate another player's seed.
- `char_knowledge` gains its own marker space (it previously borrowed the
  journal's), so shared/visited rows can never replay after dismissal.

### Production HTTPS reports the truth
- **The defect:** `SATURDAY_PRODUCTION=1 SATURDAY_TLS=1` printed an
  `https://…` URL while waitress listened on plain HTTP.
- New `startup_plan()` is the single source of truth for the listener
  protocol; the banner, health endpoint and docs all derive from it:
  - **Case A** plain HTTP → HTTP listener, HTTP URL.
  - **Case B** direct LAN HTTPS → HTTPS listener with the configured
    certificate.
  - **Case C** production HTTP → waitress, HTTP URL.
  - **Case D** production + TLS → waitress listens on **plain HTTP** and the
    banner says so explicitly ("this port serves PLAIN HTTP; TLS happens at
    your local reverse proxy"); an external HTTPS address is displayed only
    when the operator sets `SATURDAY_TLS_PROXY_URL`.
  - **Case E** production + TLS + `SATURDAY_TLS_DEVSERVER=1` → this process
    really terminates TLS.
- `/api/health` now reports `listener` ("http"/"https" — what actually
  serves the port) and `tls.mode` ("off"/"direct"/"proxy").

### Enforced certificate validation
- **The defect:** TLS diagnostics printed certificate problems but still
  served the invalid certificate.
- `ssl_context(strict=True)` now REJECTS unusable certificates before the
  server accepts any connection: missing files, unreadable certificates,
  expired certificates, key/certificate mismatches, certificates without
  SANs, a certificate that does not cover the configured HTTPS name
  (`SATURDAY_TLS_NAME`), or one that covers none of the client-facing names.
- **Bind vs client-facing distinction:** `0.0.0.0` is a bind address, not a
  browser identity. Coverage is validated against
  `SATURDAY_TLS_NAME` + the machine's real non-loopback addresses + hostname
  + localhost; partial coverage is a printed warning listing exactly which
  names are and are not covered.
- User-provided certificates (`SATURDAY_TLS_CERT/KEY`) work unchanged; user
  certificates are never regenerated silently; diagnostics never log key
  contents; errors name the fix (`cert_setup.py renew`, `--ip <address>`).
- `scripts/cert_setup.py diagnose` reports covered and missing names.

### Verification
- Live LAN run (`scripts/verify_hotfix2_lan.py`): 29/29 — full solo flow
  (title, create, act, travel, Engine Trace, filtered recap, dismiss, resume,
  Library, Forge, Director) over direct HTTPS through the machine's real
  non-loopback address with a CA-verified client; multiplayer host/join;
  per-player markers surviving a real application restart; Case-D
  truthfulness (TLS handshake to the HTTP port demonstrably fails).
- New regression suites: `tests/test_m41_hotfix2.py` (14) and
  `tests/test_m41_tls.py` (17).

## 0.4.0-living-worlds-hotfix1 — LAN HTTPS & Reliability (2026-11-21)

Corrections release on top of 0.4.0-living-worlds. All 197 tests pass
(180 prior + 9 privacy/integrity regressions + 8 LAN/HTTPS integration tests).

### Privacy and recap accuracy (The Shore Remembers)
- **NPC memory scopes respected.** The recap quoted NPC memories regardless
  of their hearing scope; deep-scoped shore knowledge (e.g. the lampkeeper's
  secrets) could surface to players who never earned it. Memories now pass a
  scope whitelist (`all`, `camp`, `doors`, `tavern`) and a blocked-kind list
  (`secret`/`hidden`/`gm`/`host`) — deep and hidden knowledge never reaches a
  player-facing recap.
- **Reliable last-seen markers.** The recap compared event sequences against
  an unrelated marker and re-served old "achievements". Dismissal now stores
  per-table rowids (`recap_seen_rowids` for events/npc_memories/journal/
  upgrades/consequences/mp_events) — exact, monotonic, never a comparison
  between unrelated identifier spaces, immune to same-second timestamps.
  Old saves migrate safely: `recap_seen_turn` derives the engine-events rowid
  (and only then) and is persisted once; a never-dismissed campaign keeps
  showing recent activity as new.
- **New vs ongoing.** Items carry `novelty` ("new" strictly after the marker,
  "ongoing" for persistent objectives and current weather); duplicates are
  deduplicated by normalized text; the recap endpoint is player-aware when a
  multiplayer token is presented.

### Expedition goal integrity
- **Campaign-scoped mutations.** `abandon_goal` updated goals by ID alone, so
  a request naming campaign A could abandon campaign B's goal. Every goal
  mutation is now scoped and verified against the supplied campaign;
  mismatches are rejected without touching data (404 via the API).
- **Verified vs player progress.** New `verified_progress`/`last_source`
  columns (schema `saturday.core.v7`, additive migration): only engine events
  (victories, discoveries, quest resolutions) can produce verified progress;
  the player-facing endpoint is hard-wired to `verified=False` and can never
  fabricate a mechanically validated achievement. Voluntary player progress
  still works and is displayed as player-authored.
- **Multiplayer ownership.** Personal goals belong to their owner: another
  guest cannot tick or abandon them (host and local player can); guests
  cannot create personal goals forged to another player's ownership.

### Endpoint audit (recap, goals, campfire, checkpoints, timelines)
- Cross-campaign checkpoint references are rejected when branching timelines.
- Goal listing is strictly campaign-scoped.
- Documented (not silently changed): read endpoints (recap, goals, campfire,
  timeline compare) follow the game's long-standing campaign-read trust model
  on the LAN — see docs/VERIFICATION.md §Trust model notes.

### LAN access
- Verified end-to-end over a real non-loopback address with `SATURDAY_HOST=0.0.0.0`:
  title/assets, solo creation, acting, resuming, Library/Forge/Workshop/
  Director endpoints, multiplayer host/join, SSE streaming and reconnection.
- Solo LAN play requires no multiplayer lobby (it never did; now regression-
  tested). Frontend requests are all relative-URL based (no hardcoded
  `localhost`); invitation links derive scheme+host from the browser origin.

### Optional LAN HTTPS
- `server/tls.py` + `scripts/cert_setup.py` (`generate` / `renew` /
  `diagnose` / `show`): a local CA + server certificate with SANs for
  localhost, the loopback, the hostname and every non-loopback LAN address.
  825-day server certificates, 10-year CA, key permissions 0600 (POSIX).
- `SATURDAY_TLS=1` enables HTTPS explicitly; ordinary HTTP is untouched when
  it is not set. User-provided certificates via `SATURDAY_TLS_CERT/KEY`.
- Clear diagnostics: expired / mismatched / missing certificates are reported
  on the console, in `/api/health` (`tls` field), and by `scripts/preflight.py`.
- Production modes: waitress (plain HTTP) unchanged; HTTPS via the dev server
  (`SATURDAY_TLS_DEVSERVER=1`) or a TLS-terminating local reverse proxy
  (documented Caddy example); `SATURDAY_TRUST_PROXY=1` is the only way
  forwarded headers are honored.
- Verified with REAL certificate verification (CA-trusted clients — no
  `verify=False` anywhere): assets, API, solo play, save/resume, multiplayer
  host/join, SSE reconnection over HTTPS. Client CA-trust instructions for
  Windows/Linux/Android/iOS/macOS in docs/DEPLOYMENT.md. Physical
  device-level trust installation remains a documented user step.
- Certificates/keys live in the data directory only (excluded from Git and
  release packages).

## 0.4.0-living-worlds (2026-11-21)

Built on GitHub `main` at `08f80b3ef5c118fb48b42ab41961680057ca559d` (the v0.3.6
release including the launcher/watchdog/Workshop-privacy hotfixes). All 164
pre-existing tests still pass; 16 new defect regressions and 6 engagement
acceptance tests bring the suite to 180.

### Phase 2 — confirmed gameplay defects repaired (each with a failing-first regression test)
1. **Solo D&D combat actions were rejected (403).** `server/api.py` `combat_act`
   resolved the acting character only from a multiplayer session. Solo voyages
   now resolve the campaign's own character through the same engine path;
   multiplayer ownership is unchanged (forged `chid` still 403).
2. **Invalid spell targets consumed spell slots.** `server/combat.py` consumed
   the slot before validating the target. All preconditions (spell known,
   living monster target, valid party member) are now validated BEFORE any
   resource is spent; valid actions consume exactly the correct resources.
3. **SSE/REST replay starvation.** `events_since` fetched 500 rows then
   filtered — 501 invisible events hid every later public event. Replaced with
   `events_since_page`: bounded pagination whose cursor advances through
   filtered events (20k scan cap per call). Verified with 501-invisible→visible,
   1,200 mixed events, repeated replays: no loss, no duplicates, no leaks. The
   REST endpoint returns a `cursor` the client adopts.
4. **Interrupted Forge jobs got stuck** in `analyzing`/running states that
   neither the watchdog claimed nor retry accepted. Jobs now carry a worker
   lease (`owner`/`heartbeat`, schema v6): single-winner atomic claims, a
   15-second heartbeat, recovery of leases stale past 90 s (artifacts
   preserved — retry resumes from the last completed stage), startup recovery,
   and watchdog re-claiming. No fixed timeout can kill a live long job.
5. **Rejected actions advanced the game clock.** `run_turn` incremented the
   turn before the dead-character check. Validation now precedes every
   state-consuming step; dead-character and malformed actions change nothing.
6. **A build without SQLite FTS5 failed at startup.** Both FTS5 virtual-table
   creations are guarded; missing optional support degrades to LIKE search with
   a logged warning, a `/api/health` indicator, and working search (tested with
   a connection proxy that fails exactly like a fts5-less build).
7. **Story spoilers could surface by keyword retrieval.** The `source_horizon`
   was never established or advanced. Source-linked packs now bind their
   document at creation/travel (title/author match — no fixed ids), open the
   revealed window at the first 15% clamped to a chapter boundary, and advance
   on scene progress (+10%), discoveries (+5%) and endings (100%). Verified:
   a late villain revelation stays unretrievable until legitimately discovered.
8. **"Full-book" extraction sampled ~30% of the text.** Extraction windows are
   now character-bounded (9,000 chars) with long chunks sliced at 2,500 chars —
   every character processed, nothing dropped at boundaries. Coverage metrics
   are honest: chunks visited, characters processed vs total, chapters fully
   analyzed, sections skipped (0), failed windows. Verified: facts at chunk
   ends and across window boundaries reach the world bible.

### Phase 5-7 — the Living Shore and engagement
- **The Shore Remembers**: a returning-player recap built from the engine
  event log — achievements, unresolved threads, discoveries, NPC memory
  movement, shore upgrades, current weather — dismissible (records the seen
  turn). Shown on entering an existing voyage.
- **Expedition goals**: shared or personal objectives with engine-validated
  progress (victories, discoveries, quest resolutions auto-credit matching
  goals); visible progress bars; abandon supported.
- **Campfire Stories**: player-authored stories/memories/memorials around the
  fire, stored separately and explicitly marked — never treated as engine
  proof; the Ledger keeps verified records distinct.
- **Engine Trace**: an optional per-turn panel showing the action, the rule
  applied, dice with modifiers and difficulty, the validated effects, and the
  narration source — GM-only knowledge never appears.
- **Combat UI**: initiative order with the active turn highlighted, spell
  slots, concentration, waiting-on-turn indicator, conditions, and a clear log.
- **Cinematic dice feedback**: optional crit/fail glows driven by actual engine
  results, disabled by reduced-motion.
- **Atmosphere**: recap/hud integration honoring mute and reduced-sensory
  settings; no external audio services.

### Phase 10-12
- **What-If Timelines**: branch a campaign from any checkpoint (or current
  state) into a NEW campaign with its own identity, events and ownership; the
  original is untouched; comparison reports endings, quests, character fates,
  inventory and relationship differences from real snapshots.
- **Workshop playtest portals**: launch a draft world into an isolated test
  campaign (no approval needed); playtest reports list validation problems,
  flow findings, missing item references and continuity warnings; stopping
  archives the portal and removes its temporary pack.
- **Interactive tutorial**: a short first-play walkthrough (shore, portals,
  composer, choices, character, D&D-specific notes when that ruleset is
  selected) with skip and replay.
- **Accessibility**: reduced-motion and high-contrast modes, visible focus
  outlines, aria-live narration, mobile-aware nav wrapping.

### Reliability
- GitHub Actions CI (`.github/workflows/ci.yml`): Linux + Windows, Python
  3.10/3.12, syntax compilation, JavaScript checks, world-pack validation, the
  full pytest suite, a real startup smoke test, and a Playwright browser job.
- `scripts/preflight.py`: PASS/WARN/FAIL diagnostics for Python, dependencies,
  SQLite/FTS5, data-dir writability, schema, backups, ports, packs, and
  optional model-endpoint reachability (never starts or installs a model,
  never prints secrets).
- `scripts/validate_packs.py` + `scripts/smoke_startup.py`.
- `requirements-dev.txt` splits test-only dependencies.
- Backup/restore verified under WAL: a `POST /backup` snapshot reproduces
  character state and event sequences exactly.


## 0.3.6 maintenance hotfix (2026-11-21)

- **Startup:** `python -m server.app`, `run.sh`, and `run.bat` now call the existing `main()` launcher; no undefined `app`, `HOST`, or `PORT` references. Both standard Flask and optional Waitress serving paths start the watchdog.
- **Watchdog:** multiplayer and combat timeout sweeps now resolve their modules correctly; exceptions are logged rather than silently swallowed. Forge queue scheduling remains in-process.
- **Workshop privacy:** a proposal touching GM secrets now redacts the actual returned `ops` and `note` for other collaborators, including nested secret paths and mixed public/private proposals. Unattributed GM secrets remain creator-only unless explicitly marked shared.
- **Regression coverage:** added `tests/test_release_fixes.py`. The full Flask-dependent suite must be rerun in a proper application environment before deployment; see `docs/VERIFICATION.md`.


## 0.3.6-living-campaign (2026-11-21)

### Critical D&D repairs
- Encounters are now persistent and player-controlled (new `server/combat.py`):
  initiative order, per-turn player actions, engine-resolved enemy turns,
  conditions with durations, concentration saves, death saving throws,
  stabilization and retreat. Pack `dnd_encounter` effects start a live
  encounter instead of an automatic multi-round roll.
- HP persists across encounters: an encounter starts from CURRENT sheet HP,
  not `hp_max`. The old auto-resolver's downed→resurrected logic is removed;
  death saves, stabilisation and death are engine-authoritative.
- Victory rewards (XP, levels) are granted exactly once per encounter.
- Rules expansion on SRD 5.1: barbarian, ranger, paladin, bard, monk, druid;
  gnome, half-orc (relentless endurance), tiefling, dragonborn (breath weapon);
  thunderwave, bless, shield of faith, hold person, fireball; class saving
  throws; `encounter_difficulty()` from SRD XP thresholds; a published
  coverage table (`/api/rules/dnd/coverage`) listing supported vs
  deliberately-unsupported material. Fixed: spell slots read from JSON
  storage (string keys) so casters restored from the database can cast again.

### Multiplayer completion
- Party splitting: per-character locations, location-scoped narration events,
  regrouping (individual or host-forced); shared travel still moves the whole
  party by default.
- Spectators: read-only observers via a dedicated invite; they can watch and
  reconnect but never act, roll, trade or travel.
- Shared D&D combat: initiative across participants, per-player turn actions
  with ownership enforcement, reinforcements in round one.
- Server-side watchdog (in-process daemon thread): expired structured-mode
  turns auto-advance; idle combat turns are auto-defended; both sweeps are
  idempotent and timestamp-driven, surviving restarts.
- Fixed: `/mp/reconnect` now honours the body token for clients that lost
  their session state.

### Infinite Library — full-book conversions
- Conversion jobs (`server/forge.py`): queued/running/failed states persisted
  in the database, resumable at stage granularity, retry/cancel, background
  worker thread, duplicate-job guard per document.
- Hierarchical pipeline: structure → extraction over the ENTIRE document
  (windows of 24 chunks, every chunk processed) → deterministic consolidation
  (alias merge, chronology, contradiction capture) → world bible (canonical
  facts, secrets, relationships, timeline, the source's ENDING) → campaign
  generation → validation → review → approval.
- Coverage metrics per job: chunks processed vs total, chapters, windows,
  model calls, errors — shown in the UI.
- Manual editing: deterministic path ops (set/add/update/remove) on drafts,
  every save recorded as a revision; history, compare, restore, duplicate,
  export; flow validator (unreachable scenes, broken ending paths, deadlocks,
  unknown items/effects) with an SVG flow graph in the editor.
- Faithful Adaptation vs Rewrite the Legend are first-class modes affecting
  generation prompts and gameplay narration.
- Safe retrieval: gameplay prompts no longer fall back to rotating windows;
  context-sensitive retrieval only, with a story-horizon guard against
  surfacing future revelations.

### The Living Campaign Director
- `server/director.py`: quests/mysteries/threats/consequences tracked from
  AUTHORITATIVE events with evidence; optional pacing suggestions (off /
  gentle / active, default gentle); suggestions are advisory lines to the GM —
  never forced, never auto-applied.
- `server/continuity.py`: deterministic checks — dead characters named in
  later narration, duplicated inventory rows, quest states reversed after
  completion, one-time encounters repeated, visibility conflicts — reported
  as advisory flags in the Director panel.

### Collaborative worldbuilding (steering addition)
- The Worldbuilding Workshop: original worlds on the same universal Forge
  (no separate homebrew system), created from scratch or seeded from an
  existing campaign.
- Contribution model: collaborators propose deterministic edits through their
  existing multiplayer identity; the creator reviews, applies or rejects.
- Conflict handling: conflicts are recomputed at review time; conflicting
  proposals are refused unless the creator explicitly forces them — nothing
  is silently overwritten.
- AI assistance: per-kind suggestions (npc/location/quest/dialogue/encounter/
  lore/branch) returned to the requester only, never applied automatically;
  offline template fallback clearly marked.
- Spoiler boundaries: GM secrets carry authoritative authorship; a
  contributor's view filters everyone else's hidden material, including
  proposal contents.
- Approval: creator-only, gated by the same `validate_pack` + flow checks as
  every literary adaptation; installation is local (userdata) — imported or
  private sources are never published automatically, and no publishing
  pipeline exists at all.

### Persistence & saves
- Schema v5 (`saturday.core.v5`): encounter, job, revision, contribution,
  director-thread and checkpoint tables; migration chain v1→v5 verified.
- Campaign checkpoints: snapshot + restore-as-new-campaign (no automatic
  rollback of shared state, no reward duplication).
- Fixed: retried `once`-flagged effects no longer double-grant rewards.

### Tests
- 159 tests green, including the mandatory v0.3.6 suite (persistent HP across
  encounters, death without resurrection, player-controlled turns, timeout
  sweeps, restart survival, split-party knowledge boundaries, spectator
  filtering, turn watchdog, full-novel coverage, resumable jobs, duplicate
  entity resolution, manual editing/versioning, flow validation, private
  content separation, safe retrieval, Director tracking, continuity flags,
  checkpoint restore, migration, restart persistence) and two acceptance
  scenarios: the eight-phase Dracula voyage (four genuine API clients +
  spectator + reconnect + ending + ledger) and the three-participant
  collaborative worldbuilding build (conflicts, secrets, install, play).


## 0.3.5-infinite-library (2026-11-21)

### The Infinite Library
- Document import for PDF (pypdf), EPUB, DOCX, TXT, Markdown, HTML and
  world packs; sources stored verbatim; heading-aware chunking; SQLite
  FTS5 index with LIKE fallback; hostile-file guards (size caps, zip
  caps, no entity expansion)
- Context-aware retrieval during play: adapted worlds feed the GM the
  most relevant passages for the current action
- Library browser with search, import screen with status/error reporting,
  adventure preview with cast, places, story shape and licensing

### The Campaign Forge
- Bounded extraction windows → profile → two synthesis calls → engine-valid
  pack draft; deterministic validation + auto-repair (ids, gotos, endings,
  hubs); editor with per-section regeneration and notes; approve installs
  the pack as a shore door instantly
- Faithful and alternate-story modes; hidden GM secrets carried into the
  hidden-facts store; library context available to the GM without
  exposing secrets to players

### D&D-compatible ruleset (optional, alongside Undertow)
- SRD 5.1 (CC-BY-4.0) derived: 4 classes, 4 species, 4 backgrounds, d20
  checks with advantage/lucky, proficiency, AC/HP, bounded deterministic
  combat with an open bestiary + literature-derived stat blocks, an open
  spell list with slots, long/short rests, XP levels 1–5
- Outcomes mapped onto the engine's five bands: every pack plays under
  either ruleset; Undertow untouched (omens/push/resist intact)

### Starter adventures (public-domain sources, licensed and attributed)
- Dracula: The White Ship — gothic horror, 6 locations, 6 scenes, 3 endings
- The Rue Morgue Affair — detective mystery, 5 locations, 4 scenes, 3 endings
- The Time Machine: Beyond the Seventh Day — sci-fi exploration, 6
  locations, 6 scenes, 3 endings
- Roanoke: private-manuscript import flow prepared; nothing fabricated or
  distributed

### Engine & platform
- Schema v4: library_docs/library_chunks(+FTS)/forge_drafts,
  campaigns.ruleset; additive migration v3→v4 (and the full v1→v4 chain)
- gm_secrets → hidden facts at campaign creation; library retrieval wired
  into the GM prompt; D&D routing for checks, rests, encounters, omens
  skipped under dnd5e
- 21 new tests (131 total): all import formats, long-document retrieval,
  forge pipeline incl. refusal of invalid packs, ruleset determinism and
  isolation, starter-pack playability to endings, hidden-info boundaries,
  multiplayer aboard imported adventures, hostile inputs, migration

## 0.3.2-shared-shore (2026-11-21)

### Milestone 3.0 — Multiplayer foundation
- Host a Shared Voyage: sessions, hashed invitation tokens (expiring,
  revocable, use-limited), player limits, approval mode, lobby with
  portraits/readiness/invite links, remove/ban.
- Player identity: independent characters per player (schema v3 rebuilds
  away the one-character-per-campaign constraint), server-side ownership
  on every endpoint, reconnect without duplication.
- Real-time sync: durable sequenced `mp_events`, SSE stream with one-time
  tickets, replay from `last_seq`, presence heartbeat + offline sweep,
  snapshot+replay reconciliation.

### Milestone 3.1 — Shared adventures
- Party travel by proposal and unanimous vote (host may move directly);
  declines cancel; executes exactly once.
- One shared AI Game Master: host's model serves all players; per-campaign
  action lock serializes actions and narration; honest offline fallback.
- Multiplayer dice: individual checks, risk/push/resist scoped to the
  roller; results announced to the party.
- Turn management: freeform (serialized) and structured turn order with
  timeouts, skipping and host pass-lantern.
- Shared/private information boundaries: hidden facts never broadcast;
  per-character purses, packs, omens and deaths.

### Milestone 3.2 — The living multiplayer shore
- Visible party presence on the Living Shore canvas (colored markers,
  name labels, idle motion; calm-mode aware).
- Party chat drawer: players, GM narration, dice, system events; rate
  limited, escaped, durable history.
- Player-to-player interactions: consented item trades (atomic, split/merge
  aware), glassbead gifts, clue sharing.
- Shared shore improvements: bead contributions with escrowed pot and
  exactly-once purchase.
- Party legacy: company moments recorded on shared endings; party section
  in the Memory Ledger; tavern gossip remembers former parties.
- Reconnection: session tokens persist per campaign; catch-up replay;
  pause/resume/end; process-restart recovery.

### Infrastructure
- Schema v3: mp_sessions/mp_players/mp_invites/mp_events; per-character
  state migration (beads, death, pending rolls, omen decks); inventory
  ownership; clue sharing flag.
- Production serving option (waitress; SATURDAY_PRODUCTION=1) and full
  deployment/security documentation.
- Tests: 81 → 110, including a multi-client harness (independent tokens,
  real HTTP concurrency), security isolation, replay, restart recovery and
  hostile-input handling.

## 0.2.5-living-multiverse (2026-11-21)
## 0.2.5-living-multiverse (2026-11-21)

### Milestone 1.5 — The Living Shore Awakens
- Tide clock (HUD dial + beats-to-change) with predictable 12-beat progression.
- Wash-ashore finds: reproducible, tide-scheduled, picked up from the dock;
  items, glassbeads and clue threads wash in.
- NPC structured memories + scoped gossip (Talk at the camp and tavern);
  grounded in recorded events; AI enrichment with honest offline voice.
- Seven GM personalities (Classic/Grimdark/Cosmic/Noir/Whimsical/Mythic/Custom),
  persistent per campaign — tone only, never rules authority.
- Cinematic dice reactions: engine resolves, GM narrates the moment only.
- Storm/rain presentation, richer campfire/tavern/lighthouse atmosphere,
  calm mode (reduced motion), three-bus audio controls.

### Milestone 2.0 — Worlds Beyond the Beam
- Seeded portal generation at the Unstable Door: deterministic, versioned
  (living-multiverse.gen.v1); six world archetypes; persistent worlds with
  visits, flags and signature scenarios that resume mid-beat.
- Two new handcrafted adventures: The Umbral Market (dark fantasy, glassbead
  economy) and The Skyless Light (lighthouse mystery, upgrade-gated ending).
- Tactical mechanics: Risk (pre-roll +2, failures hurt more), Push (1 Vigor,
  raise the band), Resist (1 Nerve, halve harm) — all engine-owned.
- Player omen hand: draw for 1 Nerve (2 per rest, 2 held), play edges/turns;
  complications play themselves.
- Shore improvements: glassbead economy + six builds with visible effects
  (kettle, guestbook, map wall, hammock, relamped teal beam, lens array).

### Milestone 2.5 — The Echo System
- Echoes: endings offer legacy (items/traits/achievements/reputations/portals);
  profile-level; up to two woven into a new voyage; single-use enforcement.
- Cross-world consequences registered on defined triggers, surfaced in
  tavern gossip and the Ledger.
- Foreshadowing clue threads with engine payoffs (The Ninth Wave unlocks a
  hidden shore location; The Wrong Gull becomes a companion perk).
- The Memory Ledger: visual journal — worlds, people, threads, consequences,
  echoes, tavern memories, chronological log.
- Death/retirement concludes a wanderer and leaves a Remembrance echo.

### Infrastructure
- Schema v2 additive migration (six new tables) — Milestone 1 saves migrate
  losslessly and stay playable; newer-schema databases are refused loudly.
- New HTTP endpoints: style, talk, washashore, push/resist, pending accept,
  omen hand draw/play, upgrades list/buy, worlds generate/list, seeds
  suggest, echoes list, ledger.
- Versioned asset URLs (?v=NN) to prevent stale client modules on upgrade.
- Tests: 50 → 81 (migrations, generator, tactics, omens, upgrades, echoes,
  consequences, gossip, ledger, HTTP).

## 0.1.0-milestone1 (2026-11-21)

- Playable solo foundation: Living Shore hub, six locations + two portal
  destinations, The Salt-Grave Signal adventure with four endings.
- AI Game Master over any OpenAI-compatible endpoint; honest Offline
  Storyteller fallback.
- The Undertow System dice (app-authoritative), Omen Deck, Vigor/Nerve.
- SQLite persistence: campaigns, journal, quests, facts (visible/hidden),
  transcripts, dice log, event log, FTS5 search, export/import, backups.
- Procedural WebAudio soundscape; QR/scanner input with strict allowlist.
- 50 pytest tests; browser-verified flows.
