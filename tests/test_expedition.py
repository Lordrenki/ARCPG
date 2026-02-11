from types import SimpleNamespace

import pytest

from arkpg.db.models import ItemType, Rarity
from arkpg.game.progression import ExpeditionService


@pytest.mark.parametrize("item_type", [ItemType.COMPONENT, ItemType.RECYCLABLE])
def test_expedition_donation_allows_material_items(item_type: ItemType) -> None:
    item = SimpleNamespace(type=item_type)
    assert ExpeditionService._is_allowed_donation_item(item)


@pytest.mark.parametrize("item_type", [ItemType.WEAPON, ItemType.ARMOR, ItemType.GADGET, ItemType.BLUEPRINT])
def test_expedition_donation_rejects_non_material_items(item_type: ItemType) -> None:
    item = SimpleNamespace(type=item_type)
    assert not ExpeditionService._is_allowed_donation_item(item)


def test_expedition_item_donation_score_is_scaled_down() -> None:
    common = SimpleNamespace(base_value=1000, rarity=Rarity.COMMON)
    rare = SimpleNamespace(base_value=1000, rarity=Rarity.RARE)

    common_score = ExpeditionService._item_donation_score(common, 2)
    rare_score = ExpeditionService._item_donation_score(rare, 2)

    assert common_score == 100
    assert rare_score == 170
    assert rare_score > common_score


def test_expedition_item_donation_score_has_minimum_floor() -> None:
    low_value = SimpleNamespace(base_value=5, rarity=Rarity.COMMON)
    assert ExpeditionService._item_donation_score(low_value, 3) == 30
