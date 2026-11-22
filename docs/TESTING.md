# Testing — what works, what was verified, what is not finished

Written at Milestone 1 (0.1.0-milestone1). This file is intentionally blunt.

## Automated verification (all passing)

- `python -m pytest tests/ -q` → **50 tests**:
  - `test_rules.py` — band boundaries, kicker/wipeout doubles (RNG monkeypatched),
    harm table, clamping, deck draw/reshuffle, 4000-roll distribution sanity.
  - `test_worldpacks.py` — pack validation, **content integrity**: every adventure
    choice `goto` target exists, every archetype kit item and ending reward item is in
    the catalog, unique ids, lore file loads, import round-trip + id sanitization.
  - `test_ai_adapter.py` — JSON extraction (fenced, chatty, embedded quotes, garbage),
    config validation, key masking, connection failures, and a **full game turn over
    real HTTP** against the bundled mock OpenAI-compatible server: AI turn applied,
    app rolled the requested check, catalog-validated item grant, hidden note stored
    hidden and absent from the visible view, transcript order.
  - `test_gm_flow.py` — campaign lifecycle, honest fallback turn, travel + discovery
    chain, tide gating, adventure door → scenes → locked choices → endings
    (beacon/pact/taken branches), rewards, rest gating, item use, manual checks,
    QR allowlist (hostile payloads inert), FTS search, export→import round-trip,
    archive.
  - `test_api.py` — health, settings mask + validation, AI test endpoint offline path,
    packs + detail, JSON 404s, client shell served, full campaign HTTP lifecycle,
    backup/restore, 404s.
- `scripts/smoke_test.py` → 35-check end-to-end walk without pytest.
- Regression: both suites re-run green after every bug found in browser verification.

## Verified in a real browser (Chromium via automation, 1440×900 and 390×844)

- Title screen (animated door/Beam, tagline, honest AI badge).
- Character creation → campaign created → hub renders with HUD, doors, lighthouse,
  tavern; dice-strip phantom and drawer-visibility bugs found and fixed.
- Canvas door click → Salt-Grave Signal entered; quest + fact chips applied.
- Scene progression: arrival → wreckline; locked "climb to the signal room" shows the
  brass-key hint; resume after leaving: "The door remembers you."
- Map panel (8 pins, unmarked pins honest, tide line), settings panel (model config,
  sliders), mobile layout (HUD stacks, no horizontal overflow).
- **Real AI turn through the UI**: mock GM enabled via API → badge `GM: mock-gm-1` →
  composer action → AI narration + suggestion chips + omen draw on cadence; the null-
  dice crash found in this pass was fixed and re-verified.
- QR scanner burst simulation → allowlist accepted `SM:CMD:MAP` → toast + map opened.
- Save & resume: campaign closed/reloaded repeatedly through the Continue flow.

## Known gaps / honest status (not finished on purpose)

- **AI providers were tested against a local mock endpoint, not a live LLM.** The
  adapter is plain OpenAI-compatible HTTP; a real model must be able to emit the JSON
  contract (retry logic included). Report quality depends on your model.
- **Multiplayer is groundwork only** — schema + contracts (`docs/MULTIPLAYER.md`).
  No sessions, sync, or invites are wired.
- **Voice narration**, **public hosting**, **cross-server portals**: designed, not built.
- Audio is synthesized and therefore deliberately simple; it has no authored music.
- The Offline Storyteller is a safety net, not a writer — it keeps mechanics going
  with templated prose and never pretends to be a model.
- No streaming of model output (single-shot turns, ~5–30 s on local hardware).
- Windows is supported by design (pure Python + Flask, `run.bat`) but was not
  exercised in this environment; Linux was.
- Canvas hub art is procedural and stylish but not hand-illustrated; vignettes are
  stylized vector scenes, not painted art.

## Reproducing the verification

```bash
pip install flask pytest
python -m pytest tests/ -q
python scripts/smoke_test.py
./run.sh            # then open http://127.0.0.1:8788
python scripts/mock_gm_server.py   # optional AI stand-in on :8090
```

## v0.4.0-hotfix3 — suite status (2026-11-22)

- `python -m pytest tests/ -q --ignore=tests/browser` → **260 tests** (228
  prior + 32 new regressions in `tests/test_m42_hotfix3.py`), all passing.
- `python -m pytest tests/browser/test_browser_flows.py -q` → 4 browser
  acceptance flows passing (Chromium; note: run the FILE — the suite-level
  `collect_ignore_glob` intentionally ignores `tests/browser/*` when
  collecting the whole tree, so the CI browser job names the file
  explicitly).
- `scripts/verify_hotfix3_lan.py` → 35/35 live checks: real HTTP + HTTPS
  servers, CA-verified clients, explicit campfire sharing over TLS, SSE,
  strict certificate refusals at startup, and a genuine hotfix2 → hotfix3
  save migration against the pristine hotfix2 tree.
- Cross-platform CI: no Unix-only imports remain in any CI-scheduled test
  module (enforced by `test_ci_suite_has_no_unix_only_code`); subprocess
  startup output is captured by a bounded background reader thread and
  children are always reaped; `requirements-dev.txt` installs
  `cryptography>=3.4` (still optional for players). The GitHub Actions
  matrix itself has not been executed from this environment — the Windows
  legs are code-verified only until the workflow runs on GitHub.

## v0.4.0-hotfix4 — suite status (2026-11-22)

- `python -m pytest tests/ -q --ignore=tests/browser` → **285 tests** (260
  prior + 25 new regressions in `tests/test_m43_hotfix4.py`), all passing.
  Four hotfix3-era tests that encoded the too-permissive scope-based
  sharing were updated to the hotfix-4 contract (acquisition recorded
  through the engine's delivery primitive before sharing).
- `pytest tests/browser/test_browser_flows.py -q` → 4 browser flows passing.
- `scripts/verify_hotfix4_lan.py` → 26/26 live checks over direct HTTPS:
  picker authorization (403 without a valid token, no fallback), real
  NPC-conversation acquisition, exact party-share grants, forged-reference
  refusals, restart persistence, and the solo no-token flows over HTTP.
- `scripts/verify_hotfix3_lan.py` → 36/36 (its two knowledge checks were
  updated to the hotfix-4 authorization semantics).

## v0.4.0-hotfix5 — suite status (2026-11-22)

- `python -m pytest tests/ -q --ignore=tests/browser` → **310 tests** (285
  prior + 25 new regressions in `tests/test_m44_hotfix5.py`), all passing.
  13 of them reproduced the two confirmed defects against the untouched
  hotfix-4 source (failing-first). Four hotfix2/3 tests encoding the old
  recap presence-rule were updated to record delivery; hotfix-4 talk tests
  now use disclosure-triggering conversation topics.
- `pytest tests/browser/test_browser_flows.py -q` → 4 browser flows passing.
- `scripts/verify_hotfix5_lan.py` → 29/29 live checks over direct HTTPS:
  the Lampkeeper's GM-only deep secret absent from response, knowledge,
  transcripts, events, picker and share attempts; disclosure-tracked tavern
  conversations; exact party shares; unified recap entitlement; restart
  persistence; solo flows over plain HTTP.
- `scripts/verify_hotfix4_lan.py` → 26/26 (talk topics updated to the
  disclosure-tracking semantics). `scripts/verify_hotfix3_lan.py` → 36/36.
