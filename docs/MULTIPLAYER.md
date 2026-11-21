# The Shared Shore — multiplayer guide (Milestones 3.0–3.2)

Saturday Multiverse v0.3.2 lets friends share one Living Shore. The rules
remain exactly what they were in solo play: **the engine determines what
happens; the AI Game Master describes what happens.** A guest can never
roll a die, spend another player's beads, or move the party — the host's
server validates every intent against its own database.

## Roles

- **Host** — runs the server (their machine, their database, their AI
  configuration). In-game, the host is also a player with a character; they
  can additionally invite, welcome, pause, resume, end the voyage, switch
  turn modes, and send travelers away.
- **Guests** — follow an invitation link, pick a display name, create a
  wanderer, and play their own character. They never see the host's AI
  keys, model URL, or server configuration.

## Hosting (host's side)

1. Start the server (`run.sh` / `run.bat`, or production mode — see
   `docs/DEPLOYMENT.md`).
2. On the title screen: **Host a Shared Voyage** → pick one of your
   campaigns. Your existing wanderer is adopted as the host's character;
   nothing is duplicated.
3. In the lobby: **Make an invitation** — a link of the form
   `http://your-host:8788/?join=<token>` is copied to the clipboard.
4. Optionally wait for players to press **Ready up**, then **Begin the
   voyage**. Everyone goes to the shared Living Shore together.

Invitations are unguessable (32 bytes of entropy), **revocable** (invite
again → revoke old links from the Party panel), optionally limited in uses
and expiry (server API: `uses`, `expires_sec`; defaults to unlimited for 14
days). Tokens are stored only as SHA-256 hashes; the raw token exists once,
in the invite/join response, and never appears in logs, events, or URLs
(streaming uses one-time, 60-second tickets).

## Joining (guest's side)

1. Open the invitation link.
2. Enter your display name and your wanderer's name, pick a road
   (archetype) and specialty.
3. You arrive in the lobby — the host may have enabled approval, in which
   case you wait to be welcomed.
4. Play. Your character is yours alone: your vigor, nerve, beads, pack,
   omen hand and death are tracked server-side per character.

If you close the tab, just return to the site and **Continue** — the
browser holds your session token and the shore restores you exactly where
the story stands (no duplicated characters, no lost events; anything that
happened while you were away is replayed).

## What is shared, what is private

Shared by the whole party: location, weather and tide, the current
adventure and its choices, discoveries, NPC relationships, world flags,
shore upgrades, party consequences and party memories.

Private per character: vigor/nerve, glassbeads, inventory, omen hand,
pending roll windows (Push/Resist), death. Hidden GM facts are never
broadcast — they stay in the host's database and are used only inside the
GM's prompt.

## Traveling together

One player proposes a door (click it). Everyone sees the proposal; the
party departs only when **all connected players** agree. Any decline
cancels the trip. The host can move the party directly (host prerogative).
Late joiners simply arrive wherever the party is — location is a property
of the shared campaign.

## Talking

The **Chat** button opens the party drawer: player messages (with speaker
and color), GM narration, dice announcements, and system events, with
history preserved across reconnects. Player text is stored as data and
always escaped for display — never executed. Rate limit: 10 messages per
30 seconds.

## Playing together

- **Freeform mode** (default): anyone may act; the server serializes
  simultaneous actions and resolves them in one consistent order.
- **Turn order** (host switch in the Party panel): the "lantern" passes in
  join order; acting out of turn is refused server-side; timed-out and
  disconnected players are skipped automatically; the host or the current
  player can pass the lantern early. Default timeout 240s.
- **Dice**: everyone rolls their own checks (risk/push/resist included);
  results are announced to the party. Pending-roll windows are private to
  the roller.
- **Trade & gifts**: offer an item from your pack (the recipient must
  accept); gift 1–10 glassbeads instantly. All transfers are atomic and
  logged.
- **Shared shore improvements**: contribute beads toward an upgrade from
  the Shore panel; when the pot covers the cost, the party builds it
  together — exactly once, whoever contributes last.
- **Party legacy**: adventures ended while a party shares the shore are
  recorded as collective memories (who sailed together and what they did),
  surface in tavern gossip and the Ledger's party section, and persist for
  future visitors to discover.

## The party ledger

The **Party** panel shows the roster (portraits, presence, readiness,
health), incoming trade offers, and host controls (turn mode, pause/resume,
end voyage, welcome/send away). The **Ledger** gained a party section:
membership and shared moments. Personal Echoes are unchanged; a shared
adventure additionally records what the company did together.

## Hosting safely (the short version)

- Solo play never changes: localhost-only, no tokens, no lobby.
- LAN play: start the server bound to your LAN address
  (`SATURDAY_HOST=0.0.0.0`), share invitation links with your LAN IP.
- Remote play: put the server behind a reverse proxy with TLS (see
  `docs/DEPLOYMENT.md`), set `SATURDAY_TOKEN`, and use HTTPS invitation
  links. The Flask development server is **not** for the public internet;
  production mode uses waitress, and a reverse proxy is still recommended.
- Guests cannot reach settings, AI configuration, backups, pack imports,
  campaign creation/deletion or exports — those endpoints reject guest
  tokens server-side. The AI model endpoint is called only by the host's
  server, never by guests.
