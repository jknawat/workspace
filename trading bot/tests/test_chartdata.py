"""The live panel's data, and the two bugs building it exposed.

The panel itself is cosmetic. Assembling it was not: it surfaced that paper
mode charged no spread at all, which made every forward fill cheaper than the
backtest that was supposed to validate it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tbot.broker.paper import PaperBroker
from tbot.engine.chartdata import _next_close, _trigger_state

TF = "M5"


# --------------------------------------------------------------------------- #
# Paper fills must cost what real ones cost
# --------------------------------------------------------------------------- #


def test_paper_takes_its_spread_from_a_live_source():
    """The bug: with no source the map is empty and every fill was free."""
    b = PaperBroker(balance=5000.0)
    b.spread_source = lambda symbol: 240.0
    assert b.spread_points("XAUUSDm") == 240.0


def test_a_live_source_beats_the_configured_map():
    """A backtest's assumed spread must not override the real one."""
    b = PaperBroker(balance=5000.0)
    b.spread_points_map["XAUUSDm"] = 60.0
    b.spread_source = lambda symbol: 310.0
    assert b.spread_points("XAUUSDm") == 310.0


def test_without_a_source_the_configured_map_still_applies():
    """Backtests pass the spread in directly and must keep working."""
    b = PaperBroker(balance=5000.0)
    b.spread_points_map["XAUUSDm"] = 240.0
    assert b.spread_points("XAUUSDm") == 240.0


def test_a_broken_quote_source_does_not_stop_trading():
    """A dropped MT5 connection must not raise through the fill path."""
    b = PaperBroker(balance=5000.0)
    b.spread_points_map["XAUUSDm"] = 240.0

    def exploding(symbol):
        raise RuntimeError("terminal went away")

    b.spread_source = exploding
    assert b.spread_points("XAUUSDm") == 240.0


def test_a_zero_live_spread_falls_back_rather_than_trading_free():
    """MT5 reports 0 when it has no fresh tick; that is absence, not free."""
    b = PaperBroker(balance=5000.0)
    b.spread_points_map["XAUUSDm"] = 240.0
    b.spread_source = lambda symbol: 0.0
    assert b.spread_points("XAUUSDm") == 240.0


# --------------------------------------------------------------------------- #
# The countdown
# --------------------------------------------------------------------------- #


def test_the_countdown_targets_the_forming_bar_not_the_closed_one():
    """``last_ts`` opens the last *closed* bar, so its own close is past.

    Counting down to that just showed "0s" forever, which reads as a stopped
    bot.
    """
    now = datetime.now(timezone.utc)
    last_closed_open = now - timedelta(minutes=7)
    out = _next_close(last_closed_open, TF)
    assert out["seconds_left"] > 0
    assert datetime.fromisoformat(out["closes_at"]) > now


def test_the_countdown_never_exceeds_one_interval():
    now = datetime.now(timezone.utc)
    for age_minutes in (1, 6, 23, 184):
        out = _next_close(now - timedelta(minutes=age_minutes), TF)
        assert 0 < out["seconds_left"] <= 5 * 60


def test_a_long_market_closure_still_yields_a_future_boundary():
    """Over a weekend the last bar is days old; the loop must still terminate
    on a sensible answer rather than a negative one."""
    now = datetime.now(timezone.utc)
    out = _next_close(now - timedelta(days=3), TF)
    assert out["seconds_left"] > 0
    assert datetime.fromisoformat(out["closes_at"]) > now


def test_the_countdown_reports_the_timeframe_it_used():
    out = _next_close(datetime.now(timezone.utc) - timedelta(minutes=90), "H1")
    assert out["timeframe"] == "H1"
    assert 0 < out["seconds_left"] <= 60 * 60


# --------------------------------------------------------------------------- #
# Permission is not intention
# --------------------------------------------------------------------------- #
#
# Every gate green while the bot sits still looks broken, and reads as "it is
# about to trade". It is not: the strategy arms on the *moment* the fast EMAs
# cross, so once they have crossed and stayed crossed there is nothing to act
# on however green the checklist is.


class _Rt:
    """Just enough runtime for the trigger reading."""

    def __init__(self, confirm, fast):
        self.ind = {"ema_confirm": confirm, "ema_fast": fast}


def test_a_fresh_cross_down_is_reported_as_a_live_trigger():
    out = _trigger_state(_Rt([5.0, 3.0], [4.0, 4.0]))
    assert out["ready"] and out["crossed"]
    assert out["would_be"] == "SHORT"
    assert "sell" in out["note"]


def test_a_fresh_cross_up_is_reported_as_a_live_trigger():
    out = _trigger_state(_Rt([3.0, 5.0], [4.0, 4.0]))
    assert out["crossed"] and out["would_be"] == "LONG"
    assert "buy" in out["note"]


def test_already_below_without_a_cross_is_not_a_trigger():
    """The exact case that confused things: gates green, nothing happening."""
    out = _trigger_state(_Rt([3.0, 2.5], [4.0, 4.0]))
    assert out["ready"]
    assert not out["crossed"]
    assert out["would_be"] == "SHORT"
    assert "has not just crossed" in out["note"]


def test_already_above_without_a_cross_is_not_a_trigger():
    out = _trigger_state(_Rt([5.0, 5.5], [4.0, 4.0]))
    assert not out["crossed"]
    assert out["would_be"] == "LONG"


def test_touching_without_crossing_is_not_a_cross():
    """Equal EMAs count as 'not above', so this must not flip twice."""
    out = _trigger_state(_Rt([3.0, 4.0], [4.0, 4.0]))
    assert not out["crossed"]


def test_unready_emas_do_not_claim_a_direction():
    assert not _trigger_state(_Rt([None, None], [4.0, 4.0]))["ready"]
    assert not _trigger_state(_Rt([], []))["ready"]
    assert not _trigger_state(_Rt([4.0], [4.0]))["ready"]
