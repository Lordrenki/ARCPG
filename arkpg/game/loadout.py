from __future__ import annotations

from arkpg.db.models import Item, ItemType

WEAPON_TYPES = {
    "rifle", "burst rifle", "smg", "shotgun", "sniper", "lmg", "pistol", "hand cannon", "bow",
    "weapon", "melee", "launcher", "arc weapon", "assault rifle", "battle rifle", "sniper rifle", "special",
}

HEALING_ITEM_FLAT = {
    "adrenaline_shot": 22,
    "vita_shot": 55,
    "vita_spray": 70,
}

SHIELD_DAMAGE_REDUCTION = {
    "light_shield": 0.30,
    "medium_shield": 0.50,
    "heavy_shield": 0.70,
}

RARITY_SCORE = {"common": 1.0, "uncommon": 1.15, "rare": 1.35, "epic": 1.6, "legendary": 2.0}


def source_type(item: Item) -> str:
    return str((item.metadata_json or {}).get("source_type") or item.type.value).lower().strip()


def source_id(item: Item) -> str:
    return str((item.metadata_json or {}).get("source_id") or "").strip().lower()


def item_description(item: Item) -> str:
    return str((item.metadata_json or {}).get("description") or "").lower()


def is_weapon(item: Item) -> bool:
    return item.type == ItemType.WEAPON or source_type(item) in WEAPON_TYPES


def is_shield(item: Item) -> bool:
    sid = source_id(item)
    return sid in SHIELD_DAMAGE_REDUCTION or source_type(item) == "shield"


def is_healing(item: Item) -> bool:
    sid = source_id(item)
    if sid in HEALING_ITEM_FLAT:
        return True
    desc = item_description(item)
    return "health" in desc and "restore" in desc


def is_gadget(item: Item) -> bool:
    return item.type == ItemType.GADGET and not is_healing(item)


def healing_amount(item_payload: dict | None) -> int:
    if not item_payload:
        return 0
    sid = str(item_payload.get("source_id") or "").lower()
    if sid in HEALING_ITEM_FLAT:
        return HEALING_ITEM_FLAT[sid]
    return 35


def shield_reduction(item_payload: dict | None) -> float:
    if not item_payload:
        return 0.0
    sid = str(item_payload.get("source_id") or "").lower()
    return SHIELD_DAMAGE_REDUCTION.get(sid, 0.0)




def gadget_utility_from_payload(item_payload: dict | None) -> int:
    if not item_payload:
        return 0
    rarity = str(item_payload.get("rarity") or "common").lower()
    rarity_mult = RARITY_SCORE.get(rarity, 1.0)
    value = int(item_payload.get("value", 0) or 0)
    base = max(4, int(value / 450) + 4)

    source_type_value = str(item_payload.get("source_type") or "").lower()
    desc = str(item_payload.get("description") or "").lower()
    sid = str(item_payload.get("source_id") or "").lower()

    bonus = 0
    if "grenade" in sid or "grenade" in desc or "explosive" in desc:
        bonus += 5
    if "mine" in sid or "trap" in desc:
        bonus += 4
    if "decoy" in sid or "decoy" in desc:
        bonus += 3
    if "smoke" in sid or "smoke" in desc:
        bonus += 3
    if "flash" in sid or "stun" in desc or "blind" in desc:
        bonus += 3
    if "shield" in desc or source_type_value == "deployable":
        bonus += 2
    if "zipline" in sid or "mobility" in desc:
        bonus += 2
    if "homing" in desc or "arc" in desc:
        bonus += 2

    return max(5, int(round((base + bonus) * rarity_mult)))


def item_power_from_payload(item_payload: dict, player_stats: dict) -> float:
    rarity = str(item_payload.get("rarity") or "common").lower()
    rarity_mult = RARITY_SCORE.get(rarity, 1.0)
    value = int(item_payload.get("value", 0) or 0)
    combat = int(player_stats.get("combat", 10) or 10)
    tech = int(player_stats.get("tech", 10) or 10)
    luck = int(player_stats.get("luck", 10) or 10)
    return (combat * 1.7 + tech * 0.8 + luck * 0.45 + value / 220) * rarity_mult


def as_item_payload(item: Item) -> dict:
    metadata = item.metadata_json or {}
    return {
        "item_id": item.id,
        "name": item.name,
        "rarity": item.rarity.value,
        "value": item.base_value,
        "source_id": metadata.get("source_id"),
        "source_type": metadata.get("source_type") or item.type.value,
        "description": metadata.get("description") or "",
    }
