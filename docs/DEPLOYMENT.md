# Deployment & security guide — The Shared Shore

## The three ways to run Saturday Multiverse

### 1. Solo play (default, zero configuration)
`run.sh` / `run.bat` binds to `127.0.0.1:8788`. Nothing leaves your machine,
no tokens exist, no lobby appears. This remains the recommended mode for a
single player and requires nothing from this guide.

### 2. LAN play (friends on your local network)
```
# Linux
SATURDAY_HOST=0.0.0.0 ./run.sh
# Windows (PowerShell)
$env:SATURDAY_HOST="0.0.0.0"; .\run.bat
```
Share invitation links of the form `http://<your-LAN-IP>:8788/?join=<token>`.
Optionally set `SATURDAY_TOKEN=<secret>` so non-loopback clients must also
present the shared secret (`X-Auth-Token` header — the join link flow adds
it automatically when configured; see settings screen). Your firewall must
allow the port. LAN play is the sweet spot: no TLS needed, everything stays
inside your network.

### 3. Remote play (friends across the internet)
Never expose the Flask development server directly to the internet. Two
supported patterns:

**Production mode (built-in):**
```
SATURDAY_HOST=0.0.0.0 SATURDAY_PRODUCTION=1 ./run.sh
```
This serves through **waitress** (pure Python, works on Windows and Linux,
threaded — required for SSE). Waitress is a solid WSGI server, but it still
speaks plain HTTP.

**Recommended: reverse proxy with TLS** in front of either serving mode.

- Caddy (easiest, automatic certificates):
  ```
  play.example.com {
      reverse_proxy 127.0.0.1:8788
  }
  ```
- nginx:
  ```
  location / {
      proxy_pass http://127.0.0.1:8788;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_read_timeout 3600s;   # SSE streams are long-lived
      proxy_buffering off;        # required for Server-Sent Events
  }
  ```
  plus TLS (`certbot --nginx`).

Then bind the game to localhost only (`SATURDAY_HOST=127.0.0.1`) and let the
proxy be the only public listener. Share `https://…` invitation links.

## Security model (what the server enforces)

- **Invitations**: 32-byte URL-safe tokens, sent as links, stored as SHA-256
  hashes only. Revocable, expiring, optionally use-limited. Joining requires
  a valid invitation; banned/removed tokens are refused.
- **Session tokens**: every player holds a session token (separate from the
  invitation). It travels in the `X-MP-Token` header on every request — a
  custom header browsers cannot attach cross-site without CORS, which
  serves as the CSRF defense. The stream uses one-time 60-second tickets so
  tokens never appear in URLs.
- **Ownership**: every gameplay request resolves to a player row; state
  changes are scoped to that player's character. Rolling, pushing,
  resisting, trading, gifting, building, chatting and acting are all
  validated server-side. There is no client authority anywhere.
- **Guest isolation**: settings, AI configuration, backups, pack imports,
  campaign creation/archiving, exports and imports reject guest tokens.
  Guests receive only the AI enabled-flag and model name — never keys or
  endpoint URLs. The host's model endpoint is contacted only by the host's
  server process.
- **Hidden information**: hidden GM facts are never broadcast over the
  stream or included in any party-visible payload (covered by tests).
- **Rate limits**: per-IP API limits (existing) plus per-player chat limits
  (10 per 30s). The SSE stream is exempt from the per-request counter.
- **Input validation**: display names and chat text are length-clamped and
  stripped of control characters; they are stored as data and HTML-escaped
  on render. JSON bodies are size-limited by the framework; malformed
  requests return 400s (covered by hostile-input tests).
- **No secrets in events**: the `mp_events` stream and the event log never
  contain tokens, keys, or hidden facts.

## Secrets and data hygiene

- AI API keys live in the host's `userdata/` settings — never in the repo,
  never in broadcasts, never in guest responses.
- `userdata/` (database, backups, exports) is excluded from packaging and
  version control.
- Backups: Settings → Saves & data; the multiplayer tables are ordinary
  SQLite rows and migrate/restore with the database.

## Milestone-4 compatibility notes (not implemented)

Character ownership is explicit, world identifiers are stable, and every
mechanical change is recorded in append-only event tables — the groundwork
a future cross-server visiting protocol needs. No federation endpoints
exist in this release.
