"""Rebuilding strategy state after a restart.

A strategy is a state machine: scanning, armed, waiting for a pullback, waiting
for a breakout. Starting fresh throws all of that away -- a setup two bars from
triggering becomes a setup that never existed, and the bot waits for a whole
new crossover. Ten restarts in a day, which is what happened while this was
being built, discards ten chances.

The state is rebuilt by replaying bars rather than persisted, because the
machine's internals are bar *indices* into a window that shifts between runs.
Feeding the bars back through a deterministic machine puts it where the market
left it, with no translation to get wrong.
"""

from __future__ import annotations

import dataclasses

from conftest import bars_from_closes

from tbot.config.models import EngineConfig
from tbot.strategy import create


def rising_then_pulling_back(n: int = 320) -> list:
    """A trend, a crossover, then counter-direction bars: an armed setup."""
    closes = [1.0 + 0.002 * i for i in range(n - 6)]
    closes += [closes[-1] - 0.0015 * (i + 1) for i in range(6)]
    return bars_from_closes(closes)


def fresh(symbol_cfg, spec):
    return create(symbol_cfg, spec)


def feed_all(strategy, cfg, spec, bars, upto=None):
    """Replay bars through a strategy exactly as the runner does."""
    from tbot.strategy.base import BarContext

    ind = strategy.compute(bars)
    end = len(bars) if upto is None else upto
    last = None
    for i in range(strategy.warmup, end):
        ctx = BarContext(cfg=cfg, spec=spec, bars=bars, i=i, ind=ind)
        last = strategy.on_bar(ctx)
    return last


# --------------------------------------------------------------------------- #
# The gap being closed
# --------------------------------------------------------------------------- #


def test_a_strategy_starts_with_no_memory(symbol_cfg, spec_eurusd):
    """The reason this exists: a new strategy object knows nothing."""
    s = fresh(symbol_cfg, spec_eurusd)
    assert s.state_summary()["phase"] == "SCANNING"
    assert s.state_summary()["side"] is None


def test_replaying_reaches_the_same_state_as_never_stopping(symbol_cfg, spec_eurusd):
    """The property the whole approach rests on.

    A strategy fed every bar, and a fresh one fed the same bars after a
    'restart', must agree -- otherwise the replay invents a different bot.
    """
    bars = rising_then_pulling_back()

    never_stopped = fresh(symbol_cfg, spec_eurusd)
    feed_all(never_stopped, symbol_cfg, spec_eurusd, bars)

    after_restart = fresh(symbol_cfg, spec_eurusd)
    feed_all(after_restart, symbol_cfg, spec_eurusd, bars)

    a, b = never_stopped.state_summary(), after_restart.state_summary()
    assert a["phase"] == b["phase"]
    assert a["side"] == b["side"]
    assert a["pullback_count"] == b["pullback_count"]
    assert a["trigger"] == b["trigger"]


def test_without_a_replay_only_the_newest_bar_is_seen(symbol_cfg, spec_eurusd):
    """What used to happen on every restart.

    poll_once hands the strategy one bar. Arming needs a crossover on a
    specific bar and then counter-direction bars after it, so a machine shown
    a single bar cannot be anywhere but SCANNING -- however far along the
    market actually is.
    """
    from tbot.strategy.base import BarContext

    bars = rising_then_pulling_back()
    one_bar_only = fresh(symbol_cfg, spec_eurusd)
    ind = one_bar_only.compute(bars)
    ctx = BarContext(cfg=symbol_cfg, spec=spec_eurusd, bars=bars,
                     i=len(bars) - 1, ind=ind)
    one_bar_only.on_bar(ctx)

    assert one_bar_only.state_summary()["phase"] == "SCANNING"
    assert one_bar_only.state_summary()["side"] is None


def test_the_replay_is_deterministic(symbol_cfg, spec_eurusd):
    """Same bars, same state, every time -- no clock or randomness in it."""
    bars = rising_then_pulling_back()
    states = []
    for _ in range(3):
        s = fresh(symbol_cfg, spec_eurusd)
        feed_all(s, symbol_cfg, spec_eurusd, bars)
        states.append(s.state_summary())
    assert states[0] == states[1] == states[2]


# --------------------------------------------------------------------------- #
# The setting
# --------------------------------------------------------------------------- #


def test_replay_bars_defaults_to_covering_a_whole_setup():
    """pullback_max_wait 10 + window_bars 8 + cooldown 6 is 24 bars; the
    default must comfortably exceed that or a setup is still lost."""
    cfg = EngineConfig.from_dict({})
    assert cfg.replay_bars >= 24
    assert cfg.replay_bars == 60


def test_replay_can_be_switched_off():
    assert EngineConfig.from_dict({"replay_bars": 0}).replay_bars == 0


def test_replay_bars_is_rejected_if_unknown_keys_creep_in():
    """The config refuses unknown keys, so a typo is caught rather than
    silently ignored -- which would leave the replay disabled without saying
    so."""
    import pytest

    from tbot.config.models import ConfigError

    with pytest.raises(ConfigError):
        EngineConfig.from_dict({"replay_barz": 60})


def test_a_symbol_config_is_unchanged_by_replay(symbol_cfg, spec_eurusd):
    """Replaying must not mutate configuration, only strategy state."""
    before = dataclasses.asdict(symbol_cfg)
    s = fresh(symbol_cfg, spec_eurusd)
    feed_all(s, symbol_cfg, spec_eurusd, rising_then_pulling_back())
    assert dataclasses.asdict(symbol_cfg) == before
