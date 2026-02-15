from types import SimpleNamespace

from arkpg.db.models import ItemType, Rarity
from arkpg.game.crafting import craft_autocomplete_matches, craftable_items_from_inventory, crafting_recipe_for_item, is_craftable_item


def _item(
    source_id: str,
    source_type: str,
    item_type: ItemType,
    rarity: Rarity,
    description: str = "",
    *,
    name: str | None = None,
    item_id: int = 1,
):
    return SimpleNamespace(
        id=item_id,
        name=name or source_id,
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


def test_bandage_recipe_requires_only_fabric() -> None:
    bandage = _item("bandage", "quick use", ItemType.GADGET, Rarity.COMMON, description="restores health")
    assert crafting_recipe_for_item(bandage) == [("fabric", 5)]


def test_craft_autocomplete_matches_shield_source_id_formats() -> None:
    shield = _item(
        "light_shield",
        "shield",
        ItemType.ARMOR,
        Rarity.UNCOMMON,
        name="Light Shield",
        item_id=42,
    )

    assert craft_autocomplete_matches(shield, "light_shield")
    assert craft_autocomplete_matches(shield, "light shield")
    assert craft_autocomplete_matches(shield, "42")


def test_craftables_from_inventory_filters_by_recipe() -> None:
    bandage = _item("bandage", "quick use", ItemType.GADGET, Rarity.COMMON, description="restores health", name="Bandage")
    herb = _item("herbal_bandage", "quick use", ItemType.GADGET, Rarity.UNCOMMON, description="restores health", name="Herbal Bandage", item_id=2)

    craftables = craftable_items_from_inventory([bandage, herb], {"fabric": 7, "bandage": 1, "antiseptic": 2, "chemicals": 2})

    assert bandage in craftables
    assert herb not in craftables
