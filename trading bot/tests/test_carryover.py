"""Open paper positions, across a restart.

Stopping the bot while a simulated trade was open used to delete it outright:
no settlement, no journal row, and a balance still showing the number from
before the trade opened. The record lost a sample, and not a random one --
losers hit their stop quickly while winners run, so the trades most likely to
be open at any moment are the ones that were going well.

The property that matters most here is the second half: restoring a position is
only correct if the bars that passed while the bot was down are replayed. A
stop hit two hours ago must settle at that price and that time, not reappear as
a live trade.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tbot.broker.paper import PaperBroker
from tbot.core.types import Bar, OrderRequest, Side, SymbolSpec
from tbot.engine import carryover
from tbot.journal import Journal

TS = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)

SPEC = SymbolSpec(
    name="XAUUSDm", digits=3, point=0.001, tick_size=0.001, tick_value=0.1,
    volume_min=0.01, volume_step=0.01, volume_max=200.0, contract_size=100.0,
    money_per_price_unit=100.0,
)


def bar(close, high=None, low=None, n=0) -> Bar:
    return Bar(
        ts=TS + timedelta(minutes=5 * n),
        open=close, high=high if high is not None else close,
        low=low if low is not None else close, close=close,
    )


def broker_with_position(sl=3990.0, tp=4030.0) -> PaperBroker:
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    b.on_bar("XAUUSDm", bar(4000.0))
    b.market_order(OrderRequest(
        symbol="XAUUSDm", side=Side.LONG, volume=0.05, sl=sl, tp=tp,
    ))
    return b


def journal_at(tmp_path) -> Journal:
    j = Journal(tmp_path / "j.sqlite")
    j.start_run("paper", "paper", "test")
    return j


# --------------------------------------------------------------------------- #
# Saving and restoring
# --------------------------------------------------------------------------- #


def test_an_open_position_survives_a_restart(tmp_path):
    j = journal_at(tmp_path)
    first = broker_with_position()
    assert len(first.positions()) == 1
    carryover.save(j, first)

    second = PaperBroker(balance=5000.0)
    second.specs["XAUUSDm"] = SPEC
    second.connect()
    restored = carryover.restore(second, carryover.load(j))

    assert len(restored) == 1
    live = second.positions()[0]
    assert live.symbol == "XAUUSDm"
    assert live.side is Side.LONG
    assert live.volume == 0.05
    assert live.sl == 3990.0
    assert live.tp == 4030.0
    j.close()


def test_nothing_open_saves_an_empty_list(tmp_path):
    j = journal_at(tmp_path)
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    carryover.save(j, b)
    assert carryover.load(j) == []
    j.close()


def test_a_fresh_journal_restores_nothing(tmp_path):
    j = journal_at(tmp_path)
    assert carryover.load(j) == []
    j.close()


def test_a_corrupt_record_does_not_stop_the_bot_starting(tmp_path):
    """Refusing to start because a saved position is unreadable would turn a
    lost trade into a bot that will not run at all."""
    j = journal_at(tmp_path)
    j.set_state(carryover.KEY, "not json at all")
    assert carryover.load(j) == []

    j.set_state(carryover.KEY, json.dumps([{"symbol": "XAUUSDm"}]))  # missing fields
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    assert carryover.restore(b, carryover.load(j)) == []
    j.close()


def test_new_tickets_do_not_collide_with_restored_ones(tmp_path):
    """A fresh trade handed a ticket that already belongs to a carried-over
    position would close the wrong one."""
    j = journal_at(tmp_path)
    first = broker_with_position()
    carryover.save(j, first)
    old_ticket = first.positions()[0].ticket

    second = PaperBroker(balance=5000.0)
    second.specs["XAUUSDm"] = SPEC
    second.connect()
    carryover.restore(second, carryover.load(j))
    second.on_bar("XAUUSDm", bar(4000.0))
    second.market_order(OrderRequest(
        symbol="XAUUSDm", side=Side.LONG, volume=0.01, sl=3990.0, tp=4030.0,
    ))
    tickets = [p.ticket for p in second.positions()]
    assert len(tickets) == len(set(tickets)) == 2
    assert max(tickets) > old_ticket
    j.close()


# --------------------------------------------------------------------------- #
# Settling what happened while the bot was off
# --------------------------------------------------------------------------- #


def test_a_stop_hit_during_downtime_settles_rather_than_reopening():
    """The point of the replay. Bringing the position back as live when the
    market closed it hours ago is worse than losing it."""
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    pos = carryover.restore(b, [{
        "ticket": 1, "symbol": "XAUUSDm", "side": "LONG", "volume": 0.05,
        "entry_price": 4000.0, "sl": 3990.0, "tp": 4030.0,
        "opened_at": TS.isoformat(), "strategy": "ema_pullback",
    }])
    missed = [bar(3995.0, n=1), bar(3985.0, high=3996.0, low=3980.0, n=2),
              bar(3998.0, n=3)]
    closed = carryover.settle_missed(b, pos, {"XAUUSDm": missed})

    assert len(closed) == 1
    assert closed[0].pnl < 0
    assert b.positions() == []


def test_a_target_hit_during_downtime_settles_as_a_win():
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    pos = carryover.restore(b, [{
        "ticket": 1, "symbol": "XAUUSDm", "side": "LONG", "volume": 0.05,
        "entry_price": 4000.0, "sl": 3990.0, "tp": 4030.0,
        "opened_at": TS.isoformat(), "strategy": "ema_pullback",
    }])
    missed = [bar(4010.0, n=1), bar(4032.0, high=4035.0, low=4009.0, n=2)]
    closed = carryover.settle_missed(b, pos, {"XAUUSDm": missed})

    assert len(closed) == 1
    assert closed[0].pnl > 0
    assert b.positions() == []


def test_a_position_still_inside_its_range_stays_open():
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    pos = carryover.restore(b, [{
        "ticket": 1, "symbol": "XAUUSDm", "side": "LONG", "volume": 0.05,
        "entry_price": 4000.0, "sl": 3990.0, "tp": 4030.0,
        "opened_at": TS.isoformat(), "strategy": "ema_pullback",
    }])
    missed = [bar(4005.0, high=4008.0, low=3998.0, n=1),
              bar(4012.0, high=4015.0, low=4004.0, n=2)]
    assert carryover.settle_missed(b, pos, {"XAUUSDm": missed}) == []
    assert len(b.positions()) == 1


def test_bars_from_before_the_trade_opened_are_skipped():
    """History the trade already lived through must not re-settle it.

    The runtime hands over its whole warm-up window, which reaches back well
    before the position existed, and those bars may well have crossed the stop
    price before the trade was even placed.
    """
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    opened = TS + timedelta(minutes=50)
    pos = carryover.restore(b, [{
        "ticket": 1, "symbol": "XAUUSDm", "side": "LONG", "volume": 0.05,
        "entry_price": 4000.0, "sl": 3990.0, "tp": 4030.0,
        "opened_at": opened.isoformat(), "strategy": "ema_pullback",
    }])
    # Bars 0-9 are before the trade and dip far below the stop.
    history = [bar(3900.0, high=3905.0, low=3850.0, n=i) for i in range(10)]
    after = [bar(4005.0, high=4008.0, low=4001.0, n=11)]
    assert carryover.settle_missed(b, pos, {"XAUUSDm": history + after}) == []
    assert len(b.positions()) == 1


def test_settling_nothing_is_harmless():
    b = PaperBroker(balance=5000.0)
    b.specs["XAUUSDm"] = SPEC
    b.connect()
    assert carryover.settle_missed(b, [], {"XAUUSDm": [bar(4000.0)]}) == []
