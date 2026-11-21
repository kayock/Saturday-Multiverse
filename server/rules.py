"""Saturday Multiverse — The Undertow System (original rules engine).

All mechanics are deterministic application code. The AI Game Master may
*request* checks and propose outcomes, but it never rolls dice, never
computes results, and never mutates state. Every roll is made here with a
cryptographic RNG and recorded in the dice log and event log.

Resolution bands (2d6 + stat modifier + situational modifier):
  12+            SURGE    strong success, minor boon
  10-11          CLEAN    straightforward success
  7-9            RIPTIDE  success at a cost
  <=6            UNDERTOW the current takes hold — failure with complication
  double 6       KICKER   critical: always at least a success, boon applies
  double 1       WIPEOUT  catastrophic failure, extra harm

A GM-called check may be marked "hard" (shift the band one step down) or
"easy" (one step up) — this is how difficulty is expressed without a
secondary chart.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

BANDS = ["wipeout", "undertow", "riptide", "clean", "surge"]

BAND_TEXT = {
    "surge": "Surge — a strong success; the tide briefly works with you.",
    "clean": "Clean — you manage it.",
    "riptide": "Riptide — you manage it, but the sea takes something.",
    "undertow": "Undertow — the current takes hold. It goes wrong.",
    "wipeout": "Wipeout — it goes badly, comprehensively.",
}

HARM_TABLE = {
    # outcome band -> harm dealt (None = none). Harm type chosen by context.
    "surge": 0,
    "clean": 0,
    "riptide": 1,
    "undertow": 2,
    "wipeout": 4,
}


@dataclass
class RollResult:
    dice: list[int] = field(default_factory=list)
    stat_mod: int = 0
    sit_mod: int = 0
    total: int = 0
    outcome: str = "clean"
    text: str = ""
    doubles: bool = False
    risk: bool = False          # declared before the roll: +2 mod, failure hurts more


def _d6() -> int:
    """Cryptographically strong d6."""
    return secrets.randbelow(6) + 1


def _band_index(total: int, shift: int = 0) -> int:
    if total >= 12:
        base = 4          # surge
    elif total >= 10:
        base = 3          # clean
    elif total >= 7:
        base = 2          # riptide
    else:
        base = 1          # undertow
    return max(0, min(4, base + shift))


def roll_check(stat_mod: int = 0, sit_mod: int = 0, shift: int = 0,
               risk: bool = False) -> RollResult:
    """Roll 2d6 + modifiers and resolve the outcome band.

    shift: -1 for a "hard" check, +1 for an "easy" one.
    risk:  declared BEFORE the roll — +2 to the roll, but any failure
           (undertow/wipeout) deals 2 extra harm. Declared by the player,
           applied by the engine.
    """
    sit_total = sit_mod + (2 if risk else 0)
    dice = [_d6(), _d6()]
    total = sum(dice) + stat_mod + sit_total
    doubles = dice[0] == dice[1]

    if doubles and dice[0] == 6:
        outcome = "surge"          # kicker: crit
    elif doubles and dice[0] == 1:
        outcome = "wipeout"        # wipeout: crit fail
    else:
        outcome = BANDS[_band_index(total, shift)]

    result = RollResult(
        dice=dice,
        stat_mod=stat_mod,
        sit_mod=sit_total,
        total=total,
        outcome=outcome,
        doubles=doubles,
        risk=risk,
    )
    risk_note = " (risked)" if risk else ""
    result.text = (
        f"2d6 [{dice[0]}+{dice[1]}] {stat_mod:+d} stat {sit_total:+d} situation "
        f"= {total} → {BAND_TEXT[outcome]}{risk_note}"
    )
    return result


def bump_band(outcome: str) -> str | None:
    """A Push moves the band ONE step toward success — but only from a
    failure or a partial. Clean and Surge cannot be pushed; crits are fate.
    Returns the new outcome, or None when a push is not possible."""
    upgrades = {"undertow": "riptide", "riptide": "clean"}
    return upgrades.get(outcome)


def resist_harm(harm: int) -> int:
    """Resisting halves the incoming harm, rounding down (1 -> 0)."""
    return max(0, harm // 2)


def harm_for(outcome: str, risk: bool = False) -> int:
    """Harm for an outcome band; a declared Risk adds 2 on any failure."""
    base = HARM_TABLE.get(outcome, 0)
    if risk and outcome in ("undertow", "wipeout"):
        base += 2
    return base


def draw_from_deck(draw_pile: list[dict], discard: list[dict]) -> tuple[dict | None, list[dict], list[dict]]:
    """Draw one card. Reshuffles discard into the pile when empty.

    Returns (card_or_None, new_pile, new_discard). Purely mechanical.
    """
    if not draw_pile:
        if not discard:
            return None, draw_pile, discard
        draw_pile = list(discard)
        discard = []
        # deterministic shuffle via crypto RNG
        for i in range(len(draw_pile) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            draw_pile[i], draw_pile[j] = draw_pile[j], draw_pile[i]
    if not draw_pile:
        return None, draw_pile, discard
    card = draw_pile.pop()
    discard.append(card)
    return card, draw_pile, discard


def skill_to_stat(skill: str) -> str:
    """Map a skill name to its governing stat."""
    mapping = {
        "notice": "wits",
        "lore": "wits",
        "persuade": "mettle",
        "fight": "might",
        "endure": "might",
        "bind": "bind",
    }
    return mapping.get(skill, "wits")


def apply_harm(character_row: dict, harm: int, harm_type: str) -> dict:
    """Apply harm to Vigor (body) or Nerve (mind). Returns updated dict.

    Character_row is a plain dict with keys vigor/vigor_max/nerve/nerve_max.
    Clamped at 0; callers decide what zero means for the story.
    """
    if harm <= 0:
        return character_row
    if harm_type == "nerve":
        character_row["nerve"] = max(0, character_row["nerve"] - harm)
    else:
        character_row["vigor"] = max(0, character_row["vigor"] - harm)
    return character_row
