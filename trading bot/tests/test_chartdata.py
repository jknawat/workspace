"""The live panel's data, and the two bugs building it exposed.

The panel itself is cosmetic. Assembling it was not: it surfaced that paper
mode charged no spread at all, which made every forward fill cheaper than the
backtest that was supposed to validate it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tbot.broker.paper import PaperBroker
from tbot.engine.chartdata import _next_close

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
