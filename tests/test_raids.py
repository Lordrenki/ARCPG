import random

from arkpg.game.raids import RaidEnemy, RaidState, begin_raid, raid_rewards, resolve_action, strip_equipped_loadout


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


class StubRng:
    def __init__(self, random_values: list[float], randint_values: list[int] | None = None):
        self._random = iter(random_values)
        self._randint = iter(randint_values or [])

    def random(self) -> float:
        return next(self._random)

    def randint(self, _a: int, _b: int) -> int:
        return next(self._randint)

    def choice(self, seq):
        return seq[0]


def test_failed_dodge_still_takes_damage() -> None:
    state = RaidState(
        player_level=10,
        player_max_hp=100,
        player_hp=100,
        enemy=RaidEnemy(name="Test Enemy", level=15, max_hp=120, hp=120, min_damage=20, max_damage=20),
    )

    result = resolve_action(state, "dodge", StubRng(random_values=[0.95, 0.10], randint_values=[20]))

    assert result.raid_over is False
    assert state.player_hp == 76


def test_consecutive_dodges_get_punished() -> None:
    state = RaidState(
        player_level=10,
        player_max_hp=100,
        player_hp=100,
        enemy=RaidEnemy(name="Test Enemy", level=15, max_hp=120, hp=120, min_damage=20, max_damage=20),
    )

    resolve_action(state, "dodge", StubRng(random_values=[0.40]))
    resolve_action(state, "dodge", StubRng(random_values=[0.55, 0.10], randint_values=[20]))

    assert state.player_hp == 76


def test_strip_equipped_loadout_clears_all_slots() -> None:
    stripped, lost = strip_equipped_loadout(
        {
            "weapons": [{"name": "Kettle I", "item_id": 1}],
            "gadget": {"name": "Pulse Grenade", "item_id": 2},
            "healing": {"name": "Bandage", "item_id": 3},
            "shield": {"name": "Light Shield", "item_id": 4},
        }
    )

    assert stripped == {"weapons": [], "gadget": None, "healing": None, "shield": None}
    assert lost == ["Kettle I", "Pulse Grenade", "Bandage", "Light Shield"]
