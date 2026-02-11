from __future__ import annotations

from arkpg.db.models import Item
from arkpg.game.loadout import is_gadget, is_healing, is_shield, is_weapon

RARITY_TIER = {"common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}


def is_craftable_item(item: Item) -> bool:
    return is_weapon(item) or is_gadget(item) or is_healing(item) or is_shield(item)


def crafting_recipe_for_item(item: Item) -> list[tuple[str, int]]:
    rarity = item.rarity.value
    tier = RARITY_TIER.get(rarity, 1)
    source_id = str((item.metadata_json or {}).get("source_id") or "").strip().lower()

    if source_id == "bandage":
        return [("fabric", 5)]

    if is_healing(item):
        return [
            ("bandage", 1 + tier),
            ("antiseptic", tier),
            ("chemicals", 1 + tier),
            ("fabric", 1 + tier),
        ]

    if is_shield(item):
        # Keep medium/heavy shield crafting accessible but expensive.
        recipe = [
            ("metal_parts", 2 + tier),
            ("wires", 2 + tier),
            ("battery", 1 + tier),
            ("electrical_components", 1 + tier),
        ]
        if source_id == "heavy_shield":
            recipe.append(("arc_alloy", 1 + max(0, tier - 3)))
        return recipe

    if is_weapon(item):
        recipe = [
            ("light_gun_parts", 2 + tier),
            ("metal_parts", 1 + tier),
            ("wires", max(1, tier - 1)),
        ]
        if tier >= 3:
            recipe.append(("electrical_components", tier - 1))
        if tier >= 4:
            recipe.append(("arc_alloy", 1))
        if tier >= 5:
            recipe.append(("advanced_mechanical_components", 1))
        return recipe

    # gadget / throwable
    recipe = [
        ("chemicals", 1 + tier),
        ("duct_tape", 1 + tier),
        ("battery", max(1, tier - 1)),
    ]
    if tier >= 3:
        recipe.append(("explosive_compound", tier - 1))
    if tier >= 4:
        recipe.append(("arc_circuitry", 1))
    return recipe
