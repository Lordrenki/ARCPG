from types import SimpleNamespace

from arkpg.db.models import ItemType, Rarity
from arkpg.game.crafting import crafting_recipe_for_item, is_craftable_item
from arkpg.game.service import _blueprint_source_ids_for_item


def _item(source_id: str, source_type: str, item_type: ItemType, rarity: Rarity):
    return SimpleNamespace(
        type=item_type,
        rarity=rarity,
        metadata_json={"source_id": source_id, "source_type": source_type, "description": ""},
    )


def test_medium_and_heavy_shields_are_craftable_without_blueprint() -> None:
    medium = _item("medium_shield", "shield", ItemType.ARMOR, Rarity.RARE)
    heavy = _item("heavy_shield", "shield", ItemType.ARMOR, Rarity.EPIC)

    assert is_craftable_item(medium)
    assert is_craftable_item(heavy)
    assert _blueprint_source_ids_for_item(medium) == []
    assert _blueprint_source_ids_for_item(heavy) == []

    medium_recipe = dict(crafting_recipe_for_item(medium))
    heavy_recipe = dict(crafting_recipe_for_item(heavy))

    assert medium_recipe["electrical_components"] >= 4
    assert heavy_recipe["electrical_components"] > medium_recipe["electrical_components"]
    assert "arc_alloy" in heavy_recipe


def test_weapon_tier_blueprints_include_base_weapon_blueprint() -> None:
    tier_one = _item("tempest", "smg", ItemType.WEAPON, Rarity.EPIC)
    tier_four = _item("tempest_t4", "smg", ItemType.WEAPON, Rarity.EPIC)

    assert "tempest_blueprint" in _blueprint_source_ids_for_item(tier_one)
    assert "tempest_blueprint" in _blueprint_source_ids_for_item(tier_four)


def test_weapon_mark_tiers_increase_recipe_requirements() -> None:
    mk1 = _item("stitcher", "smg", ItemType.WEAPON, Rarity.COMMON)
    mk2 = _item("stitcher_t2", "smg", ItemType.WEAPON, Rarity.COMMON)
    mk3 = _item("stitcher_t3", "smg", ItemType.WEAPON, Rarity.COMMON)
    mk4 = _item("stitcher_t4", "smg", ItemType.WEAPON, Rarity.COMMON)

    r1 = dict(crafting_recipe_for_item(mk1))
    r2 = dict(crafting_recipe_for_item(mk2))
    r3 = dict(crafting_recipe_for_item(mk3))
    r4 = dict(crafting_recipe_for_item(mk4))

    assert r2["light_gun_parts"] > r1["light_gun_parts"]
    assert r3["light_gun_parts"] > r2["light_gun_parts"]
    assert r4["light_gun_parts"] > r3["light_gun_parts"]

    assert "electrical_components" in r2
    assert "arc_alloy" in r3
    assert "advanced_mechanical_components" in r4
