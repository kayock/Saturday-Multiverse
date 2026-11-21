"""The Undertow System — dice mechanics must be app-authoritative."""
from server import rules


def test_roll_structure():
    for _ in range(200):
        r = rules.roll_check(stat_mod=1, sit_mod=-1)
        assert len(r.dice) == 2
        assert all(1 <= d <= 6 for d in r.dice)
        assert r.total == sum(r.dice) + 1 - 1
        assert r.outcome in rules.BANDS


def test_band_boundaries():
    assert rules._band_index(12) == 4   # surge
    assert rules._band_index(10) == 3   # clean
    assert rules._band_index(9) == 2    # riptide
    assert rules._band_index(7) == 2
    assert rules._band_index(6) == 1    # undertow
    assert rules._band_index(2) == 1


def test_band_shift_hard_and_easy():
    # a 10 is Clean normally, Riptide on a hard check, Surge easy
    assert rules._band_index(10, shift=-1) == 2
    assert rules._band_index(10, shift=1) == 4


def test_kicker_and_wipeout(monkeypatch):
    # double sixes always surge; double ones always wipe out
    monkeypatch.setattr(rules, "_d6", lambda: 6)
    assert rules.roll_check(stat_mod=-5).outcome == "surge"
    monkeypatch.setattr(rules, "_d6", lambda: 1)
    assert rules.roll_check(stat_mod=5).outcome == "wipeout"
    # a mixed roll (6 then 1) follows the band table instead: total 7 → riptide
    seq = iter([6, 1])
    monkeypatch.setattr(rules, "_d6", lambda: next(seq))
    r = rules.roll_check(stat_mod=0)
    assert r.total == 7 and r.outcome == "riptide"


def test_harm_table():
    assert rules.harm_for("surge") == 0
    assert rules.harm_for("clean") == 0
    assert rules.harm_for("riptide") == 1
    assert rules.harm_for("undertow") == 2
    assert rules.harm_for("wipeout") == 4


def test_apply_harm_clamps():
    ch = {"vigor": 2, "vigor_max": 10, "nerve": 5, "nerve_max": 10}
    rules.apply_harm(ch, 5, "vigor")
    assert ch["vigor"] == 0
    rules.apply_harm(ch, 3, "nerve")
    assert ch["nerve"] == 2
    rules.apply_harm(ch, 0, "nerve")
    assert ch["nerve"] == 2


def test_skill_to_stat():
    assert rules.skill_to_stat("bind") == "bind"
    assert rules.skill_to_stat("fight") == "might"
    assert rules.skill_to_stat("notice") == "wits"
    assert rules.skill_to_stat("persuade") == "mettle"


def test_deck_draw_and_reshuffle():
    pile = [{"id": 1}, {"id": 2}]
    discard = [{"id": 3}]
    card, p2, d2 = rules.draw_from_deck(pile, discard)
    assert card is not None
    assert len(d2) == 2 and len(p2) == 1
    # exhaust pile → reshuffle from discard
    p3, d3 = [], list(d2)
    card2, p4, d4 = rules.draw_from_deck(p3, d3)
    assert card2 is not None and len(p4) == 1 and len(d4) == 1
    # totally empty deck
    card3, _, _ = rules.draw_from_deck([], [])
    assert card3 is None


def test_outcomes_distribution_is_sane():
    """A +0 check should mostly land in riptide/clean across many rolls."""
    counts = {"surge": 0, "clean": 0, "riptide": 0, "undertow": 0, "wipeout": 0}
    n = 4000
    for _ in range(n):
        counts[rules.roll_check().outcome] += 1
    assert counts["riptide"] / n > 0.30
    assert counts["clean"] / n > 0.10
    assert counts["undertow"] / n > 0.25
    assert counts["surge"] / n > 0.02
