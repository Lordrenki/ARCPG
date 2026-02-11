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
    gadget_utility_from_payload,
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


def test_gadget_utility_uses_description_and_type() -> None:
    grenade = {"source_id": "frag_grenade", "source_type": "quick use", "rarity": "rare", "value": 5000, "description": "An explosive grenade."}
    zipline = {"source_id": "zipline", "source_type": "deployable", "rarity": "rare", "value": 1000, "description": "Mobility deployable."}

    assert gadget_utility_from_payload(grenade) > gadget_utility_from_payload(zipline)


def test_as_item_payload_contains_description() -> None:
    item = _item(source_id="wolfpack", source_type="quick use", item_type=ItemType.GADGET, description="homing explosive")
    payload = as_item_payload(item)
    assert payload["description"] == "homing explosive"


def test_special_weapon_type_is_supported() -> None:
    equalizer = _item(source_id="equalizer", source_type="special", item_type=ItemType.COMPONENT)
    assert is_weapon(equalizer)
