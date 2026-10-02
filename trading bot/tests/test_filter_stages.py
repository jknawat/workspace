"""Filters can be scoped to when they are asked.

A setup *arms* when the entry condition first appears and is *entered* when
price finally triggers, which on a pullback strategy can be many bars and a
material distance later. A gate measuring price against a moving average is
therefore answering a different question at each point.

The option exists because that difference was worth measuring. It was measured;
see docs/BACKTEST_FINDINGS.md. The answer for ``price_vs_ema`` was to leave it
checked at both, so nothing in the shipped config sets ``when`` -- the default
keeps every filter exactly as it was.
"""

from __future__ import annotations

import pytest
from conftest import bars_from_closes

from tbot.config.models import ConfigError
from tbot.core.types import Side
from tbot.strategy.base import BarContext
from tbot.strategy.filters import STAGE_ARM, STAGE_ENTRY, build_chain


def ctx_for(symbol_cfg, spec, closes=None) -> BarContext:
    bars = bars_from_closes(closes or [1.1000] * 40)
    return BarContext(
        cfg=symbol_cfg, spec=spec, bars=bars, i=len(bars) - 1,
        ind={"atr": [0.0010] * len(bars)},
    )


def test_a_filter_defaults_to_both_stages(symbol_cfg, spec_eurusd):
    chain = build_chain({"atr_range": {"min": 0.0, "max": 1.0}})
    assert chain.filters[0].applies_at(STAGE_ARM)
    assert chain.filters[0].applies_at(STAGE_ENTRY)


def test_entry_only_is_skipped_while_arming(symbol_cfg, spec_eurusd):
    """The point of the option: a gate that only speaks at the breakout."""
    chain = build_chain({"atr_range": {"min": 9.0, "max": 10.0, "when": "entry"}})
    ctx = ctx_for(symbol_cfg, spec_eurusd)
    # Impossible band, so it fails whenever it is actually consulted.
    assert chain.evaluate(ctx, Side.LONG, stage=STAGE_ARM).passed
    assert not chain.evaluate(ctx, Side.LONG, stage=STAGE_ENTRY).passed


def test_arm_only_is_skipped_at_entry(symbol_cfg, spec_eurusd):
    chain = build_chain({"atr_range": {"min": 9.0, "max": 10.0, "when": "arm"}})
    ctx = ctx_for(symbol_cfg, spec_eurusd)
    assert not chain.evaluate(ctx, Side.LONG, stage=STAGE_ARM).passed
    assert chain.evaluate(ctx, Side.LONG, stage=STAGE_ENTRY).passed


def test_no_stage_checks_everything(symbol_cfg, spec_eurusd):
    """Backtests and the display panel evaluate the whole chain.

    This is what keeps the option inert: every existing caller passes no stage
    and therefore sees no change.
    """
    chain = build_chain({"atr_range": {"min": 9.0, "max": 10.0, "when": "entry"}})
    ctx = ctx_for(symbol_cfg, spec_eurusd)
    assert not chain.evaluate(ctx, Side.LONG).passed


def test_a_skipped_filter_leaves_no_trace(symbol_cfg, spec_eurusd):
    """The trace must not imply a verdict that was never reached."""
    chain = build_chain({"atr_range": {"min": 0.0, "max": 1.0, "when": "entry"}})
    decision = chain.evaluate(ctx_for(symbol_cfg, spec_eurusd), Side.LONG,
                              stage=STAGE_ARM)
    assert "atr_range" not in decision.detail["trace"]


def test_an_unknown_stage_is_refused_at_startup():
    with pytest.raises(ConfigError, match=r"both\|arm\|entry"):
        build_chain({"atr_range": {"min": 0.0, "max": 1.0, "when": "sometimes"}})


def test_when_does_not_collide_with_a_filter_option():
    """``when`` is handled centrally, so it must not reach the subclass as an
    unknown option and be rejected."""
    chain = build_chain({"spread": {"max_points": 400, "when": "entry"}})
    assert chain.filters[0].opt["max_points"] == 400
    assert chain.filters[0].when == "entry"
