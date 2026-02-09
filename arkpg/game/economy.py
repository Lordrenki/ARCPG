from datetime import datetime, timedelta, timezone


def level_from_xp(xp: int) -> int:
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def xp_for_level(level: int) -> int:
    if level <= 1:
        return 0
    return int(((level - 1) ** (1 / 0.56)) * 180)


def scale_stats_with_level(stats: dict, level: int) -> dict:
    normalized = dict(stats or {})
    normalized["base_combat"] = int(normalized.get("base_combat", normalized.get("combat", 10)) or 10)
    normalized["base_tech"] = int(normalized.get("base_tech", normalized.get("tech", 10)) or 10)
    normalized["base_luck"] = int(normalized.get("base_luck", normalized.get("luck", 10)) or 10)

    level_bonus = max(0, int(level) - 1)
    normalized["combat"] = normalized["base_combat"] + (level_bonus * 2)
    normalized["tech"] = normalized["base_tech"] + (level_bonus * 2)
    normalized["luck"] = normalized["base_luck"] + level_bonus
    return normalized


def compute_idle_rewards(
    last_claim_at: datetime | None,
    now: datetime,
    xp_per_minute: int,
    credits_per_minute: int,
    cap_hours: int,
) -> tuple[int, int, int]:
    if last_claim_at is None:
        last_claim_at = now - timedelta(minutes=15)
    if last_claim_at.tzinfo is None:
        last_claim_at = last_claim_at.replace(tzinfo=timezone.utc)
    elapsed = min(now - last_claim_at, timedelta(hours=cap_hours))
    minutes = max(0, int(elapsed.total_seconds() // 60))

    diminishing = 1.0
    if minutes > 360:
        diminishing = 0.7
    if minutes > 720:
        diminishing = 0.5

    xp = int(minutes * xp_per_minute * diminishing)
    credits = int(minutes * credits_per_minute * diminishing)
    return minutes, xp, credits
