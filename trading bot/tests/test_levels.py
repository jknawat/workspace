"""Support and resistance from swing points.

The property everything else rests on: **a swing is not knowable when it
happens.** A high is only a high once the bars after it have failed to exceed
it, so a level becomes usable `right` bars late. Marking turning points with
hindsight and then "predicting" them is the classic way this kind of filter
invents an edge it cannot have, and it would show up as a backtest that works
and a live account that does not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tbot.core.types import Bar, Side
from tbot.strategy.base import BarContext
from tbot.strategy.filters import build_chain
from tbot.strategy.levels import nearest_above, nearest_below, room_toward, swings

TS = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def series(highs_lows) -> list[Bar]:
    """Build bars from explicit (high, low) pairs."""
    out = []
    for n, (h, lo) in enumerate(highs_lows):
        mid = (h + lo) / 2
        out.append(Bar(ts=TS + timedelta(minutes=5 * n), open=mid, high=h,
                       low=lo, close=mid))
    return out


# --------------------------------------------------------------------------- #
# No lookahead
# --------------------------------------------------------------------------- #


def test_a_swing_is_not_visible_on_the_bar_it_happens():
    """The whole point. The peak is at index 3; it cannot be used at index 3."""
    bars = series([(10, 9), (11, 10), (12, 11), (20, 12), (13, 11), (12, 10),
                   (11, 9), (10, 8)])
    assert swings(bars, 3, left=2, right=2) == []
    assert swings(bars, 4, left=2, right=2) == []
    found = swings(bars, 5, left=2, right=2)
    assert any(lv.price == 20 and lv.kind == "high" for lv in found)


def test_confirmation_lag_matches_the_right_window():
    bars = series([(10, 9), (11, 10), (30, 11), (12, 10), (11, 9), (10, 8),
                   (9, 7), (8, 6)])
    peak = 2
    for right in (1, 2, 3):
        early = swings(bars, peak + right - 1, left=1, right=right)
        assert not any(lv.price == 30 for lv in early), right
        on_time = swings(bars, peak + right, left=1, right=right)
        assert any(lv.price == 30 for lv in on_time), right


def test_the_confirmed_at_index_is_reported():
    bars = series([(10, 9), (11, 10), (30, 11), (12, 10), (11, 9), (10, 8)])
    lv = next(x for x in swings(bars, 5, left=1, right=2) if x.price == 30)
    assert lv.bar == 2
    assert lv.confirmed_at == 4


# --------------------------------------------------------------------------- #
# Finding levels
# --------------------------------------------------------------------------- #


def test_a_peak_is_a_high_and_a_trough_is_a_low():
    bars = series([(10, 9), (15, 14), (10, 5), (15, 14), (10, 9), (11, 10)])
    found = swings(bars, 5, left=1, right=1)
    assert any(lv.kind == "low" and lv.price == 5 for lv in found)


def test_a_flat_run_is_not_a_swing():
    """Equal highs mean neither bar turned the market."""
    bars = series([(10, 9)] * 8)
    assert swings(bars, 7, left=2, right=2) == []


def test_nearest_above_and_below_pick_the_closest():
    """Two peaks above and two troughs below; the near ones must win.

    Every interior bar is a potential pivot, so the series is built with a
    steady slope between the turns -- otherwise the bars meant as filler
    become swings themselves and the test is measuring the wrong level.
    """
    bars = series([
        (10, 9),    # 0
        (20, 19),   # 1  peak
        (16, 15),   # 2
        (30, 29),   # 3  higher peak
        (14, 13),   # 4
        (8, 5),     # 5  trough
        (12, 11),   # 6
        (18, 17),   # 7
    ])
    found = swings(bars, 7, left=1, right=1)
    prices = {(lv.kind, lv.price) for lv in found}
    # Both peaks and both troughs are there...
    assert ("high", 20) in prices and ("high", 30) in prices
    assert ("low", 15) in prices and ("low", 5) in prices
    # ...and the nearest of each is chosen, not the biggest or the newest.
    above = nearest_above(found, 17.0)
    assert above is not None and above.price == 20
    below = nearest_below(found, 17.0)
    assert below is not None and below.price == 15


def test_nothing_in_the_way_reads_as_unlimited_not_missing():
    """A clear path is the best case; returning None must not look like an
    error that a caller then treats as a rejection."""
    bars = series([(10, 9), (20, 19), (10, 5), (11, 10), (12, 11)])
    found = swings(bars, 4, left=1, right=1)
    assert room_toward(found, 1000.0, "LONG") is None
    assert room_toward([], 100.0, "SHORT") is None


def test_room_is_measured_toward_the_trade():
    """The same price has different room depending on which way it is going."""
    bars = series([
        (10, 9),    # 0
        (20, 19),   # 1  peak at 20
        (16, 15),   # 2
        (8, 5),     # 3  trough at 5
        (14, 13),   # 4
        (15, 14),   # 5
    ])
    found = swings(bars, 5, left=1, right=1)
    assert room_toward(found, 12.0, "LONG") == pytest.approx(8.0)   # up to 20
    assert room_toward(found, 12.0, "SHORT") == pytest.approx(7.0)  # down to 5


def test_lookback_limits_how_far_back_levels_count():
    bars = series([(100, 99)] + [(10 + (i % 3), 9) for i in range(1, 60)])
    near = swings(bars, 59, left=1, right=1, lookback=10)
    assert not any(lv.price == 100 for lv in near)


def test_degenerate_inputs_are_handled():
    bars = series([(10, 9), (11, 10)])
    assert swings(bars, 0, left=1, right=1) == []
    assert swings(bars, 99, left=1, right=1) == []
    assert swings(bars, 1, left=0, right=1) == []
    assert swings([], 0) == []


# --------------------------------------------------------------------------- #
# The filter
# --------------------------------------------------------------------------- #


def ctx_with(symbol_cfg, spec, bars, atr=1.0, tp_atr=7.5) -> BarContext:
    import dataclasses

    cfg = dataclasses.replace(symbol_cfg, params={**symbol_cfg.params,
                                                  "tp_atr": tp_atr})
    return BarContext(
        cfg=cfg, spec=spec, bars=bars, i=len(bars) - 1,
        ind={"atr": [atr] * len(bars)},
    )


def test_resistance_in_the_way_blocks_a_long(symbol_cfg, spec_eurusd):
    # Peak at 120, price back at 100, target 7.5 ATR = 75 -> needs 37.5 clear.
    bars = series([(100, 99), (120, 110), (105, 100), (102, 99), (101, 99),
                   (101, 99), (101, 99)])
    chain = build_chain({"sr_room": {"min_room": 0.5, "left": 1, "right": 1}})
    d = chain.evaluate(ctx_with(symbol_cfg, spec_eurusd, bars, atr=10.0),
                       Side.LONG)
    assert not d.passed
    assert "room" in d.reason


def test_a_clear_path_passes(symbol_cfg, spec_eurusd):
    bars = series([(100, 99), (101, 100), (99, 90), (100, 99), (101, 100),
                   (102, 101), (103, 102)])
    chain = build_chain({"sr_room": {"min_room": 0.5, "left": 1, "right": 1}})
    assert chain.evaluate(
        ctx_with(symbol_cfg, spec_eurusd, bars, atr=1.0), Side.LONG
    ).passed


def test_the_same_level_blocks_a_long_but_not_a_short(symbol_cfg, spec_eurusd):
    """Resistance above is only in the way of a buy."""
    bars = series([(100, 99), (120, 110), (105, 100), (102, 99), (101, 99),
                   (101, 99), (101, 99)])
    chain = build_chain({"sr_room": {"min_room": 0.5, "left": 1, "right": 1}})
    ctx = ctx_with(symbol_cfg, spec_eurusd, bars, atr=10.0)
    assert not chain.evaluate(ctx, Side.LONG).passed
    assert chain.evaluate(ctx, Side.SHORT).passed


def test_a_strategy_without_an_atr_target_is_not_judged(symbol_cfg, spec_eurusd):
    """Rejecting a strategy the filter cannot reason about would be noise."""
    bars = series([(100, 99), (120, 110), (105, 100), (102, 99), (101, 99)])
    chain = build_chain({"sr_room": {"min_room": 0.5, "left": 1, "right": 1}})
    d = chain.evaluate(
        ctx_with(symbol_cfg, spec_eurusd, bars, atr=10.0, tp_atr=0.0), Side.LONG
    )
    assert d.passed


def test_an_unready_atr_is_refused_rather_than_guessed(symbol_cfg, spec_eurusd):
    bars = series([(100, 99)] * 6)
    ctx = BarContext(cfg=symbol_cfg, spec=spec_eurusd, bars=bars,
                     i=len(bars) - 1, ind={"atr": [None] * len(bars)})
    d = build_chain({"sr_room": {}}).evaluate(ctx, Side.LONG)
    assert not d.passed
    assert "atr" in d.reason
