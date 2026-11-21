# Milestone verification report — The Shared Shore (3.0 / 3.1 / 3.2)

Build under verification: `0.3.2-shared-shore`, schema `saturday.core.v3`.
Every claim below distinguishes **executed** verification from what could
not be run in this environment. The Milestone 1.5–2.5 report it replaces is
preserved in git history and its results are summarized here as still
passing (the solo suite is part of the 110).

## 1. Automated tests — executed, all passing

`python -m pytest tests/ -q` → **110 tests, 0 failures** (81 pre-existing
solo/multi-milestone tests + 29 new multiplayer tests), plus the solo smoke
walk (`scripts/smoke_test.py`, 35 checks) passing.

Multiplayer coverage (all executed through a multi-client harness — each
client is an independent HTTP caller with its own session token against the
same Flask app; concurrency is real, not simulated):

| Area | Tests |
|---|---|
| Host opens session, adopts the solo character (no duplication) | 1 |
| Invitation → join flow creates independent characters & purses | 1 |
| Invitation expiry, revocation, use-limit enforcement | 1 |
| Party limit + case-insensitive duplicate-name rejection | 1 |
| Token stored hashed at rest (raw token absent from DB) | 1 |
| Missing/forged tokens rejected on gameplay endpoints (403) | 1 |
| Guest isolation: settings/AI/creation/campaign admin refused (403); stripped guest settings view leaks no keys or URLs | 1 |
| Shared scene sync: one client's action appears in the other's event stream; shared turn/drift | 1 |
| Event replay from `last_seq`: only new events, ordered, identical on retry (no duplicates) | 1 |
| Concurrent actions from two clients serialize into an ordered log | 1 (threaded) |
| SSE endpoint: ticket auth, one-time use, live frames | 1 |
| Party travel: proposal → waiting-for-votes → unanimous execution (exactly once); decline cancels | 2 |
| Per-player dice with own characters; separate pending windows (host cannot push guest's roll) | 2 |
| Death is personal; fallen player refused, host unaffected | 1 |
| Structured turn mode enforced server-side; out-of-turn refused; pass-lantern | 1 |
| Chat rate limit (10/30s) + durable history | 1 |
| Trade: consent required, stranger cannot answer, atomic move | 1 |
| Bead gifts atomic and bounded (1–10) | 1 |
| Shared upgrade contributions pool and purchase exactly once | 1 |
| Party legacy recorded on a shared ending (members + consequence) | 1 |
| Reconnect: same player, same character, catch-up; presence sweep marks offline; no character duplication | 1 |
| Process restart (fresh app on same DB): sessions and both tokens survive | 1 |
| Banned player refused | 1 |
| Hostile input: oversized chat, wrong types, script text stored as data, unknown endpoints | 1 |
| Hidden GM facts never broadcast to party streams or views | 1 |
| Solo regression: no token, no lobby, full solo flow untouched | 1 |
| Save migration: v2.5 save → v3 with per-character state moved (purse, deck, inventory owners) | 3 |

## 2. Browser-level verification — executed (Chromium + independent HTTP client)

The decisive demonstration was **genuinely synchronized two-client play**:

- **Host in the browser**: title → *Host a Shared Voyage* → campaign picked →
  lobby (portrait card, ready button, invitation link box) → *Begin the
  voyage* → the shared Living Shore with the multiplayer HUD.
- **Guest from an independent client** (separate HTTP caller, own token):
  joined via the invitation token, acted, chatted, rolled.
- **The host browser received everything live over SSE**: party chip updated
  (⚓ 1/3 → 2/4), the guest's chat line appeared in the party drawer, the
  guest's action produced a GM narration line in the host's dock, and dice
  announcements arrived. Screenshots retained (`download/screenshots/`).
- **Reconnection**: returning to the site and pressing Continue restored the
  host's session automatically (token resume → stream reconnect → catch-up).

Bugs found during browser verification — all **fixed and re-verified**:
stale module caching broke upgrades of the running client (solved with
versioned asset URLs across the whole import chain, plus a release rule:
one `?v=N` for every module); a lobby element id mismatch aborted the
enter-branch (renderLobby died silently inside a swallowed catch — errors
are now surfaced); hosting twice collided on the host's display name (host
re-hand now re-issues a token to the existing row); Continue on a shared
campaign 403'd before the resume could set the token (resume now runs
first); manual checks announced their roll text twice (dice-only emit
added); an SSE test consumed an infinite stream in the buffered client
(test bounded; production clients use EventSource).

## 3. Not run in this environment (stated honestly)

- **Two separate physical browsers/machines.** The browser demo used one
  real browser as host plus a genuinely independent HTTP client (own
  credentials, own connection) — synchronization is real HTTP+SSE, but
  pixel-level rendering of a *second* browser was not captured.
- **A live LLM as Game Master** (mock model server used, as in solo).
- **Windows**: Linux only; launch scripts and the waitress production path
  are written for both but Windows was not exercised.
- **Remote/internet deployment**: LAN-style localhost verification only;
  TLS/reverse-proxy guidance is documented but not executed here.
- Voice chat remains deliberately out of scope (future candidate).

## 4. Acceptance criteria self-check

| Criterion | Status |
|---|---|
| Friends can securely join a hosted campaign (hashed invites, tickets) | ✅ |
| Independent characters with server-side ownership | ✅ |
| Players see each other on the Living Shore (canvas presence) | ✅ |
| Campaign state synchronizes reliably (sequenced events + replay) | ✅ |
| Explore and enter adventures together (shared scenes, party travel) | ✅ |
| One AI GM narrates shared actions consistently (serialized, single narration) | ✅ |
| Host remains the sole rules authority | ✅ |
| Players roll and spend their own resources | ✅ |
| Parties coordinate travel and decisions (votes, turn order) | ✅ |
| Shared chat and interactions (trades, gifts, clue sharing) | ✅ |
| Important actions persist (events, ledger, party legacy) | ✅ |
| Disconnected players return safely (tokens, replay, no duplicates) | ✅ |
| Party adventures create lasting memories | ✅ |
| Solo gameplay unchanged (regression suite) | ✅ |
| Old saves compatible (v3 migration tested) | ✅ |
| Works without an AI connection | ✅ |
| Host/guest permissions enforced | ✅ |
| Genuinely independent clients tested | ✅ (browser + independent HTTP client; two physical machines not available) |
| Documentation and deployment instructions complete | ✅ |
| Complete ZIP delivered | ✅ `saturday-multiverse-shared-shore-m3.2.zip` |

## 5. Known limitations

- Party splitting is out of scope by design: the party shares one location
  and one adventure beat (cooperative travel is the supported model).
- The host cannot yet migrate a session between machines (Milestone 4
  territory); recovery after a restart works on the same host.
- Observers/read-only seats are not implemented (every seat is a player).
- The structured turn timeout auto-advances on stream ticks and requests;
  an idle party with nobody connected will not see timeouts fire until
  someone reconnects.
- Voice chat is not implemented.
- The second browser's rendering was not captured (see honesty note above).
