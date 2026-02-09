from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ProfileBackground:
    id: str
    name: str
    top_color: tuple[int, int, int]
    bottom_color: tuple[int, int, int]
    image_path: str | None = None


PROFILE_BACKGROUNDS: dict[str, ProfileBackground] = {
    "starter": ProfileBackground("starter", "Starter Night", (34, 21, 46), (12, 10, 18)),
    "sunset_arc": ProfileBackground("sunset_arc", "ARC Sunset", (184, 64, 110), (50, 18, 44)),
    "industrial_ice": ProfileBackground("industrial_ice", "Industrial Ice", (59, 94, 130), (20, 30, 52)),
    "radioactive_dawn": ProfileBackground("radioactive_dawn", "Radioactive Dawn", (129, 103, 50), (33, 29, 11)),
}

CUSTOM_BACKGROUNDS_PATH = Path(__file__).resolve().parents[1] / "assets" / "profile_backgrounds" / "custom_backgrounds.json"


DEFAULT_BACKGROUND_ID = "starter"


def get_background(background_id: str | None) -> ProfileBackground:
    if background_id and background_id in PROFILE_BACKGROUNDS:
        return PROFILE_BACKGROUNDS[background_id]
    return PROFILE_BACKGROUNDS[DEFAULT_BACKGROUND_ID]


def load_custom_backgrounds() -> None:
    if not CUSTOM_BACKGROUNDS_PATH.exists():
        return
    try:
        payload = json.loads(CUSTOM_BACKGROUNDS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(payload, list):
        return
    for row in payload:
        if not isinstance(row, dict):
            continue
        background_id = str(row.get("id") or "").strip().lower()
        name = str(row.get("name") or "").strip()
        image_path = str(row.get("image_path") or "").strip()
        if not background_id or not name or not image_path:
            continue
        PROFILE_BACKGROUNDS[background_id] = ProfileBackground(
            id=background_id,
            name=name,
            top_color=(34, 21, 46),
            bottom_color=(12, 10, 18),
            image_path=image_path,
        )


def save_custom_background(background_id: str, name: str, image_path: str) -> None:
    CUSTOM_BACKGROUNDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    if CUSTOM_BACKGROUNDS_PATH.exists():
        try:
            loaded = json.loads(CUSTOM_BACKGROUNDS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = [row for row in loaded if isinstance(row, dict)]
        except (json.JSONDecodeError, OSError):
            rows = []

    normalized_id = background_id.strip().lower()
    rows = [row for row in rows if str(row.get("id", "")).strip().lower() != normalized_id]
    rows.append({"id": normalized_id, "name": name.strip(), "image_path": image_path})
    CUSTOM_BACKGROUNDS_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    PROFILE_BACKGROUNDS[normalized_id] = ProfileBackground(
        id=normalized_id,
        name=name.strip(),
        top_color=(34, 21, 46),
        bottom_color=(12, 10, 18),
        image_path=image_path,
    )


def normalize_collected_background_ids(background_ids: list[str] | None) -> list[str]:
    existing = {background_id for background_id in (background_ids or []) if background_id in PROFILE_BACKGROUNDS}
    existing.add(DEFAULT_BACKGROUND_ID)
    return sorted(existing)


load_custom_backgrounds()
