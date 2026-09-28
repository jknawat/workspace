"""Filter chain behaviour.

Filters are the part of a trading bot most likely to be silently wrong -- a
filter that always passes looks exactly like a filter that works. Each one is
therefore tested in isolation, in both directions.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, time, timezone

import pytest
from conftest import bars_from_closes

from tbot.config.models import ConfigError, SessionConfig
from tbot.core.types import Side
from tbot.strategy.base import BarContext
from tbot.strategy.filters import build_chain


def ctx_for(cfg, spec, bars, ind, i=None, spread=0.0) -> BarContext:
    return BarContext(
        cfg=cfg, spec=spec, bars=bars, i=len(bars) - 1 if i is None else i,
        ind=ind, spread_points=spread,
    )


@pytest.fixture
def rising(symbol_cfg, spec_eurusd):
    bars = bars_from_closes([1.1000 + 0.0005 * i for i in range(20)])
    ind = {
        "atr": [0.0010] * 20,
        "ema_confirm": [1.1050] * 20,
        "ema_fast": [1.1040] * 20,
        "ema_medium": [1.1030] * 20,
        "ema_slow": [1.1020] * 20,
        "ema_trend": [1.1000] * 20,
        "slope": [20.0] * 20,
    }
    return symbol_cfg, spec_eurusd, bars, ind


def test_atr_range_accepts_inside_and_rejects_outside(rising):
    cfg, spec, bars, ind = rising
    inside = build_chain({"atr_range": {"min": 0.0005, "max": 0.0020}})
    assert inside.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)

    too_quiet = build_chain({"atr_range": {"min": 0.0050}})
    decision = too_quiet.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)
    assert not decision and "below min" in decision.reason

    too_wild = build_chain({"atr_range": {"max": 0.0005}})
    assert "above max" in too_wild.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG).reason


def test_atr_filter_fails_closed_when_the_indicator_is_not_ready(rising):
    cfg, spec, bars, _ = rising
    chain = build_chain({"atr_range": {"min": 0.0001}})
    decision = chain.evaluate(ctx_for(cfg, spec, bars, {"atr": [None] * 20}), Side.LONG)
    assert not decision, "an unready indicator must never be treated as a pass"


def test_ema_order_is_direction_aware(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain({"ema_order": {}})
    assert chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)
    assert not chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.SHORT)


def test_price_vs_ema_is_direction_aware(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain({"price_vs_ema": {"series": "ema_trend"}})
    assert chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)
    assert not chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.SHORT)


def test_angle_uses_the_directional_slope(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain({"angle": {"min_degrees": 10.0}})
    assert chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)
    # the same +20 degree slope is -20 relative to a short
    assert not chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.SHORT)
    steep = build_chain({"angle": {"min_degrees": 45.0}})
    assert not steep.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)


def test_candle_direction_checks_the_requested_window(rising):
    cfg, spec, bars, ind = rising
    one = build_chain({"candle_direction": {"bars": 1}})
    assert one.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)
    assert not one.evaluate(ctx_for(cfg, spec, bars, ind), Side.SHORT)
    three = build_chain({"candle_direction": {"bars": 3}})
    assert three.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)


def test_candle_direction_fails_closed_without_enough_history(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain({"candle_direction": {"bars": 5}})
    assert not chain.evaluate(ctx_for(cfg, spec, bars, ind, i=1), Side.LONG)


def test_session_filter_rejects_outside_hours(symbol_cfg, spec_eurusd):
    cfg = dataclasses.replace(
        symbol_cfg, session=SessionConfig(start=time(7, 0), end=time(16, 0))
    )
    bars = bars_from_closes(
        [1.1, 1.1005], start=datetime(2026, 1, 5, 3, 0, tzinfo=timezone.utc)
    )
    chain = build_chain({"session": {}})
    decision = chain.evaluate(ctx_for(cfg, spec_eurusd, bars, {}), Side.LONG)
    assert not decision and "outside session" in decision.reason


def test_spread_filter_skips_when_no_quote_is_available(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain({"spread": {"max_points": 10}})
    assert chain.evaluate(ctx_for(cfg, spec, bars, ind, spread=0.0), Side.LONG)
    assert not chain.evaluate(ctx_for(cfg, spec, bars, ind, spread=25.0), Side.LONG)


def test_chain_reports_the_first_failure_with_a_full_trace(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain(
        {"atr_range": {"min": 0.0001}, "angle": {"min_degrees": 80.0}, "session": {}}
    )
    decision = chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)
    assert not decision
    assert decision.reason.startswith("angle:")
    trace = decision.detail["trace"]
    assert trace["atr_range"]["passed"] is True
    assert trace["angle"]["passed"] is False
    assert "session" not in trace, "evaluation stops at the first failure"


def test_disabled_filters_are_dropped_from_the_chain(rising):
    cfg, spec, bars, ind = rising
    chain = build_chain({"angle": {"min_degrees": 80.0, "enabled": False}})
    assert len(chain) == 0
    assert chain.evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)


def test_empty_chain_passes_everything(rising):
    cfg, spec, bars, ind = rising
    assert build_chain({}).evaluate(ctx_for(cfg, spec, bars, ind), Side.LONG)


def test_unknown_filter_name_is_rejected():
    with pytest.raises(ConfigError, match="unknown filter"):
        build_chain({"moon_phase": {}})


def test_unknown_filter_option_is_rejected():
    with pytest.raises(ConfigError, match="unknown option"):
        build_chain({"atr_range": {"minimum": 0.1}})
