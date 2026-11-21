# The Worldbuilding Workshop (collaborative homebrew)

Homebrew uses the **same universal Campaign Forge** as imported novels — same
draft model, same validators, same installer. There is no separate homebrew
system, no new accounts, no keys: identity comes from the existing
multiplayer session tokens (the local player is the creator when no session
is open).

## Roles

- **Creator** — opens the world (`POST /api/forge/collab`), invites
  collaborators through the normal shared-shore invite flow, reviews
  proposals, resolves conflicts, and is the only one who can approve
  publication into the local Library.
- **Collaborators** — join the workshop session with a normal invite and
  propose NPCs, locations, quests, lore and GM secrets.

## Contribution flow

1. A contributor proposes deterministic edit ops
   (`POST /forge/collab/<id>/contribute`) with the revision they based their
   work on (`base_rev`).
2. The creator reviews. **Conflicts are recomputed at review time**: if the
   areas a proposal touches changed since `base_rev`, applying is refused
   until the creator either asks the author to rebase or explicitly applies
   with `force`. Nothing is silently overwritten.
3. Applied proposals create a normal draft **revision** — full history,
   comparison, restore, duplication and export all work.

## AI assistance

`POST /forge/collab/<id>/suggest` returns a suggestion for one of: npc,
location, quest, dialogue, encounter, lore, branch. Suggestions are returned
to the requester **only** and never applied; turning one into content
requires an explicit proposal and the creator's review. Without a configured
model, a clearly-marked offline template is returned instead.

## Spoiler boundaries

Helping build a world does not reveal its secrets. GM secrets carry
authoritative authorship (stamped with the contributor's player id when a
proposal is applied). A contributor's view of the pack — and of the proposal
list — filters everyone else's hidden material behind a placeholder. During
play, GM secrets never reach clients anyway.

## Publication

Approval (`POST /forge/collab/<id>/approve`, creator only) runs the same
`validate_pack` + adventure-flow gates as Dracula or any literary adaptation
and installs the pack into the local Library (`userdata/worldpacks`). It
appears as a playable door immediately and supports multiplayer voyages.
Installation is local-only: imported or private sources stay private, and no
upload/publish path exists anywhere in the codebase.
