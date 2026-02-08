from datetime import datetime, timedelta, timezone

from arkpg.game.economy import compute_idle_rewards


def test_idle_rewards_capped() -> None:
    now = datetime.now(timezone.utc)
    _, xp, credits = compute_idle_rewards(now - timedelta(hours=40), now, 2, 1, cap_hours=24)
    assert xp <= 24 * 60 * 2
    assert credits <= 24 * 60
