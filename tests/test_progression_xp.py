from arkpg.game.economy import level_from_xp, xp_for_level
from arkpg.bot.profile_card import _xp_progress


def test_level_from_xp_respects_thresholds() -> None:
    assert level_from_xp(0) == 1
    assert level_from_xp(xp_for_level(2) - 1) == 1
    assert level_from_xp(xp_for_level(2)) == 2
    assert level_from_xp(818) == 4


def test_xp_progress_stays_within_current_level() -> None:
    current, needed, fill = _xp_progress(818, 4)
    assert current == 113
    assert needed == xp_for_level(5) - xp_for_level(4)
    assert 0.0 < fill < 1.0
