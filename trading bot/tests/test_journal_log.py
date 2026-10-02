"""The decision log and the learning dataset.

Two properties carry the weight here. The log must stay readable, which means a
repeated "still waiting" cannot be written every bar -- and the dataset must
record declined signals too, because a dataset of only the trades that were
taken can never answer whether the gates were right to refuse the rest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tbot.broker.base import ClosedTrade
from tbot.core.types import Side, Signal
from tbot.journal import Journal

TS = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def journal_at(tmp_path) -> Journal:
    j = Journal(tmp_path / "j.sqlite")
    j.start_run("backtest", "paper", "test")
    return j


def signal(side=Side.LONG, price=4000.0, sl=3990.0, tp=4030.0, ts=TS) -> Signal:
    return Signal(
        symbol="XAUUSDm", side=side, ts=ts, price=price, sl=sl, tp=tp,
        strategy="ema_pullback", reason="test",
    )


def closed(pnl=50.0, entry=4000.0, exit_=4020.0, side="LONG") -> ClosedTrade:
    return ClosedTrade(
        symbol="XAUUSDm", side=side, volume=0.05, entry_price=entry,
        exit_price=exit_, opened_at=TS, closed_at=TS + timedelta(hours=2),
        pnl=pnl, reason="take profit", strategy="ema_pullback",
    )


# --------------------------------------------------------------------------- #
# Keeping the log readable
# --------------------------------------------------------------------------- #


def test_an_unchanged_wait_is_not_logged_twice(tmp_path):
    j = journal_at(tmp_path)
    assert j.record_decision(TS, "XAUUSDm", "wait", "waiting for a setup")
    assert not j.record_decision(TS, "XAUUSDm", "wait", "waiting for a setup")
    assert len(j.recent_decisions()) == 1
    j.close()


def test_a_wait_whose_reason_changes_is_logged(tmp_path):
    j = journal_at(tmp_path)
    j.record_decision(TS, "XAUUSDm", "wait", "waiting for a setup")
    j.record_decision(TS, "XAUUSDm", "wait", "armed LONG, waiting for the pullback")
    assert len(j.recent_decisions()) == 2
    j.close()


def test_reasons_differing_only_by_a_number_count_as_the_same(tmp_path):
    """A session gate names the bar's own clock time in its reason.

    Comparing the raw text logged a fresh row every five minutes and buried
    everything else, so numbers are ignored when deciding whether the reason
    has really changed.
    """
    j = journal_at(tmp_path)
    j.record_decision(TS, "XAUUSDm", "wait", "turned down because session: Fri 01:55")
    j.record_decision(TS, "XAUUSDm", "wait", "turned down because session: Fri 02:00")
    j.record_decision(TS, "XAUUSDm", "wait", "turned down because session: Fri 02:05")
    rows = j.recent_decisions()
    assert len(rows) == 1
    # The row that was written keeps its exact wording.
    assert rows[0]["why"] == "turned down because session: Fri 01:55"
    j.close()


def test_orders_are_always_logged_even_when_identical(tmp_path):
    """Suppressing a repeated order would lose the one row that must not go."""
    j = journal_at(tmp_path)
    for _ in range(3):
        j.record_decision(TS, "XAUUSDm", "buy", "breakout", volume=0.05)
    assert len(j.recent_decisions(action="buy")) == 3
    j.close()


def test_two_symbols_do_not_silence_each_other(tmp_path):
    j = journal_at(tmp_path)
    assert j.record_decision(TS, "XAUUSDm", "wait", "waiting for a setup")
    assert j.record_decision(TS, "EURUSDm", "wait", "waiting for a setup")
    assert len(j.recent_decisions()) == 2
    j.close()


def test_the_log_filters_by_action_and_symbol(tmp_path):
    j = journal_at(tmp_path)
    j.record_decision(TS, "XAUUSDm", "buy", "a", volume=0.01)
    j.record_decision(TS, "XAUUSDm", "sell", "b", volume=0.01)
    j.record_decision(TS, "EURUSDm", "buy", "c", volume=0.01)
    assert len(j.recent_decisions(action="buy")) == 2
    assert len(j.recent_decisions(symbol="EURUSDm")) == 1
    assert len(j.recent_decisions(symbol="EURUSDm", action="sell")) == 0
    j.close()


def test_the_log_is_newest_first(tmp_path):
    j = journal_at(tmp_path)
    j.record_decision(TS, "XAUUSDm", "wait", "first")
    j.record_decision(TS, "XAUUSDm", "wait", "second")
    assert j.recent_decisions()[0]["why"] == "second"
    j.close()


def test_the_score_and_risk_are_stored_as_numbers(tmp_path):
    """The log tab sorts and formats them, so they cannot be prose."""
    j = journal_at(tmp_path)
    j.record_decision(
        TS, "XAUUSDm", "buy", "breakout",
        score=72.5, risk_pct=0.98, volume=0.06, price=4000.5,
    )
    row = j.recent_decisions()[0]
    assert row["score"] == 72.5
    assert row["risk_pct"] == 0.98
    assert row["volume"] == 0.06
    j.close()


# --------------------------------------------------------------------------- #
# The learning dataset
# --------------------------------------------------------------------------- #


def test_a_declined_signal_is_still_recorded(tmp_path):
    """Otherwise nothing can ever test whether declining was right."""
    j = journal_at(tmp_path)
    j.record_observation(signal(), taken=False, score=20.0, features={"mtf": 0.1})
    row = j.conn.execute("SELECT * FROM observations").fetchone()
    assert row["taken"] == 0
    assert row["outcome"] == "not taken"
    j.close()


def test_a_taken_signal_starts_open_and_resolves_on_close(tmp_path):
    j = journal_at(tmp_path)
    j.record_observation(signal(), taken=True, score=70.0)
    assert j.conn.execute(
        "SELECT outcome FROM observations"
    ).fetchone()["outcome"] == "open"

    assert j.resolve_observation(closed(pnl=50.0))
    row = j.conn.execute("SELECT * FROM observations").fetchone()
    assert row["outcome"] == "win"
    assert row["pnl"] == 50.0
    j.close()


def test_a_loss_resolves_as_a_loss(tmp_path):
    j = journal_at(tmp_path)
    j.record_observation(signal(), taken=True, score=70.0)
    j.resolve_observation(closed(pnl=-25.0, exit_=3990.0))
    assert j.conn.execute(
        "SELECT outcome FROM observations"
    ).fetchone()["outcome"] == "loss"
    j.close()


def test_the_r_multiple_is_a_price_ratio_not_a_money_one(tmp_path):
    """So it stays comparable across symbols and lot sizes.

    Entry 4000, stop 3990 is 10 of risk; exiting at 4030 is +30, so 3R --
    whatever the contract size or the number of lots.
    """
    j = journal_at(tmp_path)
    j.record_observation(signal(price=4000.0, sl=3990.0), taken=True, score=70.0)
    j.resolve_observation(closed(pnl=123.45, entry=4000.0, exit_=4030.0))
    assert j.conn.execute(
        "SELECT r_multiple FROM observations"
    ).fetchone()["r_multiple"] == 3.0
    j.close()


def test_a_short_that_falls_is_a_win_in_r_terms(tmp_path):
    """Sign handling, which is easy to get backwards and silently halves a
    bidirectional strategy's measured performance."""
    j = journal_at(tmp_path)
    j.record_observation(
        signal(side=Side.SHORT, price=4000.0, sl=4010.0, tp=3970.0),
        taken=True, score=70.0,
    )
    j.resolve_observation(
        closed(pnl=100.0, entry=4000.0, exit_=3980.0, side="SHORT")
    )
    row = j.conn.execute("SELECT * FROM observations").fetchone()
    assert row["r_multiple"] == 2.0
    assert row["outcome"] == "win"
    j.close()


def test_resolving_with_no_matching_observation_is_harmless(tmp_path):
    j = journal_at(tmp_path)
    assert not j.resolve_observation(closed())
    j.close()


def test_a_declined_observation_is_not_resolved_by_a_later_trade(tmp_path):
    """A refused signal has no outcome; filling one in would fabricate data."""
    j = journal_at(tmp_path)
    j.record_observation(signal(), taken=False, score=20.0)
    assert not j.resolve_observation(closed())
    assert j.conn.execute(
        "SELECT outcome FROM observations"
    ).fetchone()["outcome"] == "not taken"
    j.close()


def test_score_bands_only_count_settled_trades(tmp_path):
    j = journal_at(tmp_path)
    j.record_observation(signal(), taken=True, score=50.0)      # still open
    j.record_observation(signal(), taken=False, score=80.0)     # declined
    j.record_observation(signal(), taken=True, score=80.0)
    j.resolve_observation(closed(pnl=40.0))
    bands = {b["band"]: b for b in j.score_bands(((45, 60), (75, 101)))}
    assert bands["45-59"]["trades"] == 0
    assert bands["75-100"]["trades"] == 1
    assert bands["75-100"]["net"] == 40.0
    j.close()


# --------------------------------------------------------------------------- #
# Upgrading an existing journal
# --------------------------------------------------------------------------- #


def test_an_older_journal_gains_the_new_columns_without_losing_rows(tmp_path):
    """A live journal holds the only copy of its history.

    SQLite has no "ADD COLUMN IF NOT EXISTS", so this is the path that would
    otherwise tempt someone into recreating the file.
    """
    import sqlite3

    path = tmp_path / "old.sqlite"

    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT,
               started_at TEXT NOT NULL, finished_at TEXT, mode TEXT NOT NULL,
               broker TEXT NOT NULL, note TEXT DEFAULT '');
           CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT,
               run_id INTEGER NOT NULL, ts TEXT NOT NULL, symbol TEXT NOT NULL,
               side TEXT NOT NULL, strategy TEXT NOT NULL, price REAL NOT NULL,
               sl REAL NOT NULL, tp REAL NOT NULL, reason TEXT NOT NULL,
               approved INTEGER NOT NULL, decision TEXT NOT NULL, volume REAL,
               meta TEXT NOT NULL DEFAULT '{}');"""
    )
    conn.execute(
        "INSERT INTO runs (started_at, mode, broker) VALUES ('x', 'paper', 'p')"
    )
    conn.execute(
        """INSERT INTO signals (run_id, ts, symbol, side, strategy, price, sl,
               tp, reason, approved, decision)
           VALUES (1, 'x', 'XAUUSDm', 'LONG', 's', 1, 1, 1, 'r', 1, 'ok')"""
    )
    conn.commit()
    conn.close()

    j = Journal(path)
    cols = {r["name"] for r in j.conn.execute("PRAGMA table_info(signals)")}
    assert {"score", "risk_pct"} <= cols
    assert j.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    j.start_run("paper", "p")
    j.record_decision(TS, "XAUUSDm", "wait", "works now")
    assert len(j.recent_decisions()) == 1
    j.close()


def test_an_unchanged_wait_is_restated_after_an_hour(tmp_path):
    """Suppressing forever makes a quiet week look like a stopped bot.

    Someone reading the log during a long wait cannot tell "nothing has
    changed" from "nothing is running", so an unchanged reason is restated
    hourly. Often enough to be a pulse, rare enough not to be a flood.
    """
    j = journal_at(tmp_path)
    assert j.record_decision(TS, "XAUUSDm", "wait", "waiting for a setup")
    assert not j.record_decision(
        TS + timedelta(minutes=55), "XAUUSDm", "wait", "waiting for a setup"
    )
    assert j.record_decision(
        TS + timedelta(minutes=61), "XAUUSDm", "wait", "waiting for a setup"
    )
    assert len(j.recent_decisions()) == 2
    j.close()


def test_the_hourly_pulse_does_not_apply_to_a_changed_reason(tmp_path):
    """A new reason is news whenever it happens, not on the hour."""
    j = journal_at(tmp_path)
    j.record_decision(TS, "XAUUSDm", "wait", "waiting for a setup")
    assert j.record_decision(
        TS + timedelta(minutes=1), "XAUUSDm", "wait", "armed LONG"
    )
    j.close()
