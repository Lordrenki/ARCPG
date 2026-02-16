import asyncio

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from arkpg.db.base import Base
from arkpg.db.models import Inventory, Item, ItemType, Rarity, User
from arkpg.game.progression import ActivityService


async def _run_salvage_conversion_test() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = User(discord_id=1234, credits=0, xp=0, level=1, progression_json={}, stats={})
        advanced = Item(
            name="Advanced Electrical Components",
            type=ItemType.COMPONENT,
            rarity=Rarity.RARE,
            base_value=300,
            metadata_json={"source_id": "advanced_electrical_components", "source_type": "topside material"},
        )
        normal = Item(
            name="Electrical Components",
            type=ItemType.COMPONENT,
            rarity=Rarity.UNCOMMON,
            base_value=120,
            metadata_json={"source_id": "electrical_components", "source_type": "topside material"},
        )
        session.add_all([user, advanced, normal])
        await session.flush()
        session.add(Inventory(user_id=user.id, item_id=advanced.id, qty=1))
        await session.commit()

        service = ActivityService(session)

        async def _fixed_seed(_: int, __: str) -> str:
            return "fixed"

        service._seed = _fixed_seed  # type: ignore[method-assign]

        result = await service.salvage(user, source_id="advanced_electrical_components")
        await session.commit()

        assert (normal.id, 1) in result.items
        assert "Recovered materials:" in result.message
        assert "Electrical Components x1" in result.message

        user_inventory = (await session.execute(select(Inventory).where(Inventory.user_id == user.id))).scalars().all()
        by_item = {row.item_id: row.qty for row in user_inventory}
        assert advanced.id not in by_item
        assert by_item.get(normal.id) == 1

    await engine.dispose()


async def _run_scavenge_guarantees_fabric_test() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = User(discord_id=9876, credits=0, xp=0, level=1, progression_json={}, stats={})
        fabric = Item(
            name="Fabric",
            type=ItemType.COMPONENT,
            rarity=Rarity.COMMON,
            base_value=20,
            metadata_json={"source_id": "fabric", "source_type": "topside material"},
        )
        chemicals = Item(
            name="Chemicals",
            type=ItemType.COMPONENT,
            rarity=Rarity.COMMON,
            base_value=25,
            metadata_json={"source_id": "chemicals", "source_type": "topside material"},
        )
        session.add_all([user, fabric, chemicals])
        await session.commit()

        service = ActivityService(session)

        async def _fixed_seed(_: int, __: str) -> str:
            return "fixed-scavenge-seed"

        service._seed = _fixed_seed  # type: ignore[method-assign]

        result = await service.scavenge(user)
        await session.commit()

        fabric_rewards = [qty for item_id, qty in result.items if item_id == fabric.id]
        non_fabric_rewards = [qty for item_id, qty in result.items if item_id != fabric.id]

        assert fabric_rewards
        assert 1 <= fabric_rewards[0] <= 5
        assert non_fabric_rewards

        user_inventory = (await session.execute(select(Inventory).where(Inventory.user_id == user.id))).scalars().all()
        by_item = {row.item_id: row.qty for row in user_inventory}
        assert fabric.id in by_item
        assert by_item[fabric.id] >= fabric_rewards[0]

    await engine.dispose()


def test_salvage_advanced_electrical_components_grants_normal_components() -> None:
    assert sqlalchemy is not None
    asyncio.run(_run_salvage_conversion_test())


def test_scavenge_always_rewards_fabric_plus_other_item() -> None:
    assert sqlalchemy is not None
    asyncio.run(_run_scavenge_guarantees_fabric_test())
