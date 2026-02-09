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
from arkpg.game.crafting import crafting_recipe_for_item, is_craftable_item
from arkpg.game.economy import compute_idle_rewards, level_from_xp, scale_stats_with_level
from arkpg.game.profile_backgrounds import DEFAULT_BACKGROUND_ID, normalize_collected_background_ids
from arkpg.game.loadout import as_item_payload, healing_amount, item_power_from_payload, shield_reduction
from arkpg.game.progression import EventBus


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def get_or_create_user(session: AsyncSession, discord_id: int) -> User:
    result = await session.execute(select(User).where(User.discord_id == discord_id))
    user = result.scalar_one_or_none()
    if user:
        stats = scale_stats_with_level(dict(user.stats or {}), user.level)
        user.stats = stats
        return user
    user = User(discord_id=discord_id, progression_json={})
    session.add(user)
    await session.flush()
    user.stats = scale_stats_with_level(dict(user.stats or {}), user.level)
    return user




async def ensure_starter_kit(session: AsyncSession, user: User) -> None:
    starter_ids = ("kettle", "light_shield", "bandage")
    rows = (await session.execute(select(Item).where(Item.metadata_json["source_id"].as_string().in_(starter_ids)))).scalars().all()
    if len(rows) < len(starter_ids):
        fallback = (await session.execute(select(Item).where(Item.name.in_(["Kettle I", "Light Shield", "Bandage"])))).scalars().all()
        by_name = {i.name: i for i in fallback}
        for name in ("Kettle I", "Light Shield", "Bandage"):
            if name in by_name and by_name[name] not in rows:
                rows.append(by_name[name])

    items_by_sid = {str((it.metadata_json or {}).get("source_id") or "").lower(): it for it in rows}
    for item in rows:
        sid = str((item.metadata_json or {}).get("source_id") or "").lower()
        if sid not in items_by_sid:
            items_by_sid[sid] = item

    for item in [items_by_sid.get("kettle"), items_by_sid.get("light_shield"), items_by_sid.get("bandage")]:
        if item is None:
            continue
        inv = (await session.execute(select(Inventory).where(and_(Inventory.user_id == user.id, Inventory.item_id == item.id, Inventory.weapon_level.is_(None))))).scalar_one_or_none()
        if inv is None:
            session.add(Inventory(user_id=user.id, item_id=item.id, qty=1))

    loadout = get_user_loadout(user)
    kettle = items_by_sid.get("kettle")
    shield = items_by_sid.get("light_shield")
    bandage = items_by_sid.get("bandage")
    loadout["weapons"] = [as_item_payload(kettle)] if kettle else []
    loadout["gadget"] = None
    loadout["healing"] = as_item_payload(bandage) if bandage else None
    loadout["shield"] = as_item_payload(shield) if shield else None
    set_user_loadout(user, loadout)

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
    user.stats = scale_stats_with_level(dict(user.stats or {}), user.level)
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
    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    stats.setdefault("max_health", 100)
    stats.setdefault("health", stats.get("max_health", 100))
    stats.setdefault("loadout", _default_loadout())
    user.stats = stats

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
    if now < as_utc(dep.ends_at):
        raise ValueError("Deployment is still running.")

    loadout_power = compute_loadout_power(user)
    resolution = resolve_deployment(dep.seeded_rng, dep.zone, user.level, extract_late=auto, loadout_power=loadout_power["total_power"])
    dep.status = DeploymentStatus.EXTRACTED if resolution.status != "failure" else DeploymentStatus.FAILED
    dep.carried_loot = {"outcome": resolution.status, "loot": resolution.loot, "event": resolution.event}

    user.xp += resolution.xp
    user.credits += resolution.credits
    user.level = level_from_xp(user.xp)
    user.stats = scale_stats_with_level(dict(user.stats or {}), user.level)
    stats = user.stats
    stats["raid_clears"] = int(stats.get("raid_clears", 0)) + (1 if resolution.status != "failure" else 0)
    stats["legendary_finds"] = int(stats.get("legendary_finds", 0)) + sum(1 for x in resolution.loot if x["rarity"] == "legendary")
    user.stats = stats
    survivability = _apply_deployment_survivability(user, resolution.damage_taken, loadout_power)

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

    session.add(AuditLog(event_type="deployment_resolved", payload={"discord_id": discord_id, "deployment_id": dep.id, "resolution": resolution.__dict__, "survivability": survivability}))
    await EventBus.emit(session, user, "EXTRACT_SUCCESS" if resolution.status != "failure" else "RAID_COMPLETED", {"counter_updates": {"raid_clears": 1 if resolution.status != "failure" else 0, "legendary_finds": sum(1 for x in resolution.loot if x["rarity"] == "legendary"), "extract_streak": 1 if resolution.status != "failure" else -int((user.progression_json or {}).get("extract_streak",0))}})
    await session.commit()
    payload = resolution.__dict__
    payload["survivability"] = survivability
    payload["loadout_power"] = round(loadout_power["total_power"], 2)
    return payload


async def atomic_trade_confirm(session: AsyncSession, trade_id: int) -> Trade:
    trade = await session.get(Trade, trade_id, with_for_update=True)
    if not trade or trade.status != TradeStatus.PENDING:
        raise ValueError("Trade unavailable")
    src = await session.get(User, trade.from_user, with_for_update=True)
    dst = await session.get(User, trade.to_user, with_for_update=True)
    if not src or not dst:
        raise ValueError("Trade users unavailable")

    offered_credits = int((trade.offered or {}).get("credits", 0))
    requested_credits = int((trade.requested or {}).get("credits", 0))

    if src.credits < offered_credits:
        raise ValueError("Offerer does not have enough credits.")
    if dst.credits < requested_credits:
        raise ValueError("Target does not have enough credits.")

    src.credits -= offered_credits
    dst.credits += offered_credits
    dst.credits -= requested_credits
    src.credits += requested_credits

    async def transfer_item(from_user_id: int, to_user_id: int, payload: dict, label: str) -> None:
        item_id = payload.get("item_id")
        qty = int(payload.get("item_qty", 0) or 0)
        if not item_id or qty <= 0:
            return

        inv_q = await session.execute(
            select(Inventory).where(
                and_(Inventory.user_id == from_user_id, Inventory.item_id == int(item_id), Inventory.weapon_level.is_(None))
            )
        )
        source_inv = inv_q.scalar_one_or_none()
        if source_inv is None or source_inv.qty < qty:
            raise ValueError(f"{label} does not have enough of item {item_id}.")

        source_inv.qty -= qty
        if source_inv.qty <= 0:
            await session.delete(source_inv)

        dst_q = await session.execute(
            select(Inventory).where(
                and_(Inventory.user_id == to_user_id, Inventory.item_id == int(item_id), Inventory.weapon_level.is_(None))
            )
        )
        dst_inv = dst_q.scalar_one_or_none()
        if dst_inv:
            dst_inv.qty += qty
        else:
            session.add(Inventory(user_id=to_user_id, item_id=int(item_id), qty=qty))

    await transfer_item(src.id, dst.id, trade.offered or {}, "Offerer")
    await transfer_item(dst.id, src.id, trade.requested or {}, "Target")

    trade.status = TradeStatus.CONFIRMED
    await session.commit()
    return trade


def _default_loadout() -> dict:
    return {"weapons": [], "gadget": None, "healing": None, "shield": None}


def get_user_loadout(user: User) -> dict:
    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    loadout = dict(stats.get("loadout") or {})
    loadout.setdefault("weapons", [])
    loadout.setdefault("gadget", None)
    loadout.setdefault("healing", None)
    loadout.setdefault("shield", None)
    return loadout


def set_user_loadout(user: User, loadout: dict) -> None:
    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    stats["loadout"] = loadout
    user.stats = stats


def compute_loadout_power(user: User) -> dict:
    loadout = get_user_loadout(user)
    stats = user.stats if isinstance(user.stats, dict) else {}
    weapon_power = sum(item_power_from_payload(w, stats) for w in (loadout.get("weapons") or []))
    gadget_power = item_power_from_payload(loadout["gadget"], stats) * 0.45 if loadout.get("gadget") else 0.0
    return {
        "weapon_power": weapon_power,
        "gadget_power": gadget_power,
        "total_power": weapon_power + gadget_power,
        "shield_reduction": shield_reduction(loadout.get("shield")),
        "healing_amount": healing_amount(loadout.get("healing")),
    }


def _apply_deployment_survivability(user: User, event_damage: int, payload: dict) -> dict:
    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    max_health = int(stats.get("max_health", 100) or 100)
    current = int(stats.get("health", max_health) or max_health)
    reduction = float(payload.get("shield_reduction", 0.0) or 0.0)
    mitigated = max(0, int(round(event_damage * (1.0 - reduction))))
    post = current - mitigated
    healing_used = False
    if post <= 0 and payload.get("healing_amount", 0) > 0:
        healing_used = True
        post = max(1, int(payload["healing_amount"]))
        loadout = get_user_loadout(user)
        loadout["healing"] = None
        set_user_loadout(user, loadout)
    stats["max_health"] = max_health
    stats["health"] = max(1, min(max_health, post))
    user.stats = stats
    return {"incoming_damage": event_damage, "effective_damage": mitigated, "healing_used": healing_used, "health_after": stats["health"]}



async def get_user_inventory_items(session: AsyncSession, user: User) -> list[tuple[Inventory, Item]]:
    return (await session.execute(select(Inventory, Item).join(Item, Inventory.item_id == Item.id).where(Inventory.user_id == user.id))).all()


async def craft_item(session: AsyncSession, discord_id: int, item_id: int, qty: int = 1) -> dict:
    if qty <= 0:
        raise ValueError("Craft quantity must be positive.")

    user = await get_or_create_user(session, discord_id)
    item = await session.get(Item, item_id)
    if item is None:
        raise ValueError("Item not found.")
    if not is_craftable_item(item):
        raise ValueError("This item cannot be crafted.")

    recipe = crafting_recipe_for_item(item)
    crafted_source_id = str((item.metadata_json or {}).get("source_id") or "").strip().lower()
    if not crafted_source_id:
        raise ValueError("Crafting is blocked because this item has no source id metadata.")

    required_blueprint_source_id = f"{crafted_source_id}_blueprint"
    blueprint_item = (
        await session.execute(
            select(Item).where(
                and_(
                    Item.type == ItemType.BLUEPRINT,
                    Item.metadata_json["source_id"].as_string() == required_blueprint_source_id,
                )
            )
        )
    ).scalar_one_or_none()
    if blueprint_item is None:
        raise ValueError(f"Crafting is blocked: missing blueprint item '{required_blueprint_source_id}'.")

    owned_blueprint = (
        await session.execute(
            select(Inventory).where(
                and_(Inventory.user_id == user.id, Inventory.item_id == blueprint_item.id, Inventory.weapon_level.is_(None), Inventory.qty > 0)
            )
        )
    ).scalar_one_or_none()
    if owned_blueprint is None:
        raise ValueError(f"You need to own **{blueprint_item.name}** before crafting this item.")

    source_items = (await session.execute(select(Item))).scalars().all()
    source_map = {str((x.metadata_json or {}).get("source_id") or "").lower(): x for x in source_items}

    required: list[tuple[Item, int]] = []
    for source_id, amount in recipe:
        material = source_map.get(source_id)
        if material is None:
            raise ValueError(f"Crafting material '{source_id}' is not available.")
        required.append((material, amount * qty))

    for material, required_qty in required:
        inv = (
            await session.execute(
                select(Inventory).where(and_(Inventory.user_id == user.id, Inventory.item_id == material.id, Inventory.weapon_level.is_(None)))
            )
        ).scalar_one_or_none()
        available = inv.qty if inv else 0
        if available < required_qty:
            raise ValueError(f"Missing materials: {material.name} x{required_qty} (have {available}).")

    for material, required_qty in required:
        inv = (
            await session.execute(
                select(Inventory).where(and_(Inventory.user_id == user.id, Inventory.item_id == material.id, Inventory.weapon_level.is_(None)))
            )
        ).scalar_one()
        inv.qty -= required_qty
        if inv.qty <= 0:
            await session.delete(inv)

    crafted_stack = (
        await session.execute(select(Inventory).where(and_(Inventory.user_id == user.id, Inventory.item_id == item.id, Inventory.weapon_level.is_(None))))
    ).scalar_one_or_none()
    if crafted_stack:
        crafted_stack.qty += qty
    else:
        session.add(Inventory(user_id=user.id, item_id=item.id, qty=qty))

    await session.commit()
    return {
        "item": item,
        "qty": qty,
        "materials": [{"name": material.name, "qty": needed} for material, needed in required],
    }


async def equip_loadout_item(session: AsyncSession, discord_id: int, item_id: int, slot: str, weapon_index: int | None = None) -> tuple[User, dict]:
    user = await get_or_create_user(session, discord_id)
    inv_item = (await session.execute(select(Inventory, Item).join(Item, Inventory.item_id == Item.id).where(and_(Inventory.user_id == user.id, Inventory.item_id == item_id)))).first()
    if inv_item is None:
        raise ValueError("Item not found in your inventory.")
    _inv, item = inv_item

    from arkpg.game.loadout import is_gadget, is_healing, is_shield, is_weapon

    loadout = get_user_loadout(user)
    payload = as_item_payload(item)

    if slot == "weapon":
        if not is_weapon(item):
            raise ValueError("That item is not a weapon.")
        weapons = list(loadout.get("weapons") or [])
        if weapon_index is None:
            weapon_index = 1 if len(weapons) < 1 else 2
        if weapon_index not in (1, 2):
            raise ValueError("Weapon slot must be 1 or 2.")
        while len(weapons) < 2:
            weapons.append(None)
        weapons[weapon_index - 1] = payload
        loadout["weapons"] = weapons
    elif slot == "gadget":
        if not is_gadget(item):
            raise ValueError("That item is not a gadget/throwable.")
        loadout["gadget"] = payload
    elif slot == "healing":
        if not is_healing(item):
            raise ValueError("That item is not a healing item.")
        loadout["healing"] = payload
    elif slot == "shield":
        if not is_shield(item):
            raise ValueError("That item is not a shield.")
        loadout["shield"] = payload
    else:
        raise ValueError("Unknown slot.")

    set_user_loadout(user, loadout)
    await session.commit()
    return user, loadout


async def get_equipped_loadout(session: AsyncSession, discord_id: int) -> tuple[User, dict]:
    user = await get_or_create_user(session, discord_id)
    return user, get_user_loadout(user)



def default_profile(discord_id: int) -> dict[str, str | list[str]]:
    return {
        "callsign": f"Raider-{str(discord_id)[-4:]}",
        "bio": "No bio set yet.",
        "background_id": DEFAULT_BACKGROUND_ID,
        "collected_background_ids": [DEFAULT_BACKGROUND_ID],
    }


def normalized_profile(user: User) -> dict[str, str | list[str]]:
    profile_data = user.stats.get("profile", {}) if isinstance(user.stats, dict) else {}
    profile = default_profile(user.discord_id)
    profile["callsign"] = str(profile_data.get("callsign", profile["callsign"]))[:32]
    profile["bio"] = str(profile_data.get("bio", profile["bio"]))[:220]
    collected = normalize_collected_background_ids(profile_data.get("collected_background_ids"))
    active_background = str(profile_data.get("background_id", DEFAULT_BACKGROUND_ID))
    if active_background not in collected:
        active_background = DEFAULT_BACKGROUND_ID
    profile["collected_background_ids"] = collected
    profile["background_id"] = active_background
    return profile


async def update_user_profile(
    session: AsyncSession,
    discord_id: int,
    callsign: str | None = None,
    bio: str | None = None,
    background_id: str | None = None,
) -> tuple[User, dict[str, str | list[str]]]:
    user = await get_or_create_user(session, discord_id)
    profile = normalized_profile(user)

    if callsign is not None:
        profile["callsign"] = callsign.strip()[:32] or profile["callsign"]
    if bio is not None:
        profile["bio"] = bio.strip()[:220] or profile["bio"]
    if background_id is not None:
        collected = set(profile["collected_background_ids"] if isinstance(profile.get("collected_background_ids"), list) else [])
        if background_id not in collected:
            raise ValueError("You have not collected that background yet.")
        profile["background_id"] = background_id

    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    stats["profile"] = profile
    user.stats = stats
    await session.commit()
    return user, profile


async def collect_profile_background(session: AsyncSession, discord_id: int, background_id: str) -> tuple[User, dict[str, str | list[str]]]:
    user = await get_or_create_user(session, discord_id)
    profile = normalized_profile(user)
    collected = set(profile["collected_background_ids"] if isinstance(profile.get("collected_background_ids"), list) else [])
    collected.add(background_id)
    profile["collected_background_ids"] = normalize_collected_background_ids(sorted(collected))

    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    stats["profile"] = profile
    user.stats = stats
    await session.commit()
    return user, profile


async def ensure_default_profile_backgrounds(session: AsyncSession, user: User) -> dict[str, str | list[str]]:
    profile = normalized_profile(user)
    stats = dict(user.stats) if isinstance(user.stats, dict) else {}
    stats["profile"] = profile
    user.stats = stats
    await session.commit()
    return profile
