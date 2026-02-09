from datetime import datetime, timedelta, timezone


def level_from_xp(xp: int) -> int:
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def xp_for_level(level: int) -> int:
    if level <= 1:
        return 0
    return int(((level - 1) ** (1 / 0.62)) * 120)


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
