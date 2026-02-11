from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


RARITY_ORDER = ("common", "uncommon", "rare", "epic", "legendary")


@dataclass(frozen=True)
class GameItem:
    id: str
    name: str
    rarity: str
    type: str
    value: int
    found_in: tuple[str, ...]
    description: str
    icon: str | None


def _repo_items_path() -> Path:
    return Path(__file__).resolve().parents[1] / "db" / "items.json"


def _repo_item_source_paths() -> tuple[Path, ...]:
    db_root = Path(__file__).resolve().parents[1] / "db"
    return (
        db_root / "gadgets_quick_use_only.json",
        db_root / "healing_items.json",
        db_root / "weapons.json",
        db_root / "crafting_materials.json",
    )


def _external_items_path() -> Path:
    return Path("/mnt/data/items.json")


def infer_rarity(raw_rarity: str | None, value: int) -> str:
    if raw_rarity and str(raw_rarity).strip().lower() in RARITY_ORDER:
        return str(raw_rarity).strip().lower()

    if value <= 500:
        return "common"
    if value <= 2500:
        return "uncommon"
    if value <= 7000:
        return "rare"
    if value <= 13000:
        return "epic"
    return "legendary"


@lru_cache(maxsize=1)
def load_items() -> tuple[GameItem, ...]:
    source_paths = [path for path in _repo_item_source_paths() if path.exists()]
    if not source_paths:
        source = _repo_items_path()
        if not source.exists() and _external_items_path().exists():
            source = _external_items_path()
        source_paths = [source]

    data: list[dict] = []
    for path in source_paths:
        loaded = json.loads(path.read_text())
        if isinstance(loaded, list):
            data.extend(loaded)

    deduped: dict[str, dict] = {}
    for row in data:
        row_id = str(row.get("id") or row.get("name") or "").strip().lower()
        if not row_id:
            continue
        deduped[row_id] = row

    out: list[GameItem] = []
    for row in deduped.values():
        value = int(row.get("value", 0) or 0)
        out.append(
            GameItem(
                id=str(row.get("id") or row["name"]).strip(),
                name=str(row.get("name") or row["id"]).strip(),
                rarity=infer_rarity(row.get("rarity"), value),
                type=str(row.get("type") or "component").strip().lower(),
                value=value,
                found_in=tuple(str(x).strip().lower() for x in (row.get("foundIn") or [])),
                description=str(row.get("description") or ""),
                icon=row.get("icon"),
            )
        )
    return tuple(out)


def filter_items_for_zone(zone: str) -> tuple[GameItem, ...]:
    zone_tags = {
        "Residential": {"residential", "commercial", "nature", "medical"},
        "Industrial": {"industrial", "mechanical", "electrical", "technological", "medical", "commercial"},
        "ARC Site": {"arc", "technological", "electrical", "mechanical", "medical"},
    }
    tags = zone_tags.get(zone, set())
    items = load_items()
    if not tags:
        return items
    filtered = tuple(item for item in items if set(item.found_in) & tags)
    return filtered or items
