"""Exit policies: break-even, trailing, partials, time stops.

The property that matters most is negative: **a stop must never move against
the position**. A trailing stop that can loosen is a mechanism for turning a
small loss into a large one, and it looks like working code right up until it
costs money.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import bars_from_closes

from tbot.broker.paper import PaperBroker
from tbot.config.models import ConfigError, SymbolConfig
from tbot.core.types import Bar, OrderRequest, Position, Side
from tbot.engine.exits import ExitManager, PositionState, available, build_policies
from tbot.strategy.base import BarContext

TS = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def ctx_at(symbol_cfg, spec, price: float, *, i: int = 20, atr: float = 0.0010,
           high: float | None = None, low: float | None = None) -> BarContext:
    """A context whose current bar closes at ``price``."""
    bars = bars_from_closes([1.1000] * (i + 1), wick=0.0002, start=TS)
    bars[i] = Bar(
        ts=TS + timedelta(minutes=5 * i),
        open=price,
        high=high if high is not None else price + 0.0002,
        low=low if low is not None else price - 0.0002,
        close=price,
    )
    return BarContext(
        cfg=symbol_cfg, spec=spec, bars=bars, i=i, ind={"atr": [atr] * (i + 1)}
    )


def long_position(entry: float = 1.1000, sl: float = 1.0980, volume: float = 1.0) -> Position:
    return Position("EURUSD", Side.LONG, volume, entry, sl, 1.1060, TS, ticket=1)


def short_position(entry: float = 1.1000, sl: float = 1.1020) -> Position:
    return Position("EURUSD", Side.SHORT, 1.0, entry, sl, 1.0940, TS, ticket=2)


def advance(broker: PaperBroker, ctx: BarContext) -> None:
    """Show the broker the same bar the context is on.

    The engine always does this (step 1 settles stops on the current bar before
    step 2 manages exits). Without it the broker still thinks price is where the
    position opened, and every stop move looks like it is on the wrong side.
    """
    broker.on_bar(ctx.symbol, ctx.bar)
    broker.drain_closed()


def state_for(pos: Position, best: float, opened_index: int = 0) -> PositionState:
    return PositionState(
        initial_risk=abs(pos.entry_price - pos.sl),
        opened_index=opened_index,
        best_price=best,
    )


# --------------------------------------------------------------------------- #
# break_even
# --------------------------------------------------------------------------- #


def test_break_even_moves_the_stop_once_the_trade_is_ahead(symbol_cfg, spec_eurusd):
    policy = build_policies({"break_even": {"trigger_r": 1.0, "offset_r": 0.1}})[0]
    pos = long_position()  # risk 0.0020
    state = state_for(pos, best=1.1020)

    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1010), state) is None
    action = policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1021), state)
    assert action is not None
    assert action.sl == pytest.approx(1.1000 + 0.1 * 0.0020)


def test_break_even_fires_only_once(symbol_cfg, spec_eurusd):
    policy = build_policies({"break_even": {}})[0]
    pos = long_position()
    state = state_for(pos, best=1.1030)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1030), state) is not None
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1040), state) is None


def test_break_even_works_for_shorts(symbol_cfg, spec_eurusd):
    policy = build_policies({"break_even": {"offset_r": 0.0}})[0]
    pos = short_position()  # entry 1.1000, sl 1.1020, risk 0.0020
    state = state_for(pos, best=1.0980)
    action = policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.0979), state)
    assert action is not None and action.sl == pytest.approx(1.1000)


# --------------------------------------------------------------------------- #
# trailing — the direction guarantee
# --------------------------------------------------------------------------- #


def test_trailing_never_loosens_a_long_stop(symbol_cfg, spec_eurusd):
    """The stop is already at 1.1050; a trail computing 1.1010 must be ignored."""
    policy = build_policies({"trailing_atr": {"distance_atr": 2.0, "start_r": 0.0}})[0]
    pos = long_position(sl=1.1050)
    state = state_for(pos, best=1.1030)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1030), state) is None


def test_trailing_never_loosens_a_short_stop(symbol_cfg, spec_eurusd):
    policy = build_policies({"trailing_atr": {"distance_atr": 2.0, "start_r": 0.0}})[0]
    pos = short_position(sl=1.0950)
    state = state_for(pos, best=1.0970)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.0970), state) is None


def test_trailing_tightens_a_long_stop(symbol_cfg, spec_eurusd):
    policy = build_policies({"trailing_atr": {"distance_atr": 2.0, "start_r": 0.0}})[0]
    pos = long_position()  # sl 1.0980
    state = state_for(pos, best=1.1060)
    action = policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1050), state)
    assert action is not None
    assert action.sl == pytest.approx(1.1060 - 2.0 * 0.0010)
    assert action.sl > pos.sl


def test_trailing_waits_for_start_r(symbol_cfg, spec_eurusd):
    policy = build_policies({"trailing_atr": {"distance_atr": 1.0, "start_r": 2.0}})[0]
    pos = long_position()  # risk 0.0020, so 2R is 1.1040
    state = state_for(pos, best=1.1030)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1030), state) is None
    state.best_price = 1.1045
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1045), state) is not None


def test_trailing_does_nothing_without_an_atr(symbol_cfg, spec_eurusd):
    policy = build_policies({"trailing_atr": {"start_r": 0.0}})[0]
    pos = long_position()
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1050)
    ctx.ind = {}
    assert policy.evaluate(pos, ctx, state_for(pos, best=1.1060)) is None


# --------------------------------------------------------------------------- #
# partial_tp
# --------------------------------------------------------------------------- #


def test_partial_take_profit_closes_half_once(symbol_cfg, spec_eurusd):
    policy = build_policies({"partial_tp": {"trigger_r": 1.0, "percent": 50.0}})[0]
    pos = long_position(volume=1.0)
    state = state_for(pos, best=1.1020)

    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1010), state) is None
    action = policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1025), state)
    assert action is not None and action.is_close
    assert action.volume == pytest.approx(0.5)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1040), state) is None


def test_partial_is_skipped_when_the_slice_is_untradeable(symbol_cfg, spec_eurusd):
    """0.01 lots cannot be halved into two tradeable pieces."""
    policy = build_policies({"partial_tp": {"trigger_r": 1.0, "percent": 50.0}})[0]
    pos = long_position(volume=0.01)
    state = state_for(pos, best=1.1030)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1030), state) is None


# --------------------------------------------------------------------------- #
# time_stop
# --------------------------------------------------------------------------- #


def test_time_stop_closes_a_stalled_trade(symbol_cfg, spec_eurusd):
    policy = build_policies({"time_stop": {"max_bars": 10, "min_r": 0.5}})[0]
    pos = long_position()
    state = state_for(pos, best=1.1005, opened_index=5)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1002, i=12), state) is None
    action = policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1002, i=20), state)
    assert action is not None and action.is_close and action.volume is None


def test_time_stop_lets_a_winner_run(symbol_cfg, spec_eurusd):
    policy = build_policies({"time_stop": {"max_bars": 10, "min_r": 0.5}})[0]
    pos = long_position()
    state = state_for(pos, best=1.1040, opened_index=5)
    assert policy.evaluate(pos, ctx_at(symbol_cfg, spec_eurusd, 1.1040, i=30), state) is None


# --------------------------------------------------------------------------- #
# Manager behaviour, through a real broker
# --------------------------------------------------------------------------- #


@pytest.fixture
def broker_with_position(spec_eurusd):
    broker = PaperBroker(balance=10_000.0, slippage_points=0.0)
    broker.connect()
    broker.on_bar("EURUSD", Bar(ts=TS, open=1.1000, high=1.1002, low=1.0998, close=1.1000))
    result = broker.market_order(OrderRequest("EURUSD", Side.LONG, 1.0, sl=1.0980, tp=1.1060))
    assert result.ok
    return broker


def test_manager_applies_a_break_even_move(symbol_cfg, spec_eurusd, broker_with_position):
    manager = ExitManager.from_config({"break_even": {"trigger_r": 1.0, "offset_r": 0.0}})
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1025, high=1.1030)
    advance(broker_with_position, ctx)
    applied = manager.manage(broker_with_position.positions(), ctx, broker_with_position)
    assert applied and applied[0].ok
    assert broker_with_position.positions()[0].sl == pytest.approx(1.1000)


def test_manager_applies_a_partial_close(symbol_cfg, spec_eurusd, broker_with_position):
    manager = ExitManager.from_config({"partial_tp": {"trigger_r": 1.0, "percent": 40.0}})
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1025, high=1.1030)
    advance(broker_with_position, ctx)
    applied = manager.manage(broker_with_position.positions(), ctx, broker_with_position)
    assert applied and applied[0].ok
    assert broker_with_position.positions()[0].volume == pytest.approx(0.6)
    assert broker_with_position.balance > 10_000.0  # the closed slice was a winner


def test_manager_remembers_initial_risk_after_the_stop_moves(
    symbol_cfg, spec_eurusd, broker_with_position
):
    """R must be measured against the *original* stop.

    Otherwise moving the stop shrinks R, and a "take half off at 1R" policy
    keeps re-triggering as the trade advances.
    """
    manager = ExitManager.from_config(
        {"break_even": {"trigger_r": 1.0, "offset_r": 0.0}, "partial_tp": {"trigger_r": 2.0}}
    )
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1025, high=1.1030)
    advance(broker_with_position, ctx)
    manager.manage(broker_with_position.positions(), ctx, broker_with_position)
    state = manager.state[1]
    assert state.initial_risk == pytest.approx(0.0020)

    later = ctx_at(symbol_cfg, spec_eurusd, 1.1030, high=1.1035)
    advance(broker_with_position, later)
    manager.manage(broker_with_position.positions(), later, broker_with_position)
    assert state.initial_risk == pytest.approx(0.0020)  # unchanged by the BE move


def test_manager_tracks_the_best_price_including_wicks(
    symbol_cfg, spec_eurusd, broker_with_position
):
    """The trail follows the extreme the market reached, not just closes."""
    manager = ExitManager.from_config({"trailing_atr": {"distance_atr": 1.0, "start_r": 0.0}})
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1050, high=1.1055)
    advance(broker_with_position, ctx)
    manager.manage(broker_with_position.positions(), ctx, broker_with_position)
    assert manager.state[1].best_price == pytest.approx(1.1055)
    assert broker_with_position.positions()[0].sl == pytest.approx(1.1045)


def test_trailing_will_not_place_a_stop_above_the_current_price(
    symbol_cfg, spec_eurusd, broker_with_position
):
    """A long wick that closes well back would otherwise trail the stop above
    the market -- an instant stop-out, and a broker rejection."""
    manager = ExitManager.from_config({"trailing_atr": {"distance_atr": 1.0, "start_r": 0.0}})
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1020, high=1.1055)
    advance(broker_with_position, ctx)
    applied = manager.manage(broker_with_position.positions(), ctx, broker_with_position)
    assert applied == []
    assert broker_with_position.positions()[0].sl == pytest.approx(1.0980)


def test_manager_forgets_closed_positions(symbol_cfg, spec_eurusd, broker_with_position):
    manager = ExitManager.from_config({"break_even": {"trigger_r": 1.0}})
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1025, high=1.1030)
    advance(broker_with_position, ctx)
    manager.manage(broker_with_position.positions(), ctx, broker_with_position)
    assert 1 in manager.state
    manager.forget(set())
    assert manager.state == {}


def test_manager_ignores_other_symbols(symbol_cfg, spec_eurusd, broker_with_position):
    manager = ExitManager.from_config({"break_even": {"trigger_r": 0.0}})
    other = Position("XAUUSD", Side.LONG, 1.0, 2000.0, 1990.0, 2050.0, TS, ticket=99)
    ctx = ctx_at(symbol_cfg, spec_eurusd, 1.1025, high=1.1030)
    applied = manager.manage([other], ctx, broker_with_position)
    assert applied == []


def test_empty_manager_does_nothing(symbol_cfg, spec_eurusd, broker_with_position):
    manager = ExitManager.from_config({})
    assert len(manager) == 0
    assert manager.manage(broker_with_position.positions(), ctx_at(symbol_cfg, spec_eurusd, 1.1050),
                          broker_with_position) == []


def test_disabled_policy_is_dropped():
    assert build_policies({"break_even": {"enabled": False}}) == []


def test_unknown_policy_is_rejected():
    with pytest.raises(ConfigError, match="unknown exit policy"):
        build_policies({"pray": {}})


def test_unknown_policy_option_is_rejected():
    with pytest.raises(ConfigError, match="unknown option"):
        build_policies({"break_even": {"triggr_r": 1.0}})


def test_every_policy_is_registered():
    assert set(available()) == {
        "break_even", "trailing_atr", "trailing_structure", "partial_tp", "time_stop"
    }


# --------------------------------------------------------------------------- #
# Broker-level partial close and modify
# --------------------------------------------------------------------------- #


def test_partial_close_reduces_volume_and_banks_pnl(broker_with_position):
    broker = broker_with_position
    broker.on_bar("EURUSD", Bar(ts=TS, open=1.1000, high=1.1030, low=1.1000, close=1.1020))
    result = broker.close_position(1, volume=0.4, reason="partial")
    assert result.ok and result.volume == pytest.approx(0.4)
    assert broker.positions()[0].volume == pytest.approx(0.6)
    # 0.4 lots x 0.0020 x 100,000 per price unit = $80
    assert broker.balance == pytest.approx(10_080.0)


def test_partial_close_refuses_to_leave_an_untradeable_remnant(broker_with_position):
    result = broker_with_position.close_position(1, volume=0.995)
    assert not result.ok and "minimum" in result.message


def test_partial_close_of_the_whole_volume_closes_it(broker_with_position):
    result = broker_with_position.close_position(1, volume=5.0)
    assert result.ok
    assert broker_with_position.positions() == []


def test_modify_rejects_a_stop_on_the_wrong_side(broker_with_position):
    broker_with_position.on_bar(
        "EURUSD", Bar(ts=TS, open=1.1000, high=1.1002, low=1.0998, close=1.1000)
    )
    result = broker_with_position.modify_position(1, sl=1.1010)
    assert not result.ok and "wrong side" in result.message


def test_modify_updates_both_levels(broker_with_position):
    result = broker_with_position.modify_position(1, sl=1.0990, tp=1.1080)
    assert result.ok
    pos = broker_with_position.positions()[0]
    assert (pos.sl, pos.tp) == (pytest.approx(1.0990), pytest.approx(1.1080))


def test_drain_reports_trades_closed_between_bars(broker_with_position):
    broker_with_position.drain_closed()  # clear the opening bar
    broker_with_position.close_position(1, reason="manual")
    drained = broker_with_position.drain_closed()
    assert len(drained) == 1 and drained[0].reason == "manual"
    assert broker_with_position.drain_closed() == []
