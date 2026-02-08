from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from arkpg.core.config import Settings
from arkpg.db.models import (
    AuditLog,
    Deployment,
    DeploymentStatus,
    Inventory,
    Item,
    ItemType,
    Rarity,
    Trade,
    TradeStatus,
    User,
)
from arkpg.game.deployments import deployment_end, make_seed, resolve_deployment
from arkpg.game.economy import compute_idle_rewards, level_from_xp


async def get_or_create_user(session: AsyncSession, discord_id: int) -> User:
    result = await session.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()
    if user:
        return user
    user = User(discord_id=discord_id)
    session.add(user)
    await session.flush()
    return user


async def claim_idle(session: AsyncSession, settings: Settings, discord_id: int) -> tuple[User, int, int, int]:
    user = await get_or_create_user(session, discord_id)
    now = datetime.now(timezone.utc)
    minutes, xp_gain, credits_gain = compute_idle_rewards(
        user.last_claim_at,
        now,
        settings.idle_xp_per_minute,
        settings.idle_credits_per_minute,
        settings.idle_claim_cap_hours,
    )
    user.last_claim_at = now
    user.xp += xp_gain
    user.credits += credits_gain
    user.level = level_from_xp(user.xp)
    if minutes < 1:
        session.add(AuditLog(event_type="suspicious_claim_frequency", payload={"discord_id": discord_id, "minutes": minutes}))
    await session.commit()
    return user, minutes, xp_gain, credits_gain


async def start_deployment(session: AsyncSession, discord_id: int, zone: str) -> Deployment:
    user = await get_or_create_user(session, discord_id)
    result = await session.execute(
        select(Deployment).where(and_(Deployment.user_id == user.id, Deployment.status.in_([DeploymentStatus.ACTIVE, DeploymentStatus.READY_TO_EXTRACT])))
    )
    active = result.scalar_one_or_none()
    if active:
        raise ValueError("You already have an active deployment.")

    now = datetime.now(timezone.utc)
    seed = make_seed(user.id, zone, now)
    dep = Deployment(user_id=user.id, zone=zone, started_at=now, ends_at=deployment_end(zone, now), seeded_rng=seed)
    session.add(dep)
    await session.commit()
    return dep


async def extract_deployment(session: AsyncSession, discord_id: int, auto: bool = False) -> dict:
    user = await get_or_create_user(session, discord_id)
    result = await session.execute(
        select(Deployment).where(and_(Deployment.user_id == user.id, Deployment.status.in_([DeploymentStatus.ACTIVE, DeploymentStatus.READY_TO_EXTRACT]))).order_by(Deployment.started_at.desc())
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise ValueError("No active deployment.")

    now = datetime.now(timezone.utc)
    if now < dep.ends_at:
        raise ValueError("Deployment is still running.")

    resolution = resolve_deployment(dep.seeded_rng, dep.zone, user.level, extract_late=auto)
    dep.status = DeploymentStatus.EXTRACTED if resolution.status != "failure" else DeploymentStatus.FAILED
    dep.carried_loot = {"outcome": resolution.status, "loot": resolution.loot, "event": resolution.event}

    user.xp += resolution.xp
    user.credits += resolution.credits
    user.level = level_from_xp(user.xp)
    stats = user.stats
    stats["raid_clears"] = int(stats.get("raid_clears", 0)) + (1 if resolution.status != "failure" else 0)
    stats["legendary_finds"] = int(stats.get("legendary_finds", 0)) + sum(1 for x in resolution.loot if x["rarity"] == "legendary")
    user.stats = stats

    for loot in resolution.loot:
        item_q = await session.execute(select(Item).where(Item.name == loot["name"]))
        item = item_q.scalar_one_or_none()
        if item is None:
            item = Item(name=loot["name"], type=ItemType.COMPONENT, rarity=Rarity(loot["rarity"]), base_value=50)
            session.add(item)
            await session.flush()
        inv_q = await session.execute(select(Inventory).where(and_(Inventory.user_id == user.id, Inventory.item_id == item.id, Inventory.weapon_level.is_(None))))
        inv = inv_q.scalar_one_or_none()
        if inv:
            inv.qty += loot["qty"]
        else:
            session.add(Inventory(user_id=user.id, item_id=item.id, qty=loot["qty"]))

    session.add(AuditLog(event_type="deployment_resolved", payload={"discord_id": discord_id, "deployment_id": dep.id, "resolution": resolution.__dict__}))
    await session.commit()
    return resolution.__dict__


async def atomic_trade_confirm(session: AsyncSession, trade_id: int) -> Trade:
    trade = await session.get(Trade, trade_id, with_for_update=True)
    if not trade or trade.status != TradeStatus.PENDING:
        raise ValueError("Trade unavailable")
    trade.status = TradeStatus.CONFIRMED
    await session.commit()
    return trade


def default_profile(discord_id: int) -> dict[str, str]:
    return {
        "callsign": f"Operator-{str(discord_id)[-4:]}",
        "title": "Rookie Scavenger",
        "bio": "No bio set yet.",
    }


def normalized_profile(user: User) -> dict[str, str]:
    profile_data = user.stats.get("profile", {}) if isinstance(user.stats, dict) else {}
    profile = default_profile(user.discord_id)
    profile["callsign"] = str(profile_data.get("callsign", profile["callsign"]))[:32]
    profile["title"] = str(profile_data.get("title", profile["title"]))[:60]
    profile["bio"] = str(profile_data.get("bio", profile["bio"]))[:220]
    return profile


async def update_user_profile(
    session: AsyncSession,
    discord_id: int,
    callsign: str | None = None,
    title: str | None = None,
    bio: str | None = None,
) -> tuple[User, dict[str, str]]:
    user = await get_or_create_user(session, discord_id)
    profile = normalized_profile(user)

    if callsign is not None:
        profile["callsign"] = callsign.strip()[:32] or profile["callsign"]
    if title is not None:
        profile["title"] = title.strip()[:60] or profile["title"]
    if bio is not None:
        profile["bio"] = bio.strip()[:220] or profile["bio"]

    stats = user.stats
    stats["profile"] = profile
    user.stats = stats
    await session.commit()
    return user, profile
