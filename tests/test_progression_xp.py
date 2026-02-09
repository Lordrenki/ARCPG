from arkpg.game.economy import level_from_xp, scale_stats_with_level, xp_for_level
from arkpg.bot.profile_card import _xp_progress


def test_level_from_xp_respects_thresholds() -> None:
    assert level_from_xp(0) == 1
    assert level_from_xp(xp_for_level(2) - 1) == 1
    assert level_from_xp(xp_for_level(2)) == 2
    assert level_from_xp(818) == 3


def test_xp_progress_stays_within_current_level() -> None:
    current, needed, fill = _xp_progress(818, 3)
    assert current == 198
    assert needed == xp_for_level(4) - xp_for_level(3)
    assert 0.0 < fill < 1.0


def test_stat_scaling_with_level() -> None:
    stats = scale_stats_with_level({"base_combat": 12, "base_tech": 11, "base_luck": 9}, 6)
    assert stats["combat"] == 22
    assert stats["tech"] == 21
    assert stats["luck"] == 14
