"""Pure-python indicators.

Every function returns a list aligned 1:1 with its input, using ``None`` for
bars where the indicator is not yet defined. Callers therefore never have to
reason about offset arithmetic, which is where the classic "index vs timestamp"
bugs come from.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .types import Bar

Series = list[float | None]


def _validate(period: int, n: int) -> bool:
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")
    return n >= period


def sma(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    if not _validate(period, len(values)):
        return out
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """Exponential MA seeded with the SMA of the first ``period`` values.

    Seeding matters: a naive ``ema[0] = values[0]`` seed drifts for hundreds of
    bars on long periods (e.g. a 200 EMA), which silently shifts every filter
    that compares price against it.
    """
    out: Series = [None] * len(values)
    if not _validate(period, len(values)):
        return out
    alpha = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * alpha + prev * (1.0 - alpha)
        out[i] = prev
    return out


def true_range(bars: Sequence[Bar]) -> Series:
    out: Series = [None] * len(bars)
    for i, b in enumerate(bars):
        if i == 0:
            out[i] = b.high - b.low
        else:
            pc = bars[i - 1].close
            out[i] = max(b.high - b.low, abs(b.high - pc), abs(b.low - pc))
    return out


def atr(bars: Sequence[Bar], period: int) -> Series:
    """Wilder's ATR (RMA smoothing), matching the MT5 / TradingView default."""
    out: Series = [None] * len(bars)
    if not _validate(period, len(bars)):
        return out
    tr = [t for t in true_range(bars)]
    seed = sum(float(t) for t in tr[:period]) / period  # type: ignore[arg-type]
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(bars)):
        prev = (prev * (period - 1) + float(tr[i])) / period  # type: ignore[arg-type]
        out[i] = prev
    return out


def slope_degrees(series: Series, lookback: int, scale: float | Series) -> Series:
    """Angle of a series in degrees, normalised by ``scale`` price units per bar.

    ``scale`` may be a constant or a per-bar series.

    **Choose it with care, because the wrong one silently saturates.** Passing
    the symbol's point size works for forex, where a point and a bar's typical
    move are the same order of magnitude. It does not work for gold: with
    ``point = 0.001`` and bars that move whole dollars, every reading comes out
    at 89.8-89.9 degrees, so any "minimum angle" filter passes everything and
    looks like it is working.

    Passing a per-bar ATR series instead makes 45 degrees mean "one ATR per
    bar" on every instrument, which is what comparable actually requires.
    """
    if lookback <= 0:
        raise ValueError("lookback must be > 0")
    constant = not isinstance(scale, list)
    if constant and scale <= 0:  # type: ignore[operator]
        raise ValueError("scale must be > 0")

    out: Series = [None] * len(series)
    for i in range(lookback, len(series)):
        a, b = series[i - lookback], series[i]
        if a is None or b is None:
            continue
        unit = scale if constant else scale[i]  # type: ignore[index]
        if unit is None or unit <= 0:
            continue
        out[i] = math.degrees(math.atan((b - a) / (lookback * unit)))
    return out


def highest(values: Sequence[float], period: int, end: int) -> float:
    start = max(0, end - period + 1)
    return max(values[start : end + 1])


def lowest(values: Sequence[float], period: int, end: int) -> float:
    start = max(0, end - period + 1)
    return min(values[start : end + 1])


def crossed_above(fast: Series, slow: Series, i: int) -> bool:
    """True when ``fast`` crosses strictly above ``slow`` on bar ``i``."""
    if i < 1:
        return False
    f0, f1, s0, s1 = fast[i], fast[i - 1], slow[i], slow[i - 1]
    if None in (f0, f1, s0, s1):
        return False
    return f1 <= s1 and f0 > s0  # type: ignore[operator]


def crossed_below(fast: Series, slow: Series, i: int) -> bool:
    if i < 1:
        return False
    f0, f1, s0, s1 = fast[i], fast[i - 1], slow[i], slow[i - 1]
    if None in (f0, f1, s0, s1):
        return False
    return f1 >= s1 and f0 < s0  # type: ignore[operator]
