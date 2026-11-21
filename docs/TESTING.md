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
