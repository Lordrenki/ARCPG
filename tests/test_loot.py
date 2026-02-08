from arkpg.game.loot import LootRoller


def test_roll_rarity_deterministic() -> None:
    roller_a = LootRoller("abc")
    roller_b = LootRoller("abc")
    assert [roller_a.roll_rarity("Residential") for _ in range(6)] == [roller_b.roll_rarity("Residential") for _ in range(6)]
