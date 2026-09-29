"""Strategy state machine behaviour.

These are property tests rather than golden-value tests: they assert the rules
the state machine promises (arm, pull back, break out, invalidate, cool down)
hold over a deterministic price path. Golden bar indices would break on any
parameter change without saying anything about correctness.
"""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import pytest
from conftest import bars_from_closes, fast_params, n_shape, v_shape

from tbot.core.types import Phase, Side, Signal
from tbot.strategy import create
from tbot.strategy.base import BarContext


def collect(strategy, cfg, spec, bars) -> list[tuple[int, Signal]]:
    ind = strategy.compute(bars)
    out: list[tuple[int, Signal]] = []
    for i in range(len(bars)):
        ctx = BarContext(cfg=cfg, spec=spec, bars=bars, i=i, ind=ind)
        signal = strategy.on_bar(ctx)
        if signal is not None:
            out.append((i, signal))
    return out


def with_params(cfg, **overrides):
    return dataclasses.replace(cfg, params=fast_params(**overrides))


# --------------------------------------------------------------------------- #
# ema_pullback
# --------------------------------------------------------------------------- #


def test_pullback_breakout_produces_long_signals_on_an_uptrend(symbol_cfg, spec_eurusd):
    bars = bars_from_closes(v_shape())
    strategy = create(symbol_cfg, spec_eurusd)
    signals = collect(strategy, symbol_cfg, spec_eurusd, bars)
    assert signals, "a V-shaped recovery should arm and break out at least once"
    for _, s in signals:
        assert s.side is Side.LONG
        assert s.sl < s.price < s.tp
        assert s.strategy == "ema_pullback"


def test_signal_geometry_follows_the_atr_multipliers(symbol_cfg, spec_eurusd):
    cfg = with_params(symbol_cfg, sl_atr=2.0, tp_atr=4.0)
    bars = bars_from_closes(v_shape())
    signals = collect(create(cfg, spec_eurusd), cfg, spec_eurusd, bars)
    assert signals
    for _, s in signals:
        assert s.rr == pytest.approx(2.0, rel=0.01)
        assert s.sl_distance == pytest.approx(2.0 * s.meta["atr"], rel=0.01)


def test_short_signals_are_not_emitted_when_only_long_is_enabled(symbol_cfg, spec_eurusd):
    bars = bars_from_closes(v_shape())
    signals = collect(create(symbol_cfg, spec_eurusd), symbol_cfg, spec_eurusd, bars)
    assert all(s.side is Side.LONG for _, s in signals)


def test_enabling_short_produces_short_signals_on_the_down_leg(symbol_cfg, spec_eurusd):
    """A rise then a fall: a short can only arm after the fast EMA has been
    above the slow one, which a permanently falling series never gives it."""
    cfg = dataclasses.replace(symbol_cfg, sides=("LONG", "SHORT"))
    bars = bars_from_closes(n_shape())
    signals = collect(create(cfg, spec_eurusd), cfg, spec_eurusd, bars)
    shorts = [s for _, s in signals if s.side is Side.SHORT]
    assert shorts, "the down-leg should produce at least one short setup"
    for s in shorts:
        assert s.tp < s.price < s.sl


def test_no_entry_when_the_required_pullback_cannot_complete_in_time(symbol_cfg, spec_eurusd):
    cfg = with_params(symbol_cfg, pullback_bars=5, pullback_max_wait=2)
    bars = bars_from_closes(v_shape())
    strategy = create(cfg, spec_eurusd)
    assert collect(strategy, cfg, spec_eurusd, bars) == []


def test_disabling_pullback_enters_straight_off_the_crossover(symbol_cfg, spec_eurusd):
    cfg = with_params(symbol_cfg, use_pullback=False)
    bars = bars_from_closes(v_shape())
    signals = collect(create(cfg, spec_eurusd), cfg, spec_eurusd, bars)
    assert signals
    assert all("no pullback" in s.reason for _, s in signals)


def test_cooldown_spaces_consecutive_entries(symbol_cfg, spec_eurusd):
    cooldown = 5
    cfg = with_params(symbol_cfg, cooldown_bars=cooldown, use_pullback=False)
    bars = bars_from_closes(v_shape())
    indices = [i for i, _ in collect(create(cfg, spec_eurusd), cfg, spec_eurusd, bars)]
    gaps = [b - a for a, b in pairwise(indices)]
    assert all(g >= cooldown for g in gaps), gaps


def test_nothing_fires_before_warmup(symbol_cfg, spec_eurusd):
    bars = bars_from_closes(v_shape())
    strategy = create(symbol_cfg, spec_eurusd)
    signals = collect(strategy, symbol_cfg, spec_eurusd, bars)
    assert all(i >= strategy.warmup for i, _ in signals)


def test_a_flat_market_never_signals(symbol_cfg, spec_eurusd):
    bars = bars_from_closes([1.1000] * 120)
    assert collect(create(symbol_cfg, spec_eurusd), symbol_cfg, spec_eurusd, bars) == []


def test_transitions_are_recorded_for_post_hoc_explanation(symbol_cfg, spec_eurusd):
    bars = bars_from_closes(v_shape())
    strategy = create(symbol_cfg, spec_eurusd)
    collect(strategy, symbol_cfg, spec_eurusd, bars)
    events = {t["event"] for t in strategy.transitions}
    assert "transition" in events
    assert all("ts" in t and "i" in t for t in strategy.transitions)


def test_reset_clears_state(symbol_cfg, spec_eurusd):
    bars = bars_from_closes(v_shape())
    strategy = create(symbol_cfg, spec_eurusd)
    collect(strategy, symbol_cfg, spec_eurusd, bars)
    strategy.reset()
    assert strategy.phase is Phase.SCANNING
    assert strategy.side is None
    assert strategy.trigger is None


def test_unknown_strategy_param_is_rejected(symbol_cfg, spec_eurusd):
    from tbot.config.models import ConfigError

    cfg = dataclasses.replace(symbol_cfg, params={"ema_fastt": 8})
    with pytest.raises(ConfigError, match="unknown param"):
        create(cfg, spec_eurusd)


def test_unknown_strategy_name_is_rejected(symbol_cfg, spec_eurusd):
    from tbot.config.models import ConfigError

    cfg = dataclasses.replace(symbol_cfg, strategy="does_not_exist")
    with pytest.raises(ConfigError, match="unknown strategy"):
        create(cfg, spec_eurusd)


# --------------------------------------------------------------------------- #
# donchian -- same engine contract, different logic
# --------------------------------------------------------------------------- #


def test_donchian_breaks_out_of_the_channel(symbol_cfg, spec_eurusd):
    cfg = dataclasses.replace(
        symbol_cfg,
        strategy="donchian",
        sides=("LONG",),
        params={"channel_period": 5, "atr_period": 3, "ema_trend": 6,
                "slope_lookback": 2, "sl_atr": 2.0, "tp_atr": 4.0, "cooldown_bars": 2},
        filters={},
    )
    closes = [1.1000] * 20 + [1.1000 + 0.002 * i for i in range(1, 30)]
    bars = bars_from_closes(closes)
    signals = collect(create(cfg, spec_eurusd), cfg, spec_eurusd, bars)
    assert signals
    assert all(s.side is Side.LONG and "channel breakout" in s.reason for _, s in signals)


def test_donchian_channel_excludes_the_current_bar(symbol_cfg, spec_eurusd):
    """Otherwise a new high could never exceed its own channel: no lookahead,
    and no self-referential level either."""
    cfg = dataclasses.replace(
        symbol_cfg, strategy="donchian",
        params={"channel_period": 5, "atr_period": 3, "ema_trend": 6},
        filters={},
    )
    bars = bars_from_closes([1.1000 + 0.0005 * i for i in range(30)])
    strategy = create(cfg, spec_eurusd)
    ind = strategy.compute(bars)
    i = 20
    assert ind["upper"][i] == pytest.approx(max(b.high for b in bars[i - 5 : i]))
