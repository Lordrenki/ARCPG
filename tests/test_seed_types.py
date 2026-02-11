from arkpg.db.models import ItemType
from arkpg.game.progression import SeederService


def test_weapon_type_normalization_uses_current_weapon_catalog() -> None:
    assert SeederService._normalize_type("special") == ItemType.WEAPON
    assert SeederService._normalize_type("battle rifle") == ItemType.WEAPON
    assert SeederService._normalize_type("melee") == ItemType.COMPONENT
