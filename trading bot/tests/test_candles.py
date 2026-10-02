"""Candlestick patterns, and the veto/vote split.

Patterns are defined as measurements so they can be backtested; these tests pin
the measurements. The voting chain is tested mostly for what it must *not* do:
a veto cannot be outvoted, because the whole point of a veto is that no amount
of agreement elsewhere buys past it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tbot.config.models import ConfigError
from tbot.core.types import Bar, Side
from tbot.strategy.base import BarContext
from tbot.strategy.candles import detect, summarise
from tbot.strategy.filters import build_chain

TS = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def bar(o, h, lo, c, n=0) -> Bar:
    return Bar(ts=TS + timedelta(minutes=5 * n), open=o, high=h, low=lo, close=c)


def names(bars, i=1, **opt) -> set[str]:
    return {p.name for p in detect(bars, i, **opt)}


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #


def test_a_hammer_is_a_long_lower_wick_that_was_rejected():
    bars = [bar(100, 101, 99, 100, 0), bar(100, 100.5, 94, 100.2, 1)]
    found = detect(bars, 1)
    hammer = next(p for p in found if p.name == "hammer")
    assert hammer.side == "LONG"
    assert hammer.supports("LONG")
    assert not hammer.supports("SHORT")


def test_a_shooting_star_is_the_mirror_image():
    bars = [bar(100, 101, 99, 100, 0), bar(100, 106, 99.5, 99.8, 1)]
    star = next(p for p in detect(bars, 1) if p.name == "shooting_star")
    assert star.side == "SHORT"


def test_wicks_at_both_ends_are_not_a_rejection():
    """A bar that was pushed hard both ways is a fight, not a signal."""
    bars = [bar(100, 101, 99, 100, 0), bar(100, 106, 94, 100.2, 1)]
    assert "hammer" not in names(bars)
    assert "shooting_star" not in names(bars)


def test_engulfing_needs_opposite_directions():
    """A bigger bar the same way is momentum, not engulfing."""
    rising = [bar(100, 101, 99, 100.5, 0), bar(99, 103, 98.5, 102, 1)]
    assert "bullish_engulfing" not in names(rising)

    reversal = [bar(101, 101.5, 99.5, 99.8, 0), bar(99.5, 103, 99, 102.5, 1)]
    assert "bullish_engulfing" in names(reversal)


def test_bearish_engulfing_is_detected():
    bars = [bar(99.5, 101.5, 99, 101, 0), bar(101.5, 102, 98, 98.5, 1)]
    found = {p.name: p for p in detect(bars, 1)}
    assert found["bearish_engulfing"].side == "SHORT"


def test_a_doji_backs_neither_side():
    """Indecision must not be read as agreement with whatever you wanted."""
    bars = [bar(100, 101, 99, 100, 0), bar(100, 102, 98, 100.05, 1)]
    doji = next(p for p in detect(bars, 1) if p.name == "doji")
    assert doji.side == "NEUTRAL"
    assert not doji.supports("LONG")
    assert not doji.supports("SHORT")


def test_a_marubozu_takes_the_direction_of_its_body():
    up = [bar(100, 101, 99, 100, 0), bar(99, 103.1, 98.9, 103, 1)]
    assert next(p for p in detect(up, 1) if p.name == "marubozu").side == "LONG"
    down = [bar(100, 101, 99, 100, 0), bar(103, 103.1, 98.9, 99, 1)]
    assert next(p for p in detect(down, 1) if p.name == "marubozu").side == "SHORT"


def test_an_inside_bar_is_neutral():
    bars = [bar(100, 105, 95, 102, 0), bar(101, 103, 97, 99, 1)]
    inside = next(p for p in detect(bars, 1) if p.name == "inside_bar")
    assert inside.side == "NEUTRAL"


def test_nothing_is_detected_without_a_previous_bar():
    """Every pattern here reads bar i and i-1, so bar 0 has no answer."""
    assert detect([bar(100, 101, 99, 100)], 0) == []


def test_a_flat_bar_is_not_a_pattern():
    """Zero range would divide by zero in every ratio."""
    bars = [bar(100, 100, 100, 100, 0), bar(100, 100, 100, 100, 1)]
    assert detect(bars, 1) == []


def test_out_of_range_indexes_are_handled():
    bars = [bar(100, 101, 99, 100, 0), bar(100, 101, 99, 100, 1)]
    assert detect(bars, 9) == []
    assert detect(bars, -1) == []


def test_the_summary_separates_support_from_opposition():
    bars = [bar(100, 101, 99, 100, 0), bar(100, 100.5, 94, 100.2, 1)]
    found = detect(bars, 1)
    assert "supports LONG" in summarise(found, "LONG")
    assert "against it" in summarise(found, "SHORT")
    assert summarise([], "LONG") == "no pattern on this bar"


# --------------------------------------------------------------------------- #
# Veto vs vote
# --------------------------------------------------------------------------- #


def ctx_for(symbol_cfg, spec, closes=None) -> BarContext:
    from conftest import bars_from_closes

    bars = bars_from_closes(closes or [1.1000] * 40)
    return BarContext(
        cfg=symbol_cfg, spec=spec, bars=bars, i=len(bars) - 1,
        ind={"atr": [0.0010] * len(bars)},
    )


def test_a_veto_cannot_be_outvoted(symbol_cfg, spec_eurusd):
    """The property the whole split exists for.

    Trading through a 2000-point spread loses money whatever else agrees, so a
    veto must not be purchasable with votes from elsewhere.
    """
    chain = build_chain(
        {
            "spread": {"max_points": 1},                      # veto, will fail
            "atr_range": {"min": 0.0, "max": 1.0, "veto": False},  # vote, passes
        },
        min_votes=1,
    )
    ctx = ctx_for(symbol_cfg, spec_eurusd)
    object.__setattr__(ctx, "spread_points", 500.0)
    d = chain.evaluate(ctx, Side.LONG)
    assert not d.passed
    assert "spread" in d.reason


def test_enough_votes_passes_despite_one_objection(symbol_cfg, spec_eurusd):
    chain = build_chain(
        {
            "atr_range": {"min": 0.0, "max": 1.0, "veto": False},    # passes
            "candles": {"require": "support", "veto": False},        # likely fails
        },
        min_votes=1,
    )
    assert chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG).passed


def test_too_few_votes_fails_and_names_the_objections(symbol_cfg, spec_eurusd):
    chain = build_chain(
        {
            "atr_range": {"min": 9.0, "max": 10.0, "veto": False},
            "candles": {"require": "support", "veto": False},
        },
        min_votes=1,
    )
    d = chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG)
    assert not d.passed
    assert "need 1" in d.reason
    assert "atr_range" in d.reason


def test_zero_min_votes_means_all_of_them(symbol_cfg, spec_eurusd):
    """So a config that marks voters but forgets the threshold does not
    silently become permissive."""
    chain = build_chain(
        {
            "atr_range": {"min": 9.0, "max": 10.0, "veto": False},
            "candles": {"require": "no_oppose", "veto": False},
        },
        min_votes=0,
    )
    assert not chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG).passed


def test_all_vetoes_behaves_exactly_as_before(symbol_cfg, spec_eurusd):
    """The default. Nothing marked as a voter means the old all-must-pass rule."""
    chain = build_chain({"atr_range": {"min": 0.0, "max": 1.0}})
    d = chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG)
    assert d.passed
    assert d.reason == "all filters passed"


def test_the_candle_filter_rejects_an_unknown_mode(symbol_cfg, spec_eurusd):
    chain = build_chain({"candles": {"require": "vibes"}})
    d = chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG)
    assert not d.passed
    assert "support|no_oppose|named" in d.reason


def test_named_mode_with_no_patterns_listed_says_so(symbol_cfg, spec_eurusd):
    """Rather than silently refusing every trade forever."""
    chain = build_chain({"candles": {"require": "named"}})
    d = chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG)
    assert not d.passed
    assert "nothing can ever match" in d.reason


def test_an_unknown_filter_option_is_still_refused():
    with pytest.raises(ConfigError, match="unknown option"):
        build_chain({"candles": {"requre": "support"}})
