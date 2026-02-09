import random

from arkpg.game.bosses import BOSS_TEMPLATES, random_boss, weighted_damage_roll


def test_random_boss_hp_within_template_range() -> None:
    rng = random.Random(42)
    boss = random_boss(rng)
    by_name = {b.name: b for b in BOSS_TEMPLATES}
    template = by_name[boss.name]
    assert template.hp_range[0] <= boss.max_hp <= template.hp_range[1]


def test_weighted_damage_scales_with_rating() -> None:
    low_rng = random.Random(5)
    hi_rng = random.Random(5)
    low = weighted_damage_roll(low_rng, 10)
    high = weighted_damage_roll(hi_rng, 60)
    assert high > low
