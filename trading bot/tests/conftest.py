"""Shared fixtures.

None of these need MetaTrader 5, a network connection, or an open market --
that is the point of the broker port. The whole suite runs on any OS.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tbot.config.models import (  # noqa: E402
    BotConfig,
    EngineConfig,
    RiskConfig,
    SessionConfig,
    SymbolConfig,
)
from tbot.core.types import Bar, SymbolSpec  # noqa: E402

START = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # a Monday


def bars_from_closes(
    closes: list[float],
    wick: float = 0.0005,
    start: datetime = START,
    minutes: int = 5,
) -> list[Bar]:
    """Build clean directional candles from a close series.

    Each bar opens at the previous close, so ``close > open`` exactly when the
    series rose -- which makes pullback counting deterministic in tests.
    """
    bars: list[Bar] = []
    prev = closes[0]
    for i, close in enumerate(closes):
        o = prev
        bars.append(
            Bar(
                ts=start + timedelta(minutes=minutes * i),
                open=o,
                high=max(o, close) + wick,
                low=min(o, close) - wick,
                close=close,
                volume=100.0,
            )
        )
        prev = close
    return bars


def v_shape(down: int = 60, up: int = 60, base: float = 1.1000, step: float = 0.0008) -> list[float]:
    """A down-leg then an up-leg, each with a retracement every 4th bar.

    The retracements are what make the path useful: they generate crossovers in
    both directions and supply the counter-direction candles a pullback entry
    needs. Fully deterministic -- the test suite contains no randomness.
    """
    closes = [base]
    for i in range(down):
        closes.append(closes[-1] + (-step if i % 4 != 3 else step * 0.6))
    for i in range(up):
        closes.append(closes[-1] + (step if i % 4 != 3 else -step * 0.6))
    return closes


@pytest.fixture
def spec_eurusd() -> SymbolSpec:
    return SymbolSpec(
        name="EURUSD",
        digits=5,
        point=0.00001,
        tick_size=0.00001,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        contract_size=100_000.0,
    )


@pytest.fixture
def spec_xauusd() -> SymbolSpec:
    return SymbolSpec(
        name="XAUUSD",
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=50.0,
        contract_size=100.0,
    )


def fast_params(**overrides) -> dict:
    """Short indicator periods so tests need tens of bars, not hundreds."""
    params = {
        "ema_confirm": 2,
        "ema_fast": 3,
        "ema_medium": 4,
        "ema_slow": 5,
        "ema_trend": 6,
        "atr_period": 3,
        "slope_lookback": 2,
        "use_pullback": True,
        "pullback_bars": 1,
        "pullback_max_wait": 6,
        "window_offset_atr": 0.1,
        "window_bars": 4,
        "sl_atr": 2.0,
        "tp_atr": 4.0,
        "cooldown_bars": 2,
    }
    params.update(overrides)
    return params


@pytest.fixture
def symbol_cfg() -> SymbolConfig:
    return SymbolConfig(
        symbol="EURUSD",
        strategy="ema_pullback",
        weight=1.0,
        sides=("LONG",),
        params=fast_params(),
        filters={},
        session=SessionConfig(),
    )


def make_bot_config(
    symbols: list[SymbolConfig],
    *,
    mode: str = "backtest",
    risk: RiskConfig | None = None,
    start_balance: float = 10_000.0,
) -> BotConfig:
    return BotConfig(
        engine=EngineConfig(mode=mode, broker="paper", timeframe="M5", start_balance=start_balance),
        risk=risk or RiskConfig(risk_per_trade_pct=1.0, min_rr=1.0),
        symbols=tuple(symbols),
        log_level="CRITICAL",
        log_file=None,
    )


@pytest.fixture
def bot_cfg(symbol_cfg: SymbolConfig) -> BotConfig:
    return make_bot_config([symbol_cfg])
