from datetime import datetime, timezone

from arkpg.game.deployments import resolve_deployment
from arkpg.game.service import as_utc


def test_deployment_resolution_shape() -> None:
    res = resolve_deployment("seed-1", "Residential", level=5)
    assert res.status in {"success", "partial", "failure"}
    assert isinstance(res.loot, list)


def test_as_utc_normalizes_naive_datetime() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    normalized = as_utc(naive)
    assert normalized.tzinfo == timezone.utc


def test_deployment_uses_catalog_items() -> None:
    res = resolve_deployment("seed-catalog", "Industrial", level=5)
    if res.loot:
        assert all(not item["name"].endswith("Salvage") for item in res.loot)
