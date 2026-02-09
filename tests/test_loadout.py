from types import SimpleNamespace

from arkpg.db.models import ItemType, Rarity
from arkpg.game.loadout import (
    HEALING_ITEM_FLAT,
    SHIELD_DAMAGE_REDUCTION,
    as_item_payload,
    healing_amount,
    is_gadget,
    is_healing,
    is_shield,
    is_weapon,
    shield_reduction,
)


def _item(*, source_id: str, source_type: str, item_type: ItemType, rarity: Rarity = Rarity.COMMON, description: str = "utility item"):
    return SimpleNamespace(
        id=1,
        name="Test",
        type=item_type,
        rarity=rarity,
        base_value=100,
        metadata_json={"source_id": source_id, "source_type": source_type, "description": description},
    )


def test_type_detection_helpers() -> None:
    weapon = _item(source_id="anvil", source_type="hand cannon", item_type=ItemType.WEAPON)
    gadget = _item(source_id="grenade", source_type="quick use", item_type=ItemType.GADGET)
    heal = _item(source_id="vita_shot", source_type="quick use", item_type=ItemType.GADGET, description="restores health")
    shield = _item(source_id="heavy_shield", source_type="shield", item_type=ItemType.ARMOR)

    assert is_weapon(weapon)
    assert is_gadget(gadget)
    assert is_healing(heal)
    assert is_shield(shield)


def test_payload_healing_and_shield_values() -> None:
    heal = _item(source_id="vita_shot", source_type="quick use", item_type=ItemType.GADGET, description="restores health")
    shield = _item(source_id="medium_shield", source_type="shield", item_type=ItemType.ARMOR)

    heal_payload = as_item_payload(heal)
    shield_payload = as_item_payload(shield)

    assert healing_amount(heal_payload) == HEALING_ITEM_FLAT["vita_shot"]
    assert shield_reduction(shield_payload) == SHIELD_DAMAGE_REDUCTION["medium_shield"]
