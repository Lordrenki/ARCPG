from arkpg.game.deployments import resolve_deployment


def test_deployment_resolution_shape() -> None:
    res = resolve_deployment("seed-1", "Residential", level=5)
    assert res.status in {"success", "partial", "failure"}
    assert isinstance(res.loot, list)
