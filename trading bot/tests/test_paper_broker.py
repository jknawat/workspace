"""Simulated broker: fills, stop/target handling and PnL arithmetic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tbot.broker.paper import PaperBroker
from tbot.core.types import Bar, OrderRequest, Side

TS = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def bar(o: float, h: float, lo: float, c: float, offset: int = 0) -> Bar:
    return Bar(ts=TS + timedelta(minutes=5 * offset), open=o, high=h, low=lo, close=c)


@pytest.fixture
def broker() -> PaperBroker:
    b = PaperBroker(balance=10_000.0, slippage_points=0.0)
    b.connect()
    return b


def test_order_is_rejected_before_any_market_data(broker):
    req = OrderRequest("EURUSD", Side.LONG, 0.10, sl=1.0990, tp=1.1030)
    result = broker.market_order(req)
    assert not result.ok and "no market data" in result.message


def test_fill_happens_at_the_bar_close_plus_costs(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1005))
    broker.spread_points_map["EURUSD"] = 20.0  # 20 points -> half spread = 10 points
    broker.slippage_points = 5.0
    result = broker.market_order(OrderRequest("EURUSD", Side.LONG, 0.10, 1.0990, 1.1030))
    assert result.ok
    assert result.price == pytest.approx(1.1005 + 15 * 0.00001, abs=1e-9)


def test_short_fill_is_worsened_in_the_other_direction(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1005))
    broker.slippage_points = 10.0
    result = broker.market_order(OrderRequest("EURUSD", Side.SHORT, 0.10, 1.1030, 1.0980))
    assert result.ok
    assert result.price == pytest.approx(1.1005 - 10 * 0.00001, abs=1e-9)


def test_order_with_a_stop_on_the_wrong_side_is_rejected(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1005))
    result = broker.market_order(OrderRequest("EURUSD", Side.LONG, 0.10, sl=1.1020, tp=1.1050))
    assert not result.ok and "wrong side" in result.message


def test_volume_below_the_broker_minimum_is_rejected(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1005))
    result = broker.market_order(OrderRequest("EURUSD", Side.LONG, 0.001, 1.0990, 1.1030))
    assert not result.ok and "below min" in result.message


def test_take_profit_closes_the_position_and_credits_the_balance(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    broker.market_order(OrderRequest("EURUSD", Side.LONG, 1.0, sl=1.0990, tp=1.1010))
    closed = broker.on_bar("EURUSD", bar(1.1000, 1.1015, 1.0995, 1.1012, offset=1))
    assert len(closed) == 1
    assert closed[0].reason == "TP"
    # 1.0 lot, +0.0010 of price, $100,000 per price unit -> +$100
    assert closed[0].pnl == pytest.approx(100.0)
    assert broker.balance == pytest.approx(10_100.0)
    assert broker.positions() == []


def test_stop_loss_debits_the_balance(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    broker.market_order(OrderRequest("EURUSD", Side.LONG, 1.0, sl=1.0990, tp=1.1050))
    closed = broker.on_bar("EURUSD", bar(1.1000, 1.1005, 1.0985, 1.0995, offset=1))
    assert closed[0].reason == "SL"
    assert closed[0].pnl == pytest.approx(-100.0)
    assert broker.balance == pytest.approx(9_900.0)


def test_a_bar_touching_both_levels_is_resolved_as_a_loss(broker):
    """Pessimistic by design: OHLC cannot tell us which came first."""
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    broker.market_order(OrderRequest("EURUSD", Side.LONG, 1.0, sl=1.0990, tp=1.1010))
    closed = broker.on_bar("EURUSD", bar(1.1000, 1.1020, 1.0980, 1.1000, offset=1))
    assert closed[0].reason == "SL"
    assert closed[0].pnl < 0


def test_short_pnl_has_the_opposite_sign(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    broker.market_order(OrderRequest("EURUSD", Side.SHORT, 1.0, sl=1.1010, tp=1.0990))
    closed = broker.on_bar("EURUSD", bar(1.1000, 1.1005, 1.0985, 1.0990, offset=1))
    assert closed[0].reason == "TP"
    assert closed[0].pnl == pytest.approx(100.0)


def test_metal_pnl_uses_the_metal_contract_size(broker):
    broker.on_bar("XAUUSD", bar(2000.0, 2001.0, 1999.0, 2000.0))
    broker.market_order(OrderRequest("XAUUSD", Side.LONG, 1.0, sl=1995.0, tp=2010.0))
    closed = broker.on_bar("XAUUSD", bar(2000.0, 2011.0, 1999.5, 2010.5, offset=1))
    # 100 oz per lot, +$10 of price -> +$1,000
    assert closed[0].pnl == pytest.approx(1000.0)


def test_equity_reflects_open_positions(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    broker.market_order(OrderRequest("EURUSD", Side.LONG, 1.0, sl=1.0950, tp=1.1100))
    broker.on_bar("EURUSD", bar(1.1000, 1.1012, 1.0998, 1.1010, offset=1))
    account = broker.account()
    assert account.balance == pytest.approx(10_000.0)
    assert account.equity == pytest.approx(10_100.0)


def test_manual_close_settles_at_the_last_close(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    opened = broker.market_order(OrderRequest("EURUSD", Side.LONG, 1.0, 1.0950, 1.1100))
    broker.on_bar("EURUSD", bar(1.1000, 1.1012, 1.0998, 1.1010, offset=1))
    result = broker.close_position(opened.ticket, reason="manual")
    assert result.ok
    assert broker.positions() == []
    assert broker.closed_trades[-1].pnl == pytest.approx(100.0)


def test_force_close_all_drains_open_positions(broker):
    broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000))
    broker.market_order(OrderRequest("EURUSD", Side.LONG, 0.10, 1.0950, 1.1100))
    closed = broker.force_close_all("session end")
    assert len(closed) == 1 and closed[0].reason == "session end"
    assert broker.positions() == []


def test_unknown_symbol_has_no_simulated_spec(broker):
    from tbot.broker.base import BrokerError

    with pytest.raises(BrokerError, match="no simulated spec"):
        broker.symbol_spec("NOPE")


def test_equity_curve_is_recorded_per_bar(broker):
    for i in range(3):
        broker.on_bar("EURUSD", bar(1.1000, 1.1010, 1.0990, 1.1000, offset=i))
    assert len(broker.equity_curve) == 3
