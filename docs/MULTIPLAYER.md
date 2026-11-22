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

## Explicit campfire knowledge sharing (v0.4.0-hotfix3/4)

Telling a campfire story shares **nothing by itself** — your tale is
player-authored flavor, never a knowledge grant. When you actually want to
spread information, the campfire form lists what YOUR character may share
(their visited places, discoveries, and the specific rumors the engine has
recorded them learning) and you tick exactly the items to give the party:

- **The picker is authorized (hotfix 4).** On a campaign with an active
  multiplayer session a valid player token is required: missing, invalid,
  banned, removed or wrong-campaign tokens receive **403** with no
  character-owned knowledge, and never fall back to the campaign's main
  character. Solo campaigns need no token — the campaign's actual session
  state decides, never a caught authentication failure. Spectators receive
  an empty picker (they hold no character).
- **Knowledge is per specific memory (hotfix 4/5).** A hearing scope
  (`kind='heard', ref='tavern'`) is evidence of a past interaction, not
  proof of knowing every present and future rumor there. The engine records
  which exact memories a character learned at authoritative delivery points
  — an NPC conversation that actually speaks them, their own arrival tale,
  a visitor tale told at their rest, or a party member sharing it at the
  fire. Only those memories (plus public `all`-scoped world news) appear in
  the picker and may be shared. Leave the tavern and the later rumors are
  not yours to tell; return and hear them, and they become shareable — in
  the picker AND in the returning-player recap, which since hotfix 5 uses
  the same specific-memory rule (a past visit never discloses later
  rumors). NPC conversations carry only what the NPC actually said: their
  internal GM-only, hidden and deep records never enter dialogue, AI
  prompts, responses, transcripts or events, and are never recorded as
  learned. Scripted mysteries reveal through explicit engine-authorized
  story events (`experience.reveal_memory`).
- **The engine validates every selection server-side.** You can only share
  what your character genuinely holds; another character's discovery, a
  GM-only secret, a forged or cross-campaign memory id, or a memory you
  never heard is refused with a reason and granted to no one — even when a
  modified client submits the id directly, bypassing the picker.
- **A hearing scope is never granted.** You share one specific rumor, not
  "everything the tavern says": rumors recorded at that place LATER stay
  private until someone hears them in person or shares them explicitly.
- **What was already recorded at share time stays readable** to the party;
  future discoveries and future rumors do not flow automatically.
- **Every grant is auditable** (the `knowledge_shares` table: what, by
  whom, when, from which story) and idempotent — retries never duplicate a
  grant. Shared knowledge survives disconnects and application restarts.
- **Spectators** follow the shared feed: explicitly shared items reach
  them; private discoveries and unshared place gossip never do.
- **Old saves migrate conservatively** (see `docs/MIGRATION.md`):
  historical blanket shares stay readable but no longer authorize memories
  created after they were made.

API surface: `GET /campaigns/<cid>/campfire/shareable` (the picker, per
teller) and `POST /campaigns/<cid>/campfire` with an optional `share` array
of place refs and/or memory ids; the response reports `share.shared` and
`share.rejected` with reasons.

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


## v0.3.6 — Party splitting, spectators, and the watchdog

### Party splitting
- `POST /api/campaigns/<cid>/mp/split {"location_id": ...}` — your character
  walks apart. Narration you cause while split is emitted with `loc:<place>`
  visibility: only characters standing in the same place see it. Private
  discoveries stay private.
- `POST .../mp/regroup` — return yourself; with `{"everyone": true}` (host)
  gather the whole party.
- Shared travel still moves the party **as one** by default and clears split
  overrides. The story's thread (an active adventure beat) belongs to the
  place where it lives; characters elsewhere act freely but cannot advance
  the beat until they regroup (`choose` refuses with a clear message).

### Spectators
- Host creates a spectator invite (`POST /campaigns/<cid>/mp/invite-spectator`).
  Spectators see party-wide events only (never split-group narrations), can
  reconnect, and cannot act, roll, trade, travel or touch combat — the engine
  refuses, not just the UI.

### Shared D&D combat
- Encounters span the session: initiative across all participants, each
  player acts on their own character's turn through
  `POST /campaigns/<cid>/combat`, ownership enforced server-side (acting for
  another character is impossible). Reinforcements may join in round one.

### The watchdog
An in-process daemon thread (no extra service) sweeps every 15 seconds:
expired structured-mode turns auto-advance with a visible system line, and
idle combat turns are auto-defended. Sweeps are idempotent, timestamp-driven
and therefore safe across restarts.


## Per-player recaps and dismissal (v0.4.0-hotfix2)

- **Your recap is yours.** What your character has visited, discovered and
  heard in person drives what the recap shows. A tavern tale reaches only
  characters who were in the tavern — or those it was shared with.
- **Sharing happens at the campfire.** Posting a story shares the teller's
  knowledge with the whole party (spectators included). Nothing else grants
  another player's discoveries.
- **Dismissal is per player.** `POST /api/campaigns/<cid>/recap/dismiss`
  records only YOUR last-seen markers; other players' unseen events stay
  unseen. Markers live in SQLite (`recap_seen`) and survive disconnects,
  application restarts and save/restore.
- **Legacy saves migrate conservatively**: every existing viewer starts from
  the old shared marker (per-player history never existed), new events after
  that marker appear, and nothing is fabricated or replayed.

## LAN and HTTPS (v0.4.0-hotfix1)

- Hosting on the LAN: run with `SATURDAY_HOST=0.0.0.0` and share
  `http://<lan-ip>:8788/?join=<invite token>`. Invitation links are built by
  the browser from its own address (`location.origin`), so an HTTPS host
  automatically produces `https://…` links.
- Personal expedition goals are owned by their creator: other guests cannot
  progress or abandon them (the host may manage any goal). Party goals stay
  open to every member. Verified goal progress only comes from engine events
  — manual progress is recorded as player-authored.
- The returning-player recap is player-aware when a session token is
  presented, and never contains deep-scoped NPC knowledge or split-party
  narration (those remain behind the usual visibility filters).
- Over HTTPS, SSE streams and reconnection behave identically; see
  docs/DEPLOYMENT.md for certificate setup and client trust steps.
