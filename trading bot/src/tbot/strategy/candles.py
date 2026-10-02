"""Candlestick patterns, defined in numbers rather than by eye.

Every pattern here is a measurement with thresholds you can argue with, not a
shape someone recognises. "Long lower wick" is `lower >= wick_ratio * body`;
"small body" is `body <= doji_body * range`. That matters because the only way
to find out whether these help is to backtest them, and a pattern that cannot
be computed identically on every bar cannot be backtested at all.

A pattern supports a *side*, never predicts a price. Bullish engulfing supports
a long; it does not mean price will rise. The caller decides what to do with
that, and the backtest decides whether it was worth knowing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.types import Bar

#: Defaults chosen to be unremarkable rather than tuned. Tuning them on the
#: same 310 days every other decision came from would be curve fitting; they
#: are config so they can be tested, not so they can be fiddled with.
DEFAULTS = {
    #: A wick this many times the body counts as a rejection.
    "wick_ratio": 2.0,
    #: A body smaller than this share of the bar's range is indecision.
    "doji_body": 0.1,
    #: A body larger than this share of the range is conviction.
    "marubozu_body": 0.8,
    #: The opposite wick must stay under this share of the range for a
    #: hammer to count -- a bar with long wicks both ends is not a rejection,
    #: it is a fight.
    "opposite_wick": 0.35,
}


@dataclass(frozen=True, slots=True)
class Pattern:
    """One detected pattern and the side it supports."""

    name: str
    side: str            # LONG | SHORT | NEUTRAL
    note: str

    def supports(self, side: str) -> bool:
        return self.side == side.upper()


def _body(bar: Bar) -> float:
    return abs(bar.close - bar.open)


def _upper_wick(bar: Bar) -> float:
    return bar.high - max(bar.open, bar.close)


def _lower_wick(bar: Bar) -> float:
    return min(bar.open, bar.close) - bar.low


def detect(bars: list[Bar], i: int, **options: float) -> list[Pattern]:
    """Every pattern visible on bar ``i``. Reads bars ``i`` and ``i-1`` only.

    No lookahead by construction: a pattern that needed the next bar to confirm
    it would be unusable live, where the next bar does not exist yet.
    """
    opt = {**DEFAULTS, **options}
    if i < 1 or i >= len(bars):
        return []
    bar, prev = bars[i], bars[i - 1]
    rng = bar.range
    if rng <= 0:
        return []

    body = _body(bar)
    upper, lower = _upper_wick(bar), _lower_wick(bar)
    found: list[Pattern] = []

    # -- indecision ------------------------------------------------------ #
    if body <= opt["doji_body"] * rng:
        found.append(Pattern(
            "doji", "NEUTRAL",
            f"body is {body / rng:.0%} of the bar -- buyers and sellers level",
        ))

    # -- rejection wicks ------------------------------------------------- #
    # A hammer is a long *lower* wick: price was pushed down and refused.
    if body > 0 and lower >= opt["wick_ratio"] * body \
            and upper <= opt["opposite_wick"] * rng:
        found.append(Pattern(
            "hammer", "LONG",
            f"lower wick {lower / body:.1f}x the body -- the push down was rejected",
        ))
    if body > 0 and upper >= opt["wick_ratio"] * body \
            and lower <= opt["opposite_wick"] * rng:
        found.append(Pattern(
            "shooting_star", "SHORT",
            f"upper wick {upper / body:.1f}x the body -- the push up was rejected",
        ))

    # -- engulfing ------------------------------------------------------- #
    # The current body must cover the previous body outright, and the two must
    # point opposite ways, or it is just a bigger bar in the same direction.
    prev_body = _body(prev)
    covers = (
        max(bar.open, bar.close) >= max(prev.open, prev.close)
        and min(bar.open, bar.close) <= min(prev.open, prev.close)
        and body > prev_body > 0
    )
    if covers and bar.is_bullish and prev.is_bearish:
        found.append(Pattern(
            "bullish_engulfing", "LONG",
            "this bar's body swallows the previous down bar",
        ))
    if covers and bar.is_bearish and prev.is_bullish:
        found.append(Pattern(
            "bearish_engulfing", "SHORT",
            "this bar's body swallows the previous up bar",
        ))

    # -- conviction ------------------------------------------------------ #
    if body >= opt["marubozu_body"] * rng:
        side = "LONG" if bar.is_bullish else "SHORT"
        found.append(Pattern(
            "marubozu", side,
            f"body is {body / rng:.0%} of the bar -- one side ran it",
        ))

    # -- compression ----------------------------------------------------- #
    if bar.high <= prev.high and bar.low >= prev.low:
        found.append(Pattern(
            "inside_bar", "NEUTRAL",
            "contained by the previous bar -- a pause, not a direction",
        ))

    return found


def summarise(patterns: list[Pattern], side: str) -> str:
    """One line for the decision panel."""
    if not patterns:
        return "no pattern on this bar"
    for_side = [p.name for p in patterns if p.supports(side)]
    against = [p.name for p in patterns if p.side not in ("NEUTRAL", side.upper())]
    neutral = [p.name for p in patterns if p.side == "NEUTRAL"]
    bits = []
    if for_side:
        bits.append(f"{', '.join(for_side)} supports {side}")
    if against:
        bits.append(f"{', '.join(against)} against it")
    if neutral:
        bits.append(f"{', '.join(neutral)} (neither)")
    return "; ".join(bits)
