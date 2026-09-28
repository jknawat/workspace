"""Indicator maths, checked against hand-computed values."""

from __future__ import annotations

import math

import pytest
from conftest import bars_from_closes

from tbot.core.indicators import (
    atr,
    crossed_above,
    crossed_below,
    ema,
    highest,
    lowest,
    slope_degrees,
    sma,
    true_range,
)


def test_sma_is_none_until_enough_data():
    out = sma([1, 2, 3, 4], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)


def test_ema_is_seeded_with_sma_not_the_first_value():
    # period 3 -> alpha 0.5, seed = mean(1,2,3) = 2.0
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_returns_all_none_when_series_is_shorter_than_period():
    assert ema([1.0, 2.0], 5) == [None, None]


def test_ema_rejects_non_positive_period():
    with pytest.raises(ValueError):
        ema([1.0, 2.0, 3.0], 0)


def test_true_range_uses_previous_close():
    bars = bars_from_closes([1.0, 1.5, 1.2], wick=0.1)
    tr = true_range(bars)
    assert tr[0] == pytest.approx(bars[0].high - bars[0].low)
    # bar 1: high 1.6, low 0.9, prev close 1.0 -> max(0.7, 0.6, 0.1) = 0.7
    assert tr[1] == pytest.approx(0.7)


def test_atr_of_constant_range_equals_that_range():
    closes = [10.0] * 10
    bars = bars_from_closes(closes, wick=0.5)  # every bar spans exactly 1.0
    out = atr(bars, 3)
    assert out[2] == pytest.approx(1.0)
    assert out[-1] == pytest.approx(1.0)


def test_slope_of_unit_ramp_is_45_degrees():
    series = [float(i) for i in range(10)]
    out = slope_degrees(series, lookback=1, scale=1.0)
    assert out[0] is None
    assert out[5] == pytest.approx(45.0)


def test_slope_is_scale_relative():
    series = [float(i) * 0.0001 for i in range(10)]
    out = slope_degrees(series, lookback=1, scale=0.0001)
    assert out[5] == pytest.approx(45.0)
    shallow = slope_degrees(series, lookback=1, scale=0.001)
    assert shallow[5] == pytest.approx(math.degrees(math.atan(0.1)))


def test_slope_skips_undefined_inputs():
    out = slope_degrees([None, None, 1.0, 2.0], lookback=1, scale=1.0)
    assert out[1] is None and out[2] is None
    assert out[3] == pytest.approx(45.0)


def test_crossover_detection_requires_a_strict_cross():
    fast = [1.0, 1.0, 3.0]
    slow = [2.0, 2.0, 2.0]
    assert crossed_above(fast, slow, 2) is True
    assert crossed_above(fast, slow, 1) is False
    assert crossed_below(fast, slow, 2) is False
    assert crossed_below(slow, fast, 2) is True


def test_crossover_ignores_not_ready_values():
    assert crossed_above([None, 2.0], [1.0, 1.0], 1) is False


def test_highest_and_lowest_window_is_inclusive():
    values = [5.0, 1.0, 9.0, 3.0]
    assert highest(values, 3, 3) == 9.0
    assert lowest(values, 3, 3) == 1.0
    assert highest(values, 10, 1) == 5.0  # window clamps at the start of the list
