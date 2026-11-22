# Browser tests (Playwright)

These specs run against a live server via Playwright. Locally:

```bash
pip install -r requirements-dev.txt
playwright install chromium
pytest tests/browser -q
```

In CI they run in the `browser` job (see `.github/workflows/ci.yml`).
The game's production architecture is no-build plain ES modules — the specs
need no bundler; they start `server.app` on a scratch data directory and
drive real Chromium sessions.
