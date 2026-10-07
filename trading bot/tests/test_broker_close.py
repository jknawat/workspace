"""Recording trades the broker closed on its own.

In live trading a stop or target fires server-side. There is no callback -- the
position simply is not there on the next poll. The engine already noticed the
balance had moved and kept the daily-loss kill-switch honest, but it never
recorded *what* happened, so three real trades (-6.22, +54.09, +23.52) sat in
the journal as "open" while the account had long since settled them.

Keeping the signal and losing the outcome is the one failure that makes the
whole record worthless: a dataset of setups with no results cannot teach
anything.
"""

from __future__ import annotations

from datetime import datetime, timezone

from tbot.broker.mt5 import MT5Broker


class _Deal:
    def __init__(self, entry, dtype, price, volume, profit=0.0, commission=0.0,
                 swap=0.0, reason=0, when=1_760_000_000, symbol="XAUUSDm",
                 comment="ema_pullback"):
        self.entry = entry          # 0 in, 1 out
        self.type = dtype           # 0 buy, 1 sell
        self.price = price
        self.volume = volume
        self.profit = profit
        self.commission = commission
        self.swap = swap
        self.reason = reason
        self.time = when
        self.symbol = symbol
        self.comment = comment


class _FakeMT5:
    def __init__(self, deals):
        self._deals = deals

    def history_deals_get(self, position=None):
        return self._deals


def broker_with(deals) -> MT5Broker:
    b = MT5Broker.__new__(MT5Broker)
    b._mt5 = _FakeMT5(deals)  # noqa: SLF001 - wiring a fake binding
    b.magic = 770001
    return b


# --------------------------------------------------------------------------- #
# Reconstruction
# --------------------------------------------------------------------------- #


def test_a_long_closed_at_target_is_reconstructed():
    b = broker_with([
        _Deal(entry=0, dtype=0, price=4000.0, volume=0.05),
        _Deal(entry=1, dtype=1, price=4030.0, volume=0.05, profit=150.0, reason=5),
    ])
    t = b.closed_trade(1)
    assert t is not None
    assert t.side == "LONG"
    assert t.entry_price == 4000.0
    assert t.exit_price == 4030.0
    assert t.pnl == 150.0
    assert t.reason == "TP"


def test_the_side_comes_from_the_entry_deal_not_the_exit():
    """The exit deal is the mirror of the entry. Reading it would record every
    trade backwards -- every long as a short."""
    b = broker_with([
        _Deal(entry=0, dtype=1, price=4000.0, volume=0.02),   # SELL to open
        _Deal(entry=1, dtype=0, price=3980.0, volume=0.02,    # BUY to close
              profit=40.0, reason=5),
    ])
    assert b.closed_trade(1).side == "SHORT"


def test_commission_and_swap_are_included():
    """The pnl must be what actually moved the balance, or the journal and the
    account disagree by exactly the costs."""
    b = broker_with([
        _Deal(entry=0, dtype=0, price=4000.0, volume=0.05, commission=-2.0),
        _Deal(entry=1, dtype=1, price=4030.0, volume=0.05, profit=150.0,
              commission=-2.0, swap=-1.5, reason=5),
    ])
    assert b.closed_trade(1).pnl == 150.0 - 2.0 - 2.0 - 1.5


def test_a_stop_out_is_named():
    b = broker_with([
        _Deal(entry=0, dtype=0, price=4000.0, volume=0.05),
        _Deal(entry=1, dtype=1, price=3990.0, volume=0.05, profit=-50.0, reason=4),
    ])
    assert b.closed_trade(1).reason == "SL"


def test_an_unknown_reason_code_does_not_crash():
    b = broker_with([
        _Deal(entry=0, dtype=0, price=4000.0, volume=0.05),
        _Deal(entry=1, dtype=1, price=4010.0, volume=0.05, profit=50.0, reason=99),
    ])
    assert b.closed_trade(1).reason == "closed"


def test_times_are_timezone_aware_utc():
    """Naive timestamps would be compared against aware ones elsewhere and
    raise at the worst moment."""
    b = broker_with([
        _Deal(entry=0, dtype=0, price=4000.0, volume=0.05, when=1_760_000_000),
        _Deal(entry=1, dtype=1, price=4030.0, volume=0.05, profit=150.0,
              when=1_760_003_600, reason=5),
    ])
    t = b.closed_trade(1)
    assert t.opened_at.tzinfo is timezone.utc
    assert t.closed_at > t.opened_at
    assert isinstance(t.opened_at, datetime)


def test_volume_sums_the_exits():
    """A position closed in two parts is still one trade."""
    b = broker_with([
        _Deal(entry=0, dtype=0, price=4000.0, volume=0.10),
        _Deal(entry=1, dtype=1, price=4020.0, volume=0.05, profit=100.0, reason=5),
        _Deal(entry=1, dtype=1, price=4030.0, volume=0.05, profit=150.0, reason=5),
    ])
    t = b.closed_trade(1)
    assert t.volume == 0.10
    assert t.pnl == 250.0


# --------------------------------------------------------------------------- #
# Refusing to guess
# --------------------------------------------------------------------------- #


def test_a_position_still_open_returns_nothing():
    """One deal in, none out. Inventing an exit price would fabricate a
    result."""
    b = broker_with([_Deal(entry=0, dtype=0, price=4000.0, volume=0.05)])
    assert b.closed_trade(1) is None


def test_no_deals_returns_nothing():
    assert broker_with([]).closed_trade(1) is None
    assert broker_with(None).closed_trade(1) is None


def test_the_default_broker_reconstructs_nothing():
    """Paper and backtest brokers settle their own trades and need no history."""
    from tbot.broker.paper import PaperBroker

    assert PaperBroker(balance=5000.0).closed_trade(1) is None
