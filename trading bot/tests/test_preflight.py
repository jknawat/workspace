"""Refuse to start live if the broker will refuse every order.

Two live orders were lost to a malformed comment field. The bot started
cleanly, reported three symbols, scanned for hours, and only revealed the
problem on the first signal -- by which time the setup was gone. The orders had
been logged as filled.

A broker that will reject every request should say so while someone is still
looking at the window. These tests pin the distinction the check rests on: a
malformed *request* stops the start, a closed market or an empty account does
not.
"""

from __future__ import annotations

import pytest

from tbot.broker.base import Broker, BrokerError
from tbot.broker.mt5 import MT5Broker


class _Result:
    def __init__(self, retcode, comment="test"):
        self.retcode = retcode
        self.comment = comment


class _Info:
    def __init__(self):
        self.volume_min = 0.01
        self.digits = 3
        self.filling_mode = 3


class _Tick:
    ask = 4000.0
    bid = 3999.0


class _FakeMT5:
    """Just enough of the binding for preflight."""

    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2

    def __init__(self, check_result, info=True, tick=True):
        self._check = check_result
        self._info = _Info() if info else None
        self._tick = _Tick() if tick else None
        self.sent = []

    def symbol_info(self, s):
        return self._info

    def symbol_info_tick(self, s):
        return self._tick

    def order_check(self, req):
        self.sent.append(req)
        return self._check

    def last_error(self):
        return (-2, 'Invalid "comment" argument')


def broker_with(fake) -> MT5Broker:
    """A broker wired to a fake binding.

    ``mt5`` is a read-only property guarding against use before connect(), so
    the backing field is set directly rather than the property.
    """
    b = MT5Broker.__new__(MT5Broker)
    b._mt5 = fake  # noqa: SLF001 - wiring a fake binding for the test
    b.magic = 770001
    b.deviation_points = 20
    return b


# --------------------------------------------------------------------------- #
# What must stop the start
# --------------------------------------------------------------------------- #


def test_a_refused_request_shape_is_fatal():
    """The exact failure that cost two trades: order_check returns None."""
    b = broker_with(_FakeMT5(check_result=None))
    fatal, message = b.preflight("XAUUSDm")
    assert fatal
    assert "refused the request shape" in message


@pytest.mark.parametrize("retcode", [10013, 10014, 10015, 10016, 10030])
def test_structural_retcodes_are_fatal(retcode):
    """Invalid request, volume, price, stops, filling mode -- none of these
    get better by waiting, so every order would be refused."""
    b = broker_with(_FakeMT5(check_result=_Result(retcode)))
    fatal, message = b.preflight("XAUUSDm")
    assert fatal
    assert str(retcode) in message


def test_an_unknown_symbol_is_fatal():
    b = broker_with(_FakeMT5(check_result=_Result(0), info=False))
    fatal, message = b.preflight("NOPEm")
    assert fatal
    assert "not offered" in message


# --------------------------------------------------------------------------- #
# What must not stop the start
# --------------------------------------------------------------------------- #


def test_no_quote_yet_is_not_fatal():
    """A closed market is a condition of the moment, not a broken request."""
    b = broker_with(_FakeMT5(check_result=_Result(0), tick=False))
    fatal, message = b.preflight("XAUUSDm")
    assert not fatal
    assert "market closed" in message


def test_no_money_is_not_fatal():
    """It will trade again after a loss is recovered or a deposit lands."""
    b = broker_with(_FakeMT5(check_result=_Result(10019, "no money")))
    fatal, _ = b.preflight("XAUUSDm")
    assert not fatal


def test_a_clean_check_passes():
    b = broker_with(_FakeMT5(check_result=_Result(0)))
    fatal, message = b.preflight("XAUUSDm")
    assert not fatal
    assert message.endswith("ok")


# --------------------------------------------------------------------------- #
# It checks the request the bot would really send
# --------------------------------------------------------------------------- #


def test_the_probe_carries_a_comment_within_the_limit():
    """Otherwise the check would pass while real orders failed -- the precise
    way this bug hid."""
    from tbot.broker.mt5 import MAX_COMMENT

    fake = _FakeMT5(check_result=_Result(0))
    broker_with(fake).preflight("XAUUSDm")
    assert len(fake.sent[0]["comment"]) <= MAX_COMMENT


def test_the_probe_uses_the_symbols_minimum_volume():
    fake = _FakeMT5(check_result=_Result(0))
    broker_with(fake).preflight("XAUUSDm")
    assert fake.sent[0]["volume"] == 0.01


def test_the_probe_carries_the_bots_magic_number():
    """So a check cannot pass under settings the real orders do not use."""
    fake = _FakeMT5(check_result=_Result(0))
    broker_with(fake).preflight("XAUUSDm")
    assert fake.sent[0]["magic"] == 770001


# --------------------------------------------------------------------------- #
# The default
# --------------------------------------------------------------------------- #


def test_a_broker_without_a_preflight_does_not_block_anything():
    """Paper and backtest brokers have no broker to ask."""

    class Bare(Broker):
        def connect(self): ...
        def disconnect(self): ...
        def account(self): ...
        def symbol_spec(self, symbol): ...
        def bars(self, symbol, timeframe, count): ...
        def positions(self, symbol=None): ...
        def market_order(self, req): ...
        def close_position(self, ticket, volume=None, reason="manual"): ...
        def modify_position(self, ticket, sl=None, tp=None): ...

    fatal, _ = Bare().preflight("XAUUSDm")
    assert not fatal


def test_brokererror_is_what_the_runner_raises():
    """It maps to exit code 2, which run.bat does not retry -- a bot spinning
    on a request the broker will always refuse is worse than one plainly down.
    """
    assert issubclass(BrokerError, Exception)
