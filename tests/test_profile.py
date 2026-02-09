from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

from arkpg.game.service import default_profile, normalized_profile


def test_default_profile_uses_discord_suffix() -> None:
    profile = default_profile(123456789)
    assert profile["callsign"] == "Raider-6789"
    assert profile["background_id"] == "starter"
    assert profile["collected_background_ids"] == ["starter"]


def test_normalized_profile_applies_limits() -> None:
    user = SimpleNamespace(
        discord_id=42,
        stats={
            "profile": {
                "callsign": "X" * 100,
                "bio": "Z" * 500,
                "background_id": "unknown",
                "collected_background_ids": ["starter", "bogus"],
            }
        },
    )
    profile = normalized_profile(user)
    assert len(profile["callsign"]) == 32
    assert len(profile["bio"]) == 220
    assert profile["background_id"] == "starter"
    assert profile["collected_background_ids"] == ["starter"]
