from datetime import datetime, timedelta, timezone

from arkpg.game.economy import claim_cooldown_remaining_seconds, compute_idle_rewards


def test_idle_rewards_capped() -> None:
    now = datetime.now(timezone.utc)
    _, xp, credits = compute_idle_rewards(now - timedelta(hours=40), now, 2, 1, cap_hours=24)
    assert xp <= 24 * 60 * 2
    assert credits <= 24 * 60


def test_claim_cooldown_remaining_seconds_zero_without_previous_claim() -> None:
    now = datetime.now(timezone.utc)
    assert claim_cooldown_remaining_seconds(None, now, cooldown_minutes=15) == 0


def test_claim_cooldown_remaining_seconds_counts_down() -> None:
    now = datetime.now(timezone.utc)
    last_claim = now - timedelta(minutes=10)
    assert claim_cooldown_remaining_seconds(last_claim, now, cooldown_minutes=15) == 300


def test_claim_cooldown_remaining_seconds_never_negative() -> None:
    now = datetime.now(timezone.utc)
    last_claim = now - timedelta(minutes=16)
    assert claim_cooldown_remaining_seconds(last_claim, now, cooldown_minutes=15) == 0
