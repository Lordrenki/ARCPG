from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib

from arkpg.game.constants import ZONE_CONFIG
from arkpg.game.items import filter_items_for_zone
from arkpg.game.loot import LootRoller


@dataclass
class DeploymentResolution:
    status: str
    credits: int
    xp: int
    loot: list[dict]
    durability_loss: int
    event: str


def make_seed(user_id: int, zone: str, started_at: datetime) -> str:
    raw = f"{user_id}:{zone}:{started_at.timestamp()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def deployment_end(zone: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    mins = ZONE_CONFIG[zone]["duration_min"]
    return now + timedelta(minutes=mins)


def resolve_deployment(seed: str, zone: str, level: int, extract_late: bool = False) -> DeploymentResolution:
    cfg = ZONE_CONFIG[zone]
    roller = LootRoller(seed)
    event = roller.roll_event()
    risk = cfg["risk"] + (0.05 if extract_late else 0.0)
    success_roll = roller.rng.random()

    if success_roll < risk * 0.55:
        return DeploymentResolution("failure", 0, int(20 * cfg["reward_mult"]), [], 20, event)

    partial = success_roll < risk
    loot_count = 1 if partial else roller.rng.randint(2, 4)
    zone_items = filter_items_for_zone(zone)
    loot = []
    for _ in range(loot_count):
        rarity = roller.roll_rarity(zone)
        matching = [item for item in zone_items if item.rarity == rarity]
        if not matching:
            matching = [item for item in zone_items if item.rarity in {"common", "uncommon", "rare", "epic", "legendary"}]
        picked = roller.rng.choice(matching)
        loot.append({"name": picked.name, "rarity": picked.rarity, "qty": 1})

    credits = int((75 + level * 8) * cfg["reward_mult"] * (0.65 if partial else 1.0))
    xp = int((95 + level * 12) * cfg["reward_mult"] * (0.75 if partial else 1.0))
    durability_loss = int(8 * cfg["reward_mult"] + (6 if partial else 0))
    return DeploymentResolution("partial" if partial else "success", credits, xp, loot, durability_loss, event)
