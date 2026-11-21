# Multiplayer & independent hosting (Milestones 3–4)

Milestone 1 ships solo, but the architecture was built host-authoritative from the
first commit. This document states the design so the early decisions are visible and
the contracts don't drift.

## Principles

1. **The host owns the truth.** All state lives in the host's SQLite database. Clients
   send intents (`POST /action`, `/choose`, `/travel`); the server resolves dice and
   effects exactly as in solo play. A player can never write to someone else's
   campaign database — there is no client-side state to corrupt, only intents.
2. **One code path.** Multiplayer reuses the solo endpoints with a player token
   attached. Solo play is simply a campaign with one host session.
3. **The host owns the AI.** The host's configured model endpoint serves every player;
   guests never see or use their own keys. The host can throttle or disable AI.
4. **No platform dependency.** Saturday Multiverse servers talk to each other (and to
   players) directly. No Z.ai infrastructure, no mandatory cloud service, no phone-home.

## Milestone 3 — Friends on a self-hosted server

- **Sessions.** `sessions(id, campaign_id, player_name, token, role, permissions_json)`
  already exists. The host generates an **invite** (`invites.code`, uses_left,
  expires_at, permissions_json) and shares `<host-url>/join/<code>`. Roles:
  `host`, `player`, `observer`; permissions cover acting, journaling, map, private
  notes.
- **Optional passwords** on invites; rate limits tighten per session; the host can
  revoke a token mid-session.
- **Sync.** A read-only event stream (`GET /api/campaigns/<id>/events?since=<id>`,
  later SSE) broadcasts turn results, dice, scene changes, and dock state. Clients
  render the same narration for everyone; player composers remain free-text.
- **Turn discipline.** The host picks a mode: free-for-all typing, or a speaking-order
  queue enforced server-side.
- **Hosting safely.** Widen the bind only deliberately: put the server behind a reverse
  proxy with TLS, set `SATURDAY_TOKEN`, keep the model endpoint on localhost only, and
  keep rate limits on. The AI endpoint is never exposed to guests.

## Milestone 4 — Public worlds and guest portals

- **Public hosting** is the same server with registration open (guest accounts are
  `sessions` rows with limited permissions). Discovery is a directory the host opts
  into (a simple registry endpoint a server can announce itself to; self-hosted by
  anyone; the game works with it empty).
- **Moderation.** Host tools: block list, mute, kick, session revocation, per-player
  rate limits; an event-log export for audits.
- **Guest portals (cross-server visiting).** A future protocol where a character
  *visits* another host's shore:

  ```
  POST /federation/portal_request
    { visitor_host, character_manifest (hashes + public outline), purpose, duration }
  → host replies with an ephemeral visit_token + allowed scopes
  POST /federation/portal_open   (token) → visit session begins
  ```

  Data contract rules: the **visiting host** ships a signed character manifest
  (id, name, archetype, portrait seed, inventory hashes); the **destination host**
  decides which items may cross (allowlist), what the visitor may take home, and can
  end the visit at any time. Original items stay home unless both hosts allow the
  transfer. Nothing in Milestone 1 pretends this exists — the tables above are the
  only groundwork, and this section is a design commitment, not a feature claim.

## What is deliberately NOT implemented yet

- No WebSocket/SSE sync, no session tokens on gameplay routes, no invite UI.
- No public registry, no federation endpoints.
- The `sessions`/`invites` tables exist so that adding these does not require a
  migration of campaign data.
