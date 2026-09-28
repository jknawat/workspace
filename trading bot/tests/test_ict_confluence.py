"""The ict_confluence entry model.

Structure picks the direction, a zone gives the entry and the stop, liquidity
gives the target. These tests pin the behaviour that is easy to get quietly
wrong: failing closed without structure, not re-entering the same zone every
bar, and refusing stops that would blow the position size up.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import bars_from_closes

from tbot.config.models import ConfigError, SymbolConfig
from tbot.core.types import Phase, Side, Signal
from tbot.data.snapshot import Snapshot
from tbot.strategy import create
from tbot.strategy.base import BarContext

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_eurusd_m5.json"
START = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)

# ob-001 in the fixture: bullish ORDER_BLOCK spanning 1.10500 - 1.10700.
ZONE_LOWER, ZONE_UPPER = 1.1050, 1.1070


def raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def snap(d: dict | None = None) -> Snapshot:
    return Snapshot.parse(d if d is not None else raw())


def ict_cfg(**params) -> SymbolConfig:
    merged = {
        "atr_period": 3,
        "confirmation": "none",
        "sl_buffer_atr": 0.5,
        "min_sl_atr": 0.1,
        "max_sl_atr": 20.0,
        "tp_rr": 2.0,
        "cooldown_bars": 2,
        "zone_tolerance_points": 0.0,
    }
    merged.update(params)
    return SymbolConfig(
        symbol="EURUSD", strategy="ict_confluence", sides=("LONG",),
        params=merged, filters={},
    )


def approach_zone(n_before: int = 8) -> list[float]:
    """Drift down from above the block, then trade inside it on the last bars."""
    return [1.1090] * n_before + [1.1080, 1.1072, 1.1060, 1.1062]


def run(cfg: SymbolConfig, spec, closes: list[float], snapshot: Snapshot | None):
    """Feed a strategy bar by bar; return (strategy, [(index, signal)])."""
    strategy = create(cfg, spec)
    bars = bars_from_closes(closes, wick=0.0003, start=START)
    ind = strategy.compute(bars)
    out: list[tuple[int, Signal]] = []
    for i in range(len(bars)):
        ctx = BarContext(
            cfg=cfg, spec=spec, bars=bars, i=i, ind=ind, snapshot=snapshot
        )
        signal = strategy.on_bar(ctx)
        if signal is not None:
            out.append((i, signal))
    return strategy, out


# --------------------------------------------------------------------------- #
# Failing closed
# --------------------------------------------------------------------------- #


def test_no_snapshot_means_no_trades(spec_eurusd):
    """The whole model is structure; without it there is no opinion at all."""
    _, signals = run(ict_cfg(), spec_eurusd, approach_zone(), snapshot=None)
    assert signals == []


def test_losing_the_snapshot_while_armed_resets_to_scanning(spec_eurusd):
    cfg = ict_cfg(confirmation="candle", confirm_max_bars=5)
    strategy = create(cfg, spec_eurusd)
    bars = bars_from_closes([1.1090] * 8 + [1.1072, 1.1058], wick=0.0003, start=START)
    ind = strategy.compute(bars)

    def step(i: int, snapshot: Snapshot | None):
        return strategy.on_bar(
            BarContext(cfg=cfg, spec=spec_eurusd, bars=bars, i=i, ind=ind, snapshot=snapshot)
        )

    for i in range(len(bars) - 1):
        step(i, snap())
    assert strategy.phase in {Phase.ARMED, Phase.SCANNING, Phase.COOLDOWN}

    strategy.phase = Phase.ARMED  # whatever it reached, prove the reset path
    assert step(len(bars) - 1, None) is None
    assert strategy.phase is Phase.SCANNING


# --------------------------------------------------------------------------- #
# The entry itself
# --------------------------------------------------------------------------- #


def test_price_entering_a_bullish_zone_produces_a_long(spec_eurusd):
    _, signals = run(ict_cfg(), spec_eurusd, approach_zone(), snap())
    assert signals, "price traded into a bullish order block with bullish bias"
    _, signal = signals[0]
    assert signal.side is Side.LONG
    assert signal.strategy == "ict_confluence"
    assert signal.meta["zone_id"] == "ob-001"
    assert signal.meta["zone_concept"] == "ORDER_BLOCK"


def test_the_stop_sits_below_the_zone_not_at_an_atr_distance(spec_eurusd):
    """The defining property of this strategy: structure sets the stop."""
    _, signals = run(ict_cfg(sl_buffer_atr=0.5), spec_eurusd, approach_zone(), snap())
    _, signal = signals[0]
    buffer = 0.5 * signal.meta["atr"]
    assert signal.sl == pytest.approx(ZONE_LOWER - buffer, abs=1e-5)
    assert signal.sl < ZONE_LOWER


def test_the_target_is_an_r_multiple_of_that_stop(spec_eurusd):
    _, signals = run(ict_cfg(tp_rr=3.0), spec_eurusd, approach_zone(), snap())
    _, signal = signals[0]
    assert signal.rr == pytest.approx(3.0, rel=0.01)
    assert signal.meta["target"] == "rr"


def test_bias_gates_the_direction(spec_eurusd):
    """The fixture's newest structural event is bullish, so shorts never arm."""
    cfg = dataclasses.replace(ict_cfg(), sides=("SHORT",))
    _, signals = run(cfg, spec_eurusd, approach_zone(), snap())
    assert signals == []


def test_bias_can_be_switched_off(spec_eurusd):
    """Without the bias gate, a bearish-labelled zone can be traded short."""
    d = raw()
    for record in d["records"]:
        if record["id"] == "ob-001":
            record["direction"] = "bearish"
    cfg = dataclasses.replace(
        ict_cfg(require_bias=False), sides=("SHORT",)
    )
    _, signals = run(cfg, spec_eurusd, approach_zone(), snap(d))
    assert signals and signals[0][1].side is Side.SHORT


def test_a_zone_price_never_reaches_is_not_traded(spec_eurusd):
    _, signals = run(ict_cfg(), spec_eurusd, [1.1200] * 12, snap())
    assert signals == []


# --------------------------------------------------------------------------- #
# One entry per zone — the bug this model invites
# --------------------------------------------------------------------------- #


def test_a_zone_is_traded_once_not_on_every_bar(spec_eurusd):
    """An order block stays active for many bars; without memory the bot
    re-enters the same setup until the zone finally breaks."""
    closes = [1.1090] * 8 + [1.1060] * 20
    _, signals = run(ict_cfg(cooldown_bars=0), spec_eurusd, closes, snap())
    assert len(signals) == 1
    zone_ids = [s.meta["zone_id"] for _, s in signals]
    assert zone_ids == ["ob-001"]


def test_repeat_entries_are_possible_when_the_guard_is_disabled(spec_eurusd):
    closes = [1.1090] * 8 + [1.1060] * 20
    _, signals = run(
        ict_cfg(one_entry_per_zone=False, cooldown_bars=0), spec_eurusd, closes, snap()
    )
    assert len(signals) > 1


def test_cooldown_spaces_entries(spec_eurusd):
    closes = [1.1090] * 8 + [1.1060] * 30
    _, signals = run(
        ict_cfg(one_entry_per_zone=False, cooldown_bars=5), spec_eurusd, closes, snap()
    )
    gaps = [b - a for (a, _), (b, _) in zip(signals, signals[1:])]
    assert all(g >= 5 for g in gaps), gaps


# --------------------------------------------------------------------------- #
# Stop sanity bounds
# --------------------------------------------------------------------------- #


def test_a_stop_far_beyond_the_bounds_is_refused(spec_eurusd):
    """A tall zone relative to ATR would mean an enormous stop; refuse it."""
    _, signals = run(ict_cfg(max_sl_atr=0.2), spec_eurusd, approach_zone(), snap())
    assert signals == []


def test_a_stop_below_the_minimum_is_refused(spec_eurusd):
    _, signals = run(ict_cfg(min_sl_atr=50.0), spec_eurusd, approach_zone(), snap())
    assert signals == []


def test_the_refusal_reason_is_recorded(spec_eurusd):
    strategy, _ = run(ict_cfg(max_sl_atr=0.2), spec_eurusd, approach_zone(), snap())
    assert "outside" in strategy.last_reject


# --------------------------------------------------------------------------- #
# Confirmation modes
# --------------------------------------------------------------------------- #


def test_candle_confirmation_waits_for_a_directional_close(spec_eurusd):
    """Entry into the zone on a falling bar does not confirm; the next up bar does."""
    cfg = ict_cfg(confirmation="candle", confirm_max_bars=4)
    closes = [1.1090] * 8 + [1.1060, 1.1058, 1.1065]
    _, signals = run(cfg, spec_eurusd, closes, snap())
    assert signals
    entry_index = signals[0][0]
    assert entry_index == len(closes) - 1  # the rising bar, not the falling one


def test_candle_confirmation_expires(spec_eurusd):
    cfg = ict_cfg(confirmation="candle", confirm_max_bars=1)
    closes = [1.1090] * 8 + [1.1062, 1.1061, 1.1060, 1.1059, 1.1058]
    _, signals = run(cfg, spec_eurusd, closes, snap())
    assert signals == []


def test_a_close_through_the_zone_invalidates_the_setup(spec_eurusd):
    cfg = ict_cfg(confirmation="candle", confirm_max_bars=10)
    closes = [1.1090] * 8 + [1.1060, 1.1030, 1.1035]
    strategy, signals = run(cfg, spec_eurusd, closes, snap())
    assert signals == []
    assert any(
        "close through zone" in t.get("reason", "") for t in strategy.transitions
    )


def test_structure_confirmation_accepts_an_event_confirmed_since_arming(spec_eurusd):
    """The fixture's BOS confirmed at 11:40; bars starting 10:00 arm before that."""
    cfg = ict_cfg(confirmation="structure", confirm_max_bars=40)
    closes = [1.1090] * 8 + [1.1060] * 30
    _, signals = run(cfg, spec_eurusd, closes, snap())
    assert signals, "the BOS confirmed later in the session should confirm the setup"
    assert "structure BOS" in signals[0][1].reason


# --------------------------------------------------------------------------- #
# Liquidity targets
# --------------------------------------------------------------------------- #


def with_liquidity_above(level: float) -> dict:
    d = raw()
    d["records"].append(
        {
            "id": "liq-above", "concept": "LIQUIDITY",
            "source_time": "2026-09-18T09:00:00",
            "confirmed_at": "2026-09-18T09:05:00",
            "updated_at": "2026-09-18T09:05:00",
            "direction": "bearish", "lower": level, "upper": level,
            "state": "UNSWEPT", "active": True, "related_ids": [],
            "period_start": None, "period_end": None,
            "reference_price": level, "comparison_price": 0, "strength": 2.0,
            "reason": "Equal highs",
        }
    )
    return d


def test_liquidity_target_aims_at_the_next_pool_above(spec_eurusd):
    cfg = ict_cfg(target="liquidity", liquidity_min_rr=0.5)
    _, signals = run(cfg, spec_eurusd, approach_zone(), snap(with_liquidity_above(1.1150)))
    assert signals
    signal = signals[0][1]
    assert signal.meta["target"] == "liquidity"
    assert signal.tp == pytest.approx(1.1150, abs=1e-5)


def test_liquidity_target_falls_back_when_the_pool_is_too_close(spec_eurusd):
    cfg = ict_cfg(target="liquidity", liquidity_min_rr=5.0, tp_rr=2.0)
    _, signals = run(cfg, spec_eurusd, approach_zone(), snap(with_liquidity_above(1.1075)))
    signal = signals[0][1]
    assert signal.meta["target"].startswith("rr")
    assert signal.rr == pytest.approx(2.0, rel=0.01)


def test_liquidity_target_falls_back_when_nothing_is_ahead(spec_eurusd):
    cfg = ict_cfg(target="liquidity")
    _, signals = run(cfg, spec_eurusd, approach_zone(), snap())
    signal = signals[0][1]
    assert signal.meta["target"].startswith("rr")


# --------------------------------------------------------------------------- #
# Filters, metadata and configuration
# --------------------------------------------------------------------------- #


def test_declared_filters_still_gate_the_entry(spec_eurusd):
    cfg = dataclasses.replace(ict_cfg(), filters={"ict_killzone": {"names": ["tokyo"]}})
    _, signals = run(cfg, spec_eurusd, approach_zone(), snap())
    assert signals == []


def test_signal_metadata_explains_the_trade(spec_eurusd):
    _, signals = run(ict_cfg(), spec_eurusd, approach_zone(), snap())
    meta = signals[0][1].meta
    assert meta["zone_state"] == "FRESH"
    assert meta["bias"] == "bullish"
    assert meta["snapshot_as_of"].startswith("2026-09-18T12:00")


def test_state_summary_reports_the_phase(spec_eurusd):
    strategy, _ = run(ict_cfg(), spec_eurusd, approach_zone(), snap())
    summary = strategy.state_summary()
    assert summary["phase"] in {p.value for p in Phase}
    assert summary["traded_zones"] == 1


def test_an_invalid_confirmation_mode_is_rejected(spec_eurusd):
    with pytest.raises(ConfigError, match="confirmation"):
        create(ict_cfg(confirmation="vibes"), spec_eurusd)


def test_an_invalid_target_is_rejected(spec_eurusd):
    with pytest.raises(ConfigError, match="target"):
        create(ict_cfg(target="hope"), spec_eurusd)


def test_an_unknown_param_is_rejected(spec_eurusd):
    with pytest.raises(ConfigError, match="unknown param"):
        create(ict_cfg(zone_conceptz=["FVG"]), spec_eurusd)


def test_warmup_covers_the_atr_period(spec_eurusd):
    assert create(ict_cfg(atr_period=14), spec_eurusd).warmup >= 14


def test_structure_confirmation_ignores_events_older_than_the_setup(spec_eurusd):
    """A break of structure from before price reached the zone confirms nothing."""
    d = raw()
    for record in d["records"]:
        if record["id"] == "bos-001":
            record["confirmed_at"] = "2026-09-18T09:00:00"  # before the first bar
    cfg = ict_cfg(confirmation="structure", confirm_max_bars=40)
    closes = [1.1090] * 8 + [1.1060] * 10
    _, signals = run(cfg, spec_eurusd, closes, snap(d))
    assert signals == []
