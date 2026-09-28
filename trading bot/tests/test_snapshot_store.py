"""Reading snapshots off disk: paths, caching, and failing closed."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbot.data.snapshot import SnapshotError
from tbot.data.snapshot_store import SnapshotStore, sanitise_symbol

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_eurusd_m5.json"
AS_OF = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path) -> SnapshotStore:
    (tmp_path / "EURUSD_M5.json").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return SnapshotStore(directory=tmp_path, timeframe="M5")


def rewrite(path: Path, payload: dict, *, bump_mtime: float = 10.0) -> None:
    """Rewrite a snapshot and move its mtime forward deterministically."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = path.stat().st_mtime + bump_mtime
    os.utime(path, (stamp, stamp))


# --------------------------------------------------------------------------- #
# Filenames
# --------------------------------------------------------------------------- #


def test_plain_symbols_are_unchanged():
    assert sanitise_symbol("EURUSD") == "EURUSD"
    assert sanitise_symbol("EURUSD.pro") == "EURUSD.pro"
    assert sanitise_symbol("US30-cash") == "US30-cash"


def test_broker_suffixes_are_hex_encoded_like_the_exporting_ea():
    """Brokers use '/', '#', ':' and spaces; those would become path separators."""
    assert sanitise_symbol("EUR/USD") == "EUR_002fUSD"
    assert sanitise_symbol("XAUUSD#") == "XAUUSD_0023"
    assert sanitise_symbol("US 30") == "US_002030"


def test_empty_symbol_falls_back_to_the_ea_default():
    assert sanitise_symbol("") == "symbol"


def test_path_follows_the_symbol_and_timeframe(tmp_path):
    s = SnapshotStore(directory=tmp_path, timeframe="M5")
    assert s.path_for("EURUSD").name == "EURUSD_M5.json"
    assert s.path_for("EURUSD", "H1").name == "EURUSD_H1.json"
    # Case is preserved: the broker's own symbol name is what the EA writes.
    assert s.path_for("eurusd").name == "eurusd_M5.json"


def test_discover_ignores_lock_files(tmp_path):
    (tmp_path / "EURUSD_M5.json").write_text("{}", encoding="utf-8")
    (tmp_path / "EURUSD_M5.json.lock").write_text("", encoding="utf-8")
    assert [p.name for p in SnapshotStore(directory=tmp_path).discover()] == ["EURUSD_M5.json"]


def test_discover_is_empty_when_the_folder_does_not_exist(tmp_path):
    assert SnapshotStore(directory=tmp_path / "nope").discover() == []


# --------------------------------------------------------------------------- #
# Loading and caching
# --------------------------------------------------------------------------- #


def test_loads_a_snapshot(store):
    snapshot = store.load("EURUSD")
    assert snapshot.symbol == "EURUSD"
    assert snapshot.source_path.endswith("EURUSD_M5.json")


def test_unchanged_file_is_not_reparsed(store):
    assert store.load("EURUSD") is store.load("EURUSD")


def test_republished_file_is_reparsed(store, tmp_path):
    first = store.load("EURUSD")
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["as_of"] = "2026-09-18T12:05:00"
    rewrite(tmp_path / "EURUSD_M5.json", payload)
    second = store.load("EURUSD")
    assert second is not first
    assert second.as_of == AS_OF + timedelta(minutes=5)


def test_missing_file_names_the_likely_cause(store):
    with pytest.raises(SnapshotError, match="SMC_Snapshot_Export"):
        store.load("GBPUSD")


def test_get_swallows_the_error_and_returns_none(store):
    assert store.get("GBPUSD") is None


def test_get_reports_a_malformed_file_as_none(tmp_path):
    (tmp_path / "EURUSD_M5.json").write_text('{"schema_version": "9.0"}', encoding="utf-8")
    assert SnapshotStore(directory=tmp_path).get("EURUSD") is None


def test_broker_offset_is_applied_to_loaded_snapshots(tmp_path):
    (tmp_path / "EURUSD_M5.json").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    s = SnapshotStore(directory=tmp_path, broker_utc_offset_hours=3.0)
    assert s.load("EURUSD").as_of == AS_OF - timedelta(hours=3)


# --------------------------------------------------------------------------- #
# Freshness — the gate trading code actually calls
# --------------------------------------------------------------------------- #


def test_default_max_age_is_three_bars_of_the_timeframe():
    assert SnapshotStore(directory=".", timeframe="M5").max_age == timedelta(minutes=15)
    assert SnapshotStore(directory=".", timeframe="H1").max_age == timedelta(minutes=180)


def test_explicit_max_age_wins():
    s = SnapshotStore(directory=".", timeframe="M5", max_age=timedelta(minutes=90))
    assert s.max_age == timedelta(minutes=90)


def test_fresh_returns_the_snapshot_within_the_age_limit(store):
    assert store.fresh("EURUSD", AS_OF + timedelta(minutes=10)) is not None


def test_fresh_returns_none_once_stale(store):
    """A stale snapshot is worse than none: authoritative-looking, and wrong."""
    assert store.fresh("EURUSD", AS_OF + timedelta(hours=2)) is None


def test_fresh_returns_none_when_the_snapshot_is_not_ready(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["status"] = "NOT_READY"
    (tmp_path / "EURUSD_M5.json").write_text(json.dumps(payload), encoding="utf-8")
    s = SnapshotStore(directory=tmp_path, timeframe="M5")
    assert s.fresh("EURUSD", AS_OF) is None


def test_partial_snapshots_are_still_usable(tmp_path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["status"] = "PARTIAL"
    (tmp_path / "EURUSD_M5.json").write_text(json.dumps(payload), encoding="utf-8")
    s = SnapshotStore(directory=tmp_path, timeframe="M5")
    assert s.fresh("EURUSD", AS_OF) is not None


def test_fresh_returns_none_when_the_file_is_absent(store):
    assert store.fresh("GBPUSD", AS_OF) is None


# --------------------------------------------------------------------------- #
# Settings resolution
# --------------------------------------------------------------------------- #


def test_from_settings_appends_the_export_folder(tmp_path):
    (tmp_path / "SMC_Export").mkdir()
    s = SnapshotStore.from_settings(
        folder="SMC_Export", common_path=str(tmp_path), timeframe="M15"
    )
    assert s.directory == tmp_path / "SMC_Export"
    assert s.timeframe == "M15"


def test_from_settings_accepts_the_common_folder_above_files(tmp_path):
    (tmp_path / "Files" / "SMC_Export").mkdir(parents=True)
    s = SnapshotStore.from_settings(folder="SMC_Export", common_path=str(tmp_path))
    assert s.directory == tmp_path / "Files" / "SMC_Export"


def test_status_line_reports_a_missing_export(store):
    assert "MISSING" in store.status_line("GBPUSD")


def test_status_line_summarises_a_present_export(store):
    line = store.status_line("EURUSD", AS_OF + timedelta(minutes=1))
    assert "READY" in line and "bias=bullish" in line and "active_records=6" in line
