import random

from arkpg.game.raids import begin_raid, raid_rewards, resolve_action


def test_begin_raid_generates_high_level_enemy() -> None:
    state, opening = begin_raid(
        player_level=12, player_hp=95, player_max_hp=120, rng=random.Random(7)
    )
    assert state.enemy.level >= 16
    assert state.enemy.hp == state.enemy.max_hp
    assert opening


def test_raid_attack_or_enemy_action_advances_turn() -> None:
    state, _ = begin_raid(player_level=10, player_hp=100, player_max_hp=100, rng=random.Random(2))
    result = resolve_action(state, "attack", random.Random(3))
    if not result.raid_over:
        assert state.turn == 2
        assert state.enemy.hp < state.enemy.max_hp or state.player_hp < state.player_max_hp


def test_raid_retreat_ends_encounter() -> None:
    state, _ = begin_raid(player_level=8, player_hp=100, player_max_hp=100, rng=random.Random(9))
    result = resolve_action(state, "retreat", random.Random(9))
    assert result.raid_over is True
    assert result.player_won is False


def test_raid_rewards_scale_with_enemy_level() -> None:
    low = raid_rewards(enemy_level=12, rng=random.Random(4))
    high = raid_rewards(enemy_level=24, rng=random.Random(4))
    assert high[0] > low[0]
    assert high[1] > low[1]
