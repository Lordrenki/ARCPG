from datetime import datetime, timezone

from arkpg.game.deployments import resolve_deployment
from arkpg.game.service import as_utc


def test_deployment_resolution_shape() -> None:
    res = resolve_deployment("seed-1", "Residential", level=5)
    assert res.status in {"success", "partial", "failure"}
    assert isinstance(res.loot, list)
    assert isinstance(res.damage_taken, int)


def test_as_utc_normalizes_naive_datetime() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    normalized = as_utc(naive)
    assert normalized.tzinfo == timezone.utc


def test_deployment_uses_catalog_items() -> None:
    res = resolve_deployment("seed-catalog", "Industrial", level=5)
    if res.loot:
        assert all(not item["name"].endswith("Salvage") for item in res.loot)


def test_deployment_loadout_power_reduces_risk() -> None:
    weak = resolve_deployment("seed-power", "ARC Site", level=5, loadout_power=0)
    strong = resolve_deployment("seed-power", "ARC Site", level=5, loadout_power=400)
    # deterministic seed should trend equal-or-better with stronger power in our risk model
    ordering = {"failure": 0, "partial": 1, "success": 2}
    assert ordering[strong.status] >= ordering[weak.status]


def test_deployment_loot_can_favor_fabric() -> None:
    had_fabric = any(
        any(item["name"] == "Fabric" for item in resolve_deployment(f"fabric-seed-{idx}", "Industrial", level=5).loot)
        for idx in range(30)
    )
    assert had_fabric
