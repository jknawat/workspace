"""Support and resistance from swing points.

The strategy already reads *dynamic* support and resistance -- the EMAs it
pulls back to, and the swing extreme it breaks out from. What it has never read
is the horizontal kind: the price levels where the market turned before.

The one rule that makes this honest is confirmation. A swing high at bar *k* is
not knowable at bar *k*: it is only a swing once ``right`` further bars have
failed to exceed it. So a level becomes usable at ``k + right``, never earlier.
Skipping that is the classic way a support-and-resistance backtest invents an
edge it cannot have -- it marks the turning points with hindsight and then
"predicts" them.

The ICT filters already express this idea far more richly, through order blocks
and fair-value gaps. They cannot be backtested, because MT5's snapshot
describes structure only as it stands now. This can, which is the entire reason
it exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.types import Bar


@dataclass(frozen=True, slots=True)
class Level:
    """A price the market turned at, and when it became knowable."""

    price: float
    kind: str            # "high" | "low"
    bar: int             # index of the pivot itself
    confirmed_at: int    # index at which it could first be acted on

    def distance_from(self, price: float) -> float:
        return abs(self.price - price)


def swings(
    bars: list[Bar],
    i: int,
    left: int = 3,
    right: int = 3,
    lookback: int = 300,
) -> list[Level]:
    """Swing highs and lows confirmed on or before bar ``i``.

    A pivot high needs ``left`` bars before it with lower highs and ``right``
    bars after it that fail to exceed it. The second half is why it is only
    confirmed at ``bar + right``.
    """
    if i < 0 or i >= len(bars) or left < 1 or right < 1:
        return []

    start = max(left, i - lookback)
    out: list[Level] = []
    # A pivot at k is confirmed at k + right, so the newest one that can be
    # used at bar i sits at i - right.
    for k in range(start, i - right + 1):
        high, low = bars[k].high, bars[k].low
        is_high = True
        is_low = True
        for j in range(k - left, k + right + 1):
            if j == k or j < 0 or j >= len(bars):
                continue
            if bars[j].high >= high:
                is_high = False
            if bars[j].low <= low:
                is_low = False
            if not is_high and not is_low:
                break
        if is_high:
            out.append(Level(high, "high", k, k + right))
        if is_low:
            out.append(Level(low, "low", k, k + right))
    return out


def nearest_above(levels: list[Level], price: float) -> Level | None:
    """Closest resistance above ``price``, or ``None`` if the way is clear."""
    above = [lv for lv in levels if lv.kind == "high" and lv.price > price]
    return min(above, key=lambda lv: lv.price - price) if above else None


def nearest_below(levels: list[Level], price: float) -> Level | None:
    """Closest support below ``price``."""
    below = [lv for lv in levels if lv.kind == "low" and lv.price < price]
    return min(below, key=lambda lv: price - lv.price) if below else None


def room_toward(levels: list[Level], price: float, side: str) -> float | None:
    """How far price can run before it meets the first level in its way.

    ``None`` means nothing is in the way within the lookback, which is the best
    case rather than a missing answer -- callers should treat it as unlimited.
    """
    lv = nearest_above(levels, price) if side.upper() == "LONG" \
        else nearest_below(levels, price)
    return None if lv is None else lv.distance_from(price)
