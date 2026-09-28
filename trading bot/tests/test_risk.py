"""Portfolio risk gate: budgets, caps, and the daily kill-switch."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest
from conftest import make_bot_config

from tbot.config.models import RiskConfig
from tbot.core.types import AccountState, Position, Side, Signal
from tbot.risk import RiskManager

TS = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
ACCOUNT = AccountState(balance=10_000.0, equity=10_000.0)


def signal(symbol="EURUSD", side=Side.LONG, price=1.1000, sl=1.0990, tp=1.1020) -> Signal:
    return Signal(
        symbol=symbol, side=side, ts=TS, price=price, sl=sl, tp=tp,
        strategy="ema_pullback", reason="test",
    )


def position(symbol="EURUSD") -> Position:
    return Position(symbol, Side.LONG, 0.10, 1.1000, 1.0990, 1.1020, TS, ticket=1)


def test_budget_is_split_by_weight(symbol_cfg):
    heavy = dataclasses.replace(symbol_cfg, symbol="EURUSD", weight=3.0)
    light = dataclasses.replace(symbol_cfg, symbol="USDJPY", weight=1.0)
    risk = RiskManager(make_bot_config([heavy, light]))
    # 1% of 10,000 = 100, split 75/25
    assert risk.budget_for("EURUSD", 10_000.0) == pytest.approx(75.0)
    assert risk.budget_for("USDJPY", 10_000.0) == pytest.approx(25.0)


def test_total_deployed_risk_stays_at_the_configured_percentage(symbol_cfg):
    symbols = [
        dataclasses.replace(symbol_cfg, symbol=name, weight=1.0)
        for name in ("EURUSD", "USDJPY", "XAUUSD", "GBPUSD")
    ]
    risk = RiskManager(make_bot_config(symbols))
    total = sum(risk.budget_for(s.symbol, 10_000.0) for s in symbols)
    assert total == pytest.approx(100.0), "four simultaneous signals must still risk 1%, not 4%"


def test_approved_order_is_sized_from_the_budget(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)
    decision, order = risk.approve(signal(), spec_eurusd, ACCOUNT, [])
    assert decision and order is not None
    assert order.volume == pytest.approx(1.0)  # $100 budget / (0.0010 x $100,000)
    assert decision.detail["risk_money"] == pytest.approx(100.0)


def test_order_carries_the_signal_levels(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)
    _, order = risk.approve(signal(), spec_eurusd, ACCOUNT, [])
    assert (order.sl, order.tp, order.side) == (1.0990, 1.1020, Side.LONG)


def test_one_position_per_symbol_is_enforced(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)
    decision, order = risk.approve(signal(), spec_eurusd, ACCOUNT, [position("EURUSD")])
    assert not decision and order is None
    assert "already has" in decision.reason


def test_global_position_cap_is_enforced(symbol_cfg, spec_eurusd):
    cfg = make_bot_config([symbol_cfg], risk=RiskConfig(max_open_positions=2, min_rr=1.0))
    risk = RiskManager(cfg)
    open_positions = [position("GBPUSD"), position("XAUUSD")]
    decision, _ = risk.approve(signal(), spec_eurusd, ACCOUNT, open_positions)
    assert not decision and "cap" in decision.reason


def test_poor_reward_to_risk_is_declined(symbol_cfg, spec_eurusd):
    cfg = make_bot_config([symbol_cfg], risk=RiskConfig(min_rr=2.0))
    risk = RiskManager(cfg)
    decision, _ = risk.approve(
        signal(sl=1.0990, tp=1.1005), spec_eurusd, ACCOUNT, []
    )  # rr = 0.5
    assert not decision and "reward/risk" in decision.reason


def test_zero_stop_distance_is_declined(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)
    decision, _ = risk.approve(signal(sl=1.1000), spec_eurusd, ACCOUNT, [])
    assert not decision and "stop distance" in decision.reason


def test_daily_loss_limit_halts_trading(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)  # 3% of 10,000 = 300
    risk.record_close(-150.0, TS.date())
    assert risk.approve(signal(), spec_eurusd, ACCOUNT, [])[0]
    risk.record_close(-150.0, TS.date())
    decision, order = risk.approve(signal(), spec_eurusd, ACCOUNT, [])
    assert not decision and order is None
    assert "daily loss" in decision.reason


def test_the_halt_stays_in_force_for_the_rest_of_the_day(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)
    risk.record_close(-400.0, TS.date())
    risk.approve(signal(), spec_eurusd, ACCOUNT, [])
    later = dataclasses.replace(signal(), ts=TS.replace(hour=20))
    decision, _ = risk.approve(later, spec_eurusd, ACCOUNT, [])
    assert not decision and "halted" in decision.reason


def test_a_new_day_clears_the_halt(bot_cfg, spec_eurusd):
    risk = RiskManager(bot_cfg)
    risk.record_close(-400.0, TS.date())
    risk.approve(signal(), spec_eurusd, ACCOUNT, [])
    tomorrow = dataclasses.replace(signal(), ts=TS.replace(day=TS.day + 1))
    decision, order = risk.approve(tomorrow, spec_eurusd, ACCOUNT, [])
    assert decision and order is not None


def test_a_budget_too_small_for_one_lot_step_is_declined(symbol_cfg, spec_eurusd):
    cfg = make_bot_config([symbol_cfg], start_balance=20.0)
    risk = RiskManager(cfg)
    tiny = AccountState(balance=20.0, equity=20.0)  # 1% of 20 = $0.20 budget
    decision, order = risk.approve(signal(), spec_eurusd, tiny, [])
    assert not decision and order is None
    assert "sizing" in decision.reason
