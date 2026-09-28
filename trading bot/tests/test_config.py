"""Configuration validation.

A typo in a strategy parameter must be a loud startup error, never a silently
ignored key. That is the whole reason params are declared rather than scraped.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from tbot.config.loader import load_config, load_symbol_configs
from tbot.config.models import ConfigError, EngineConfig, RiskConfig, SessionConfig, SymbolConfig

BOT_TOML = """
[engine]
mode = "backtest"
broker = "paper"
timeframe = "M5"
start_balance = 20000.0

[risk]
risk_per_trade_pct = 2.0
max_open_positions = 3

[log]
level = "WARNING"
file = ""
"""

EURUSD_TOML = """
symbol = "eurusd"
strategy = "ema_pullback"
weight = 3.0
sides = ["LONG", "SHORT"]

[session]
start = "07:00"
end = "16:00"

[params]
ema_fast = 9

[filters.atr_range]
min = 0.0002
"""

XAUUSD_TOML = """
symbol = "XAUUSD"
strategy = "donchian"
weight = 1.0
enabled = false
"""


@pytest.fixture
def config_dir(tmp_path):
    (tmp_path / "symbols").mkdir()
    (tmp_path / "bot.toml").write_text(BOT_TOML, encoding="utf-8")
    (tmp_path / "symbols" / "eurusd.toml").write_text(EURUSD_TOML, encoding="utf-8")
    (tmp_path / "symbols" / "xauusd.toml").write_text(XAUUSD_TOML, encoding="utf-8")
    return tmp_path


def test_loads_engine_risk_and_symbols(config_dir):
    cfg = load_config(config_dir / "bot.toml")
    assert cfg.engine.mode == "backtest"
    assert cfg.engine.start_balance == 20_000.0
    assert cfg.risk.risk_per_trade_pct == 2.0
    assert len(cfg.symbols) == 2
    assert cfg.symbol("EURUSD").session.start == time(7, 0)
    assert cfg.symbol("eurusd").sides == ("LONG", "SHORT")


def test_symbol_names_are_normalised_to_upper_case(config_dir):
    cfg = load_config(config_dir / "bot.toml")
    assert {s.symbol for s in cfg.symbols} == {"EURUSD", "XAUUSD"}


def test_disabled_symbols_are_excluded_but_still_listed(config_dir):
    cfg = load_config(config_dir / "bot.toml")
    assert [s.symbol for s in cfg.active_symbols] == ["EURUSD"]
    assert len(cfg.symbols) == 2


def test_weights_are_renormalised_across_enabled_symbols_only(config_dir):
    cfg = load_config(config_dir / "bot.toml")
    # XAUUSD is disabled, so EURUSD carries the full budget rather than 75% of it
    assert cfg.normalised_weights == {"EURUSD": pytest.approx(1.0)}


def test_unknown_engine_key_is_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        EngineConfig.from_dict({"mode": "paper", "timefrmae": "M5"})


def test_unknown_symbol_key_is_rejected():
    with pytest.raises(ConfigError, match="unknown key"):
        SymbolConfig.from_dict(
            {"symbol": "EURUSD", "strategy": "ema_pullback", "sesion": {}}, "test"
        )


def test_missing_required_symbol_key_is_rejected():
    with pytest.raises(ConfigError, match="missing required key"):
        SymbolConfig.from_dict({"symbol": "EURUSD"}, "test")


def test_invalid_side_is_rejected():
    with pytest.raises(ConfigError, match="LONG"):
        SymbolConfig.from_dict(
            {"symbol": "EURUSD", "strategy": "ema_pullback", "sides": ["UP"]}, "test"
        )


def test_live_mode_cannot_use_the_paper_broker():
    with pytest.raises(ConfigError, match="requires a real broker"):
        EngineConfig.from_dict({"mode": "live", "broker": "paper"})


def test_absurd_risk_is_rejected():
    with pytest.raises(ConfigError, match="risk_per_trade_pct"):
        RiskConfig.from_dict({"risk_per_trade_pct": 50.0})


def test_duplicate_symbol_files_are_rejected(tmp_path):
    d = tmp_path / "symbols"
    d.mkdir()
    for name in ("a.toml", "b.toml"):
        (d / name).write_text('symbol = "EURUSD"\nstrategy = "donchian"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicate symbol"):
        load_symbol_configs(d)


def test_missing_config_file_is_reported_clearly(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_session_window_matches_weekday_and_time():
    session = SessionConfig(start=time(7, 0), end=time(16, 0), weekdays=(0, 1, 2, 3, 4))
    monday_9am = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
    monday_6am = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
    assert session.contains(monday_9am)
    assert not session.contains(monday_6am)
    assert not session.contains(saturday)


def test_session_window_can_wrap_midnight():
    session = SessionConfig(start=time(22, 0), end=time(2, 0), weekdays=tuple(range(7)))
    assert session.contains(datetime(2026, 1, 5, 23, 30, tzinfo=timezone.utc))
    assert session.contains(datetime(2026, 1, 5, 1, 30, tzinfo=timezone.utc))
    assert not session.contains(datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc))


def test_env_override_changes_the_timeframe(config_dir, monkeypatch):
    monkeypatch.setenv("TBOT_TIMEFRAME", "H1")
    assert load_config(config_dir / "bot.toml").engine.timeframe == "H1"


# --------------------------------------------------------------------------- #
# [snapshot] — MT5 structure export
# --------------------------------------------------------------------------- #


def test_snapshot_defaults_to_disabled(config_dir):
    cfg = load_config(config_dir / "bot.toml")
    assert cfg.snapshot.enabled is False
    assert cfg.snapshot.folder == "SMC_Export"
    assert cfg.snapshot.timeframe == ""  # follows [engine].timeframe


def test_snapshot_section_is_loaded(config_dir):
    path = config_dir / "bot.toml"
    path.write_text(
        BOT_TOML
        + '\n[snapshot]\nenabled = true\nfolder = "Exports"\n'
          'timeframe = "M15"\nmax_age_minutes = 45.0\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.snapshot.enabled is True
    assert cfg.snapshot.folder == "Exports"
    assert cfg.snapshot.timeframe == "M15"
    assert cfg.snapshot.max_age_minutes == 45.0


def test_unknown_snapshot_key_is_rejected():
    from tbot.config.models import SnapshotConfig

    with pytest.raises(ConfigError, match="unknown key"):
        SnapshotConfig.from_dict({"enabled": True, "foldr": "x"})


def test_enabled_snapshot_needs_a_folder():
    from tbot.config.models import SnapshotConfig

    with pytest.raises(ConfigError, match="folder"):
        SnapshotConfig.from_dict({"enabled": True, "folder": ""})


def test_negative_snapshot_age_is_rejected():
    from tbot.config.models import SnapshotConfig

    with pytest.raises(ConfigError, match="max_age_minutes"):
        SnapshotConfig.from_dict({"max_age_minutes": -1.0})
