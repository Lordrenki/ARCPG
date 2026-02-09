import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from arkpg.db.models import TradeStatus


def test_trade_status_values() -> None:
    assert sqlalchemy is not None
    assert TradeStatus.PENDING.value == "pending"
    assert TradeStatus.CONFIRMED.value == "confirmed"
