"""End-to-end pipeline tests: feed -> strategy -> risk -> broker -> journal.

These are the tests that would have caught the class of bug where a GUI path
and a headless path drift apart, because there is only one path to test.
"""

from __future__ import annotations

import dataclasses

import pytest
from conftest import bars_from_closes, make_bot_config, v_shape

from tbot.config.models import RiskConfig
from tbot.data.feed import CsvFeed, ListFeed
from tbot.engine import TradeEngine, run_backtest
from tbot.journal import Journal


@pytest.fixture
def feed():
    return ListFeed({"EURUSD": bars_from_closes(v_shape(down=80, up=120))})


def test_backtest_runs_the_whole_pipeline(bot_cfg, feed):
    report = run_backtest(bot_cfg, feed)
    assert report.bars == len(feed.bars["EURUSD"])
    assert report.signals >= 1
    assert report.trades, "signals should have produced closed trades"
    assert len(report.equity_curve) == report.bars


def test_report_metrics_are_self_consistent(bot_cfg, feed):
    report = run_backtest(bot_cfg, feed)
    assert len(report.wins) + len(report.losses) == len(report.trades)
    assert report.net_pnl == pytest.approx(sum(t.pnl for t in report.trades), abs=1e-6)
    assert report.end_balance == pytest.approx(report.start_balance + report.net_pnl)
    assert 0.0 <= report.win_rate <= 100.0
    assert report.max_drawdown >= 0.0


def test_report_renders_without_blowing_up_on_zero_trades(symbol_cfg):
    cfg = make_bot_config([symbol_cfg])
    flat = ListFeed({"EURUSD": bars_from_closes([1.1000] * 80)})
    report = run_backtest(cfg, flat)
    assert report.trades == []
    assert report.win_rate == 0.0
    assert "trades closed" in report.render()


def test_risk_gate_can_veto_every_signal(symbol_cfg, feed):
    cfg = make_bot_config([symbol_cfg], risk=RiskConfig(min_rr=99.0))
    report = run_backtest(cfg, feed)
    assert report.signals >= 1
    assert report.declined == report.signals
    assert report.trades == []
    assert any("reward/risk" in reason for reason in report.declined_reasons)


def test_position_cap_is_respected_across_symbols(symbol_cfg):
    symbols = [
        dataclasses.replace(symbol_cfg, symbol=name)
        for name in ("EURUSD", "GBPUSD", "XAUUSD")
    ]
    cfg = make_bot_config(symbols, risk=RiskConfig(max_open_positions=1, min_rr=1.0))
    closes = v_shape(down=80, up=120)
    feed = ListFeed(
        {
            "EURUSD": bars_from_closes(closes),
            "GBPUSD": bars_from_closes(closes),
            "XAUUSD": bars_from_closes([c * 1800 for c in closes]),
        }
    )
    report = run_backtest(cfg, feed)
    declined = " ".join(report.declined_reasons)
    assert report.declined >= 1
    assert "cap" in declined or "already has" in declined


def test_backtest_without_data_fails_loudly(bot_cfg):
    with pytest.raises(ValueError, match="no data"):
        run_backtest(bot_cfg, ListFeed({}))


def test_journal_records_signals_trades_and_rejections(bot_cfg, feed, tmp_path):
    journal = Journal(tmp_path / "journal.sqlite")
    journal.start_run("backtest", "paper")
    report = run_backtest(bot_cfg, feed, journal=journal)
    stats = journal.stats()
    assert stats["trades"] == len(report.trades)
    assert stats["net_pnl"] == pytest.approx(report.net_pnl, abs=1e-6)
    rows = journal.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert rows == report.signals
    journal.close()


def test_journal_explains_why_signals_were_declined(symbol_cfg, feed, tmp_path):
    cfg = make_bot_config([symbol_cfg], risk=RiskConfig(min_rr=99.0))
    journal = Journal(tmp_path / "journal.sqlite")
    journal.start_run("backtest", "paper")
    run_backtest(cfg, feed, journal=journal)
    rejections = journal.rejection_counts()
    assert rejections
    assert any("reward/risk" in reason for _, reason, _ in rejections)
    journal.close()


def test_journal_requires_a_run_before_writing(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite")
    with pytest.raises(RuntimeError, match="start_run"):
        journal.record_equity(bars_from_closes([1.0, 1.1])[0].ts, 100.0)
    journal.close()


def test_engine_state_exposes_each_strategy_phase(bot_cfg):
    from tbot.broker.paper import PaperBroker

    broker = PaperBroker(balance=1_000.0)
    broker.connect()
    engine = TradeEngine(bot_cfg, broker)
    engine.register_all()
    state = engine.state()
    assert set(state) == {"EURUSD"}
    assert state["EURUSD"]["phase"] == "SCANNING"


def test_csv_feed_round_trips_bars(tmp_path):
    path = tmp_path / "EURUSD_M5.csv"
    path.write_text(
        "ts,open,high,low,close,volume\n"
        "2026-01-05T00:00:00Z,1.1000,1.1010,1.0990,1.1005,100\n"
        "2026-01-05T00:05:00Z,1.1005,1.1015,1.1000,1.1012,120\n",
        encoding="utf-8",
    )
    bars = CsvFeed(tmp_path).history("EURUSD", "M5", 0)
    assert len(bars) == 2
    assert bars[0].close == pytest.approx(1.1005)
    assert bars[1].ts.hour == 0 and bars[1].ts.minute == 5
    assert bars[-1].ts.tzinfo is not None


def test_csv_feed_accepts_a_time_column_and_naive_timestamps(tmp_path):
    path = tmp_path / "GBPUSD_M5.csv"
    path.write_text(
        "time,open,high,low,close\n2026-01-05 00:00:00,1.3,1.31,1.29,1.305\n",
        encoding="utf-8",
    )
    bars = CsvFeed(tmp_path).history("GBPUSD", "M5", 0)
    assert bars[0].ts.tzinfo is not None
    assert bars[0].volume == 0.0


def test_csv_feed_reports_a_bad_row_with_its_line_number(tmp_path):
    path = tmp_path / "EURUSD_M5.csv"
    path.write_text("ts,open,high,low,close\n2026-01-05T00:00:00Z,1.1,oops,1.0,1.05\n", "utf-8")
    with pytest.raises(ValueError, match=":2:"):
        CsvFeed(tmp_path).history("EURUSD", "M5", 0)


def test_csv_feed_requires_a_timestamp_column(tmp_path):
    path = tmp_path / "EURUSD_M5.csv"
    path.write_text("open,high,low,close\n1.1,1.2,1.0,1.15\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no timestamp column"):
        CsvFeed(tmp_path).history("EURUSD", "M5", 0)


def test_csv_feed_missing_file_names_the_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="EURUSD"):
        CsvFeed(tmp_path).history("EURUSD", "M5", 0)
