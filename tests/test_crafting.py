from types import SimpleNamespace

from arkpg.db.models import ItemType, Rarity
from arkpg.game.crafting import crafting_recipe_for_item, is_craftable_item


def _item(source_id: str, source_type: str, item_type: ItemType, rarity: Rarity, description: str = ""):
    return SimpleNamespace(
        type=item_type,
        rarity=rarity,
        metadata_json={"source_id": source_id, "source_type": source_type, "description": description},
    )


def test_crafting_recipes_cover_weapon_gadget_and_healing() -> None:
    weapon = _item("osiris", "assault rifle", ItemType.WEAPON, Rarity.RARE)
    gadget = _item("frag_grenade", "quick use", ItemType.GADGET, Rarity.UNCOMMON)
    healing = _item("vita_shot", "quick use", ItemType.GADGET, Rarity.RARE, description="restores health")

    assert is_craftable_item(weapon)
    assert is_craftable_item(gadget)
    assert is_craftable_item(healing)

    weapon_recipe = dict(crafting_recipe_for_item(weapon))
    gadget_recipe = dict(crafting_recipe_for_item(gadget))
    healing_recipe = dict(crafting_recipe_for_item(healing))

    assert "light_gun_parts" in weapon_recipe
    assert "chemicals" in gadget_recipe
    assert "bandage" in healing_recipe


def test_legendary_weapon_recipe_has_high_tier_materials() -> None:
    weapon = _item("legendary_rifle", "assault rifle", ItemType.WEAPON, Rarity.LEGENDARY)
    recipe = dict(crafting_recipe_for_item(weapon))
    assert "arc_alloy" in recipe
    assert "advanced_mechanical_components" in recipe
