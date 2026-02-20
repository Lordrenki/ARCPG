from arkpg.game.items import filter_items_for_zone, infer_rarity, load_items


def test_load_items_from_repo_db() -> None:
    items = load_items()
    assert len(items) > 50
    assert any(i.name == "Blue Light Stick" for i in items)


def test_infer_rarity_fallback_from_value() -> None:
    assert infer_rarity(None, 300) == "common"
    assert infer_rarity(None, 2000) == "uncommon"
    assert infer_rarity(None, 5000) == "rare"
    assert infer_rarity(None, 12000) == "epic"
    assert infer_rarity(None, 20000) == "legendary"


def test_filter_items_for_zone_prefers_zone_tags() -> None:
    arc_items = filter_items_for_zone("ARC Site")
    assert arc_items
    assert any("arc" in item.found_in for item in arc_items)


def test_load_items_includes_shield_tiers() -> None:
    items = load_items()
    source_ids = {item.id for item in items}

    assert "light_shield" in source_ids
    assert "medium_shield" in source_ids
    assert "heavy_shield" in source_ids
