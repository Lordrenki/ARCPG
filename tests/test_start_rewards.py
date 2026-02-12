from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

from arkpg.game.service import can_receive_start_kit, mark_start_command_used


def test_start_kit_allowed_before_start_command_used() -> None:
    user = SimpleNamespace(stats={})
    assert can_receive_start_kit(user) is True


def test_start_kit_blocked_after_start_command_used() -> None:
    user = SimpleNamespace(stats={"start_command_used": True})
    assert can_receive_start_kit(user) is False


def test_mark_start_command_used_sets_flag() -> None:
    user = SimpleNamespace(stats={"health": 100})
    mark_start_command_used(user)
    assert user.stats["start_command_used"] is True
    assert user.stats["health"] == 100
