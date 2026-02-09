from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileBackground:
    id: str
    name: str
    top_color: tuple[int, int, int]
    bottom_color: tuple[int, int, int]


PROFILE_BACKGROUNDS: dict[str, ProfileBackground] = {
    "starter": ProfileBackground("starter", "Starter Night", (34, 21, 46), (12, 10, 18)),
    "sunset_arc": ProfileBackground("sunset_arc", "ARC Sunset", (184, 64, 110), (50, 18, 44)),
    "industrial_ice": ProfileBackground("industrial_ice", "Industrial Ice", (59, 94, 130), (20, 30, 52)),
    "radioactive_dawn": ProfileBackground("radioactive_dawn", "Radioactive Dawn", (129, 103, 50), (33, 29, 11)),
}


DEFAULT_BACKGROUND_ID = "starter"


def get_background(background_id: str | None) -> ProfileBackground:
    if background_id and background_id in PROFILE_BACKGROUNDS:
        return PROFILE_BACKGROUNDS[background_id]
    return PROFILE_BACKGROUNDS[DEFAULT_BACKGROUND_ID]


def normalize_collected_background_ids(background_ids: list[str] | None) -> list[str]:
    existing = {background_id for background_id in (background_ids or []) if background_id in PROFILE_BACKGROUNDS}
    existing.add(DEFAULT_BACKGROUND_ID)
    return sorted(existing)

