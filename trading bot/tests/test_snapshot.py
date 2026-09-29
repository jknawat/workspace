"""SMC/ICT snapshot contract: parsing, validation, queries and time basis.

This is a boundary with another program. Every field arrives from MetaTrader 5,
and a misread structure file would silently change what the bot trades — so the
parser is tested for what it *rejects* at least as hard as for what it accepts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbot.data.snapshot import Snapshot, SnapshotError

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_eurusd_m5.json"
AS_OF_BROKER = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)  # if offset were 0


def raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def load(offset: float = 0.0) -> Snapshot:
    return Snapshot.from_json(
        FIXTURE.read_text(encoding="utf-8"),
        broker_utc_offset_hours=offset,
        source_path=str(FIXTURE),
    )


def mutated(**changes) -> str:
    d = raw()
    d.update(changes)
    return json.dumps(d)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parses_the_header():
    s = load()
    assert (s.symbol, s.timeframe, s.status) == ("EURUSD", "M5", "READY")
    assert s.schema_version == "1.0"
    assert s.ready and s.usable
    assert len(s.records) == 7
    assert len(s.modules) == 7


def test_active_record_counts_by_concept():
    assert load().counts() == {
        "BOS": 1, "FVG": 1, "KILL_ZONE": 1, "LIQUIDITY": 1, "MSS": 1, "ORDER_BLOCK": 1
    }


def test_record_fields_are_typed():
    ob = load().by_concept("ORDER_BLOCK")[0]
    assert ob.id == "ob-001"
    assert ob.is_bullish and ob.active and ob.is_zone
    assert ob.lower == pytest.approx(1.1050)
    assert ob.upper == pytest.approx(1.1070)
    assert ob.mid == pytest.approx(1.1060)
    assert ob.height == pytest.approx(0.0020)
    assert ob.related_ids == ("bos-001",)
    assert ob.strength == pytest.approx(2.4)


# --------------------------------------------------------------------------- #
# Time basis — broker wall clock in, UTC out
# --------------------------------------------------------------------------- #


def test_timestamps_are_converted_from_broker_time_to_utc():
    """Snapshot times carry no zone; a broker on UTC+2 is two hours ahead."""
    s = load(offset=2.0)
    assert s.as_of == AS_OF_BROKER - timedelta(hours=2)
    assert s.as_of.tzinfo is timezone.utc
    assert s.as_of_broker == "2026-09-18T12:00:00"  # original preserved for display


def test_zero_offset_leaves_the_wall_clock_unchanged():
    assert load(offset=0.0).as_of == AS_OF_BROKER


def test_every_record_timestamp_is_timezone_aware():
    for r in load(offset=3.0).records:
        for value in (r.source_time, r.confirmed_at, r.updated_at):
            assert value.tzinfo is timezone.utc
        assert r.broker_times["updated_at"].endswith(":00")


def test_nullable_period_fields_survive():
    s = load()
    kz = s.by_concept("KILL_ZONE")[0]
    assert kz.period_start is not None and kz.period_end is not None
    assert s.by_concept("BOS")[0].period_start is None


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #


def test_by_concept_hides_inactive_records_by_default():
    s = load()
    assert [r.id for r in s.by_concept("FVG")] == ["fvg-001"]
    assert {r.id for r in s.by_concept("FVG", active_only=False)} == {"fvg-001", "fvg-002"}


def test_containing_finds_the_zone_around_a_price():
    s = load()
    hits = s.containing(1.1060, "ORDER_BLOCK")
    assert [r.id for r in hits] == ["ob-001"]
    assert s.containing(1.2000, "ORDER_BLOCK") == ()


def test_containing_sorts_by_proximity_to_the_zone_midpoint():
    s = load()
    hits = s.containing(1.1060)  # inside both the order block and the killzone
    assert [r.id for r in hits][:2] == ["ob-001", "kz-london"]


def test_containing_respects_a_tolerance():
    s = load()
    assert s.containing(1.1072, "ORDER_BLOCK") == ()
    assert [r.id for r in s.containing(1.1072, "ORDER_BLOCK", tolerance=0.0005)] == ["ob-001"]


def test_distance_to_is_zero_inside_and_signed_outside():
    ob = load().by_concept("ORDER_BLOCK")[0]
    assert ob.distance_to(1.1060) == 0.0
    assert ob.distance_to(1.1080) == pytest.approx(0.0010)
    assert ob.distance_to(1.1040) == pytest.approx(-0.0010)


def test_nearest_can_be_restricted_to_one_direction():
    s = load()
    assert s.nearest(1.1000, "FVG", side="LONG").id == "fvg-001"
    assert s.nearest(1.1000, "FVG", side="SHORT") is None  # the bearish one is inactive


def test_latest_picks_the_most_recently_updated():
    assert load().latest("FVG").id == "fvg-001"


def test_bias_comes_from_the_newest_structural_event():
    """BOS at 11:40 is newer than MSS at 11:05, so the read is bullish."""
    assert load().bias() == "bullish"
    assert load().bias("MSS") == "bearish"


def test_bias_counts_inactive_structural_events():
    """BOS and CHOCH arrive with active=false on every record.

    Measured against a live MetaQuotes export: 11 BOS and 13 CHOCH, none
    active, because the library treats a break of structure as an event rather
    than a living zone. Filtering them out made bias() return neutral forever,
    so a strategy configured with bias_concepts = ["BOS", "CHOCH"] would never
    have taken a trade -- silently.
    """
    d = raw()
    for record in d["records"]:
        if record["concept"] in {"BOS", "MSS"}:
            record["active"] = False
    s = Snapshot.parse(d)
    assert s.by_concept("BOS") == ()          # nothing active, as in real data
    assert s.bias("BOS") == "bullish"         # ...but the event still counts
    assert s.bias() == "bullish"


def test_bias_is_neutral_when_nothing_structural_is_present():
    d = raw()
    d["records"] = [r for r in d["records"] if r["concept"] not in {"BOS", "MSS"}]
    assert Snapshot.parse(d).bias() == "neutral"


def test_agrees_with_maps_sides_to_directions():
    s = load()
    ob = s.by_concept("ORDER_BLOCK")[0]
    kz = s.by_concept("KILL_ZONE")[0]
    assert ob.agrees_with("LONG") and not ob.agrees_with("SHORT")
    assert not kz.agrees_with("LONG") and not kz.agrees_with("SHORT")  # neutral agrees with neither


# --------------------------------------------------------------------------- #
# Module readiness and freshness
# --------------------------------------------------------------------------- #


def test_disabled_concept_is_not_treated_as_ready():
    s = load()
    assert s.module("SMT").status == "DISABLED"
    assert s.concept_ready("SMT") is False


def test_partial_concept_is_usable():
    s = load()
    assert s.concept_ready("LIQUIDITY") is True
    assert s.module("LIQUIDITY").truncated is True


def test_unknown_concept_is_not_assumed_ready():
    assert load().concept_ready("PO3") is False


def test_problems_reports_truncation_and_failures():
    problems = " ".join(load().problems())
    assert "LIQUIDITY truncated" in problems


def test_problems_reports_a_degraded_snapshot():
    s = Snapshot.from_json(mutated(status="PARTIAL", message="history warming up"))
    assert s.usable and not s.ready
    assert "history warming up" in " ".join(s.problems())


def test_staleness_uses_as_of():
    s = load()
    assert not s.is_stale(AS_OF_BROKER + timedelta(minutes=10), timedelta(minutes=15))
    assert s.is_stale(AS_OF_BROKER + timedelta(minutes=20), timedelta(minutes=15))


def test_missing_as_of_counts_as_stale():
    s = Snapshot.from_json(mutated(as_of=None, status="NOT_READY"))
    assert s.as_of is None
    assert s.is_stale(AS_OF_BROKER, timedelta(days=365))


# --------------------------------------------------------------------------- #
# Rejection — the important half
# --------------------------------------------------------------------------- #


def test_rejects_a_future_major_schema_version():
    with pytest.raises(SnapshotError, match="schema_version"):
        Snapshot.from_json(mutated(schema_version="2.0"))


def test_accepts_a_newer_minor_schema_version():
    assert Snapshot.from_json(mutated(schema_version="1.7")).schema_version == "1.7"


def test_rejects_a_non_broker_time_basis():
    with pytest.raises(SnapshotError, match="time_basis"):
        Snapshot.from_json(mutated(time_basis="utc"))


def test_rejects_a_missing_top_level_key():
    d = raw()
    del d["records"]
    with pytest.raises(SnapshotError, match="records"):
        Snapshot.parse(d)


def test_rejects_an_unknown_concept():
    d = raw()
    d["records"][0]["concept"] = "VIBES"
    with pytest.raises(SnapshotError, match="concept"):
        Snapshot.parse(d)


def test_rejects_an_unknown_status():
    with pytest.raises(SnapshotError, match="status"):
        Snapshot.from_json(mutated(status="FINE"))


def test_rejects_duplicate_record_ids():
    d = raw()
    d["records"][1]["id"] = d["records"][0]["id"]
    with pytest.raises(SnapshotError, match="duplicated"):
        Snapshot.parse(d)


def test_rejects_an_inverted_zone():
    d = raw()
    d["records"][0]["lower"] = 9.0
    with pytest.raises(SnapshotError, match="exceeds upper"):
        Snapshot.parse(d)


def test_rejects_a_timestamp_with_a_timezone_suffix():
    """Broker timestamps are wall clock. A 'Z' would mean someone changed the
    contract, and reading it as UTC would silently shift every level."""
    d = raw()
    d["records"][0]["updated_at"] = "2026-09-18T11:55:00Z"
    with pytest.raises(SnapshotError, match="broker timestamp"):
        Snapshot.parse(d)


def test_rejects_a_non_finite_number():
    text = FIXTURE.read_text(encoding="utf-8").replace('"strength": 2.4', '"strength": NaN')
    with pytest.raises(SnapshotError, match="non-finite"):
        Snapshot.from_json(text)


def test_rejects_invalid_json_with_the_path_in_the_message():
    with pytest.raises(SnapshotError, match="invalid JSON"):
        Snapshot.from_json("{not json", source_path="x.json")


def test_rejects_a_record_that_is_not_an_object():
    d = raw()
    d["records"][0] = "ob-001"
    with pytest.raises(SnapshotError, match="must be an object"):
        Snapshot.parse(d)


def test_rejects_a_non_boolean_active_flag():
    d = raw()
    d["records"][0]["active"] = "true"
    with pytest.raises(SnapshotError, match="active must be a boolean"):
        Snapshot.parse(d)
