from types import SimpleNamespace

from arkpg.game.service import _apply_deployment_survivability


def test_survivability_allows_zero_hp_when_lethal_without_heal() -> None:
    user = SimpleNamespace(stats={"health": 8, "max_health": 100, "loadout": {"weapons": [], "gadget": None, "healing": None, "shield": None}})
    outcome = _apply_deployment_survivability(user, event_damage=12, payload={"shield_reduction": 0.0, "healing_amount": 0})
    assert outcome["health_after"] == 0
    assert user.stats["health"] == 0


def test_survivability_consumes_heal_and_restores_positive_hp() -> None:
    user = SimpleNamespace(stats={"health": 5, "max_health": 100, "loadout": {"weapons": [], "gadget": None, "healing": {"name": "Bandage"}, "shield": None}})
    outcome = _apply_deployment_survivability(user, event_damage=20, payload={"shield_reduction": 0.0, "healing_amount": 22})
    assert outcome["healing_used"] is True
    assert outcome["health_after"] == 22
    assert user.stats["loadout"]["healing"] is None
