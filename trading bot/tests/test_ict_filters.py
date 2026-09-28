"""ICT gates built on the MT5 structure snapshot.

The single most important property here is that **every gate fails closed**.
A structure filter that passes when it has no data silently converts "I don't
know" into "go ahead", which is how a bot ends up trading blind after the
terminal quietly stopped exporting.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import bars_from_closes

from tbot.config.models import ConfigError
from tbot.core.types import Side
from tbot.data.snapshot import Snapshot
from tbot.strategy.base import BarContext
from tbot.strategy.filters import build_chain

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot_eurusd_m5.json"
# The fixture's structure was evaluated at 12:00 on this day, broker == UTC.
NOW = datetime(2026, 9, 18, 11, 30, tzinfo=timezone.utc)


def raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def snapshot(**changes) -> Snapshot:
    d = raw()
    d.update(changes)
    return Snapshot.parse(d)


def context(
    symbol_cfg,
    spec,
    *,
    closes: list[float] | None = None,
    snap: Snapshot | None = None,
    start: datetime = NOW,
) -> BarContext:
    """A context whose last bar sits at ``start`` + n bars, with structure attached."""
    prices = closes if closes is not None else [1.1060, 1.1062, 1.1061, 1.1065]
    bars = bars_from_closes(prices, wick=0.0003, start=start)
    return BarContext(
        cfg=symbol_cfg,
        spec=spec,
        bars=bars,
        i=len(bars) - 1,
        ind={"atr": [0.0010] * len(bars)},
        snapshot=snap if snap is not None else Snapshot.parse(raw()),
    )


# --------------------------------------------------------------------------- #
# Failing closed
# --------------------------------------------------------------------------- #

ALL_GATES = [
    ("ict_snapshot", {}),
    ("ict_bias", {}),
    ("ict_killzone", {}),
    ("ict_zone", {}),
    ("ict_liquidity_swept", {}),
    ("ict_premium_discount", {}),
    ("ict_no_opposing_zone", {}),
]


@pytest.mark.parametrize("name,options", ALL_GATES)
def test_every_gate_rejects_when_no_snapshot_is_available(name, options, symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    ctx.snapshot = None
    decision = build_chain({name: options}).evaluate(ctx, Side.LONG)
    assert not decision, f"{name} passed with no structure data"


def test_snapshot_gate_names_the_likely_cause(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    ctx.snapshot = None
    decision = build_chain({"ict_snapshot": {}}).evaluate(ctx, Side.LONG)
    assert "export EA" in decision.reason


# --------------------------------------------------------------------------- #
# ict_snapshot
# --------------------------------------------------------------------------- #


def test_snapshot_gate_passes_on_a_ready_snapshot(symbol_cfg, spec_eurusd):
    chain = build_chain({"ict_snapshot": {"concepts": ["ORDER_BLOCK", "FVG"]}})
    assert chain.evaluate(context(symbol_cfg, spec_eurusd), Side.LONG)


def test_snapshot_gate_rejects_a_disabled_concept(symbol_cfg, spec_eurusd):
    """SMT is DISABLED in the fixture: switched off is not agreement."""
    chain = build_chain({"ict_snapshot": {"concepts": ["SMT"]}})
    decision = chain.evaluate(context(symbol_cfg, spec_eurusd), Side.LONG)
    assert not decision and "SMT" in decision.reason


def test_snapshot_gate_accepts_a_partial_concept(symbol_cfg, spec_eurusd):
    chain = build_chain({"ict_snapshot": {"concepts": ["LIQUIDITY"]}})
    assert chain.evaluate(context(symbol_cfg, spec_eurusd), Side.LONG)


# --------------------------------------------------------------------------- #
# ict_bias
# --------------------------------------------------------------------------- #


def test_bias_follows_the_newest_structural_event(symbol_cfg, spec_eurusd):
    """BOS (bullish, 11:40) is newer than MSS (bearish, 11:05)."""
    ctx = context(symbol_cfg, spec_eurusd)
    chain = build_chain({"ict_bias": {}})
    assert chain.evaluate(ctx, Side.LONG)
    assert not chain.evaluate(ctx, Side.SHORT)


def test_bias_can_be_scoped_to_chosen_concepts(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    chain = build_chain({"ict_bias": {"concepts": ["MSS"]}})
    assert chain.evaluate(ctx, Side.SHORT)
    assert not chain.evaluate(ctx, Side.LONG)


def test_neutral_bias_is_rejected_by_default(symbol_cfg, spec_eurusd):
    d = raw()
    d["records"] = [r for r in d["records"] if r["concept"] not in {"BOS", "MSS"}]
    ctx = context(symbol_cfg, spec_eurusd, snap=Snapshot.parse(d))
    decision = build_chain({"ict_bias": {}}).evaluate(ctx, Side.LONG)
    assert not decision and "neutral" in decision.reason


def test_neutral_bias_can_be_permitted(symbol_cfg, spec_eurusd):
    d = raw()
    d["records"] = [r for r in d["records"] if r["concept"] not in {"BOS", "MSS"}]
    ctx = context(symbol_cfg, spec_eurusd, snap=Snapshot.parse(d))
    assert build_chain({"ict_bias": {"allow_neutral": True}}).evaluate(ctx, Side.LONG)


# --------------------------------------------------------------------------- #
# ict_killzone
# --------------------------------------------------------------------------- #


def test_killzone_gate_passes_inside_the_published_window(symbol_cfg, spec_eurusd):
    """The fixture's London killzone runs 07:00-16:00; the bar is at 11:45."""
    assert build_chain({"ict_killzone": {}}).evaluate(
        context(symbol_cfg, spec_eurusd), Side.LONG
    )


def test_killzone_gate_rejects_outside_the_window(symbol_cfg, spec_eurusd):
    late = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    ctx = context(symbol_cfg, spec_eurusd, start=late)
    decision = build_chain({"ict_killzone": {}}).evaluate(ctx, Side.LONG)
    assert not decision and "outside killzone" in decision.reason


def test_killzone_names_are_matched_case_insensitively(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    assert build_chain({"ict_killzone": {"names": ["LONDON"]}}).evaluate(ctx, Side.LONG)
    assert not build_chain({"ict_killzone": {"names": ["tokyo"]}}).evaluate(ctx, Side.LONG)


# --------------------------------------------------------------------------- #
# ict_zone
# --------------------------------------------------------------------------- #


def test_zone_gate_passes_when_price_is_inside_a_matching_zone(symbol_cfg, spec_eurusd):
    """ob-001 is bullish, 1.10500-1.10700; the bars trade at ~1.1060."""
    decision = build_chain({"ict_zone": {}}).evaluate(
        context(symbol_cfg, spec_eurusd), Side.LONG
    )
    assert decision
    assert decision.detail["zone_id"] == "ob-001"


def test_zone_gate_rejects_price_outside_every_zone(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd, closes=[1.2000, 1.2001, 1.2002])
    assert not build_chain({"ict_zone": {}}).evaluate(ctx, Side.LONG)


def test_zone_gate_is_direction_aware(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    assert not build_chain({"ict_zone": {}}).evaluate(ctx, Side.SHORT)


def test_zone_gate_counts_a_wick_into_the_zone(symbol_cfg, spec_eurusd):
    """Closes sit above the block; only the low reaches into it."""
    ctx = context(symbol_cfg, spec_eurusd, closes=[1.1073, 1.1072, 1.10715])
    ctx.bars[-1] = dataclasses.replace(ctx.bars[-1], low=1.1068)
    assert build_chain({"ict_zone": {}}).evaluate(ctx, Side.LONG)


def test_zone_tolerance_admits_a_near_miss(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd, closes=[1.1075, 1.1076, 1.1075])
    assert not build_chain({"ict_zone": {}}).evaluate(ctx, Side.LONG)
    assert build_chain({"ict_zone": {"tolerance_points": 100.0}}).evaluate(ctx, Side.LONG)


def test_zone_gate_can_require_a_state(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    assert build_chain({"ict_zone": {"states": ["fresh"]}}).evaluate(ctx, Side.LONG)
    assert not build_chain({"ict_zone": {"states": ["mitigated"]}}).evaluate(ctx, Side.LONG)


def test_zone_gate_can_require_a_minimum_strength(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd)
    assert build_chain({"ict_zone": {"min_strength": 2.0}}).evaluate(ctx, Side.LONG)
    assert not build_chain({"ict_zone": {"min_strength": 9.0}}).evaluate(ctx, Side.LONG)


def test_zone_gate_can_require_recency(symbol_cfg, spec_eurusd):
    """ob-001 last updated 11:55; the bars run from 11:30."""
    ctx = context(symbol_cfg, spec_eurusd, start=NOW + timedelta(hours=6))
    assert not build_chain({"ict_zone": {"max_age_minutes": 60.0}}).evaluate(ctx, Side.LONG)


def test_zone_gate_ignores_inactive_zones(symbol_cfg, spec_eurusd):
    """fvg-002 is BROKEN and inactive; price inside it must not qualify."""
    ctx = context(symbol_cfg, spec_eurusd, closes=[1.1102, 1.1103, 1.1102])
    assert not build_chain({"ict_zone": {"concepts": ["FVG"]}}).evaluate(ctx, Side.SHORT)


# --------------------------------------------------------------------------- #
# ict_liquidity_swept
# --------------------------------------------------------------------------- #


def swept_snapshot(state: str = "SWEPT", direction: str = "bullish") -> Snapshot:
    d = raw()
    for record in d["records"]:
        if record["concept"] == "LIQUIDITY":
            record["state"] = state
            record["direction"] = direction
    return Snapshot.parse(d)


def test_liquidity_gate_requires_a_swept_pool(symbol_cfg, spec_eurusd):
    unswept = context(symbol_cfg, spec_eurusd)  # fixture state is UNSWEPT
    assert not build_chain({"ict_liquidity_swept": {}}).evaluate(unswept, Side.LONG)

    swept = context(symbol_cfg, spec_eurusd, snap=swept_snapshot())
    assert build_chain({"ict_liquidity_swept": {}}).evaluate(swept, Side.LONG)


def test_state_match_accepts_a_compound_state_token(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd, snap=swept_snapshot(state="SWEPT_CONFIRMED"))
    assert build_chain({"ict_liquidity_swept": {"states": ["swept"]}}).evaluate(ctx, Side.LONG)


def test_unswept_does_not_satisfy_a_swept_requirement(symbol_cfg, spec_eurusd):
    """Token matching, not substring: 'swept' is inside 'UNSWEPT'.

    With a naive ``in`` test an untouched liquidity pool would satisfy a
    "must have been swept" gate — exactly backwards, and silently so.
    """
    ctx = context(symbol_cfg, spec_eurusd, snap=swept_snapshot(state="UNSWEPT"))
    assert not build_chain({"ict_liquidity_swept": {"states": ["swept"]}}).evaluate(
        ctx, Side.LONG
    )


def test_liquidity_direction_convention_is_configurable(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd, snap=swept_snapshot(direction="bearish"))
    assert not build_chain({"ict_liquidity_swept": {}}).evaluate(ctx, Side.LONG)
    assert build_chain({"ict_liquidity_swept": {"direction": "oppose"}}).evaluate(ctx, Side.LONG)
    assert build_chain({"ict_liquidity_swept": {"direction": "any"}}).evaluate(ctx, Side.LONG)


def test_liquidity_gate_rejects_a_stale_sweep(symbol_cfg, spec_eurusd):
    ctx = context(symbol_cfg, spec_eurusd, snap=swept_snapshot(), start=NOW + timedelta(days=1))
    assert not build_chain({"ict_liquidity_swept": {"max_age_minutes": 60.0}}).evaluate(
        ctx, Side.LONG
    )


# --------------------------------------------------------------------------- #
# ict_premium_discount
# --------------------------------------------------------------------------- #


def with_range(lower: float, upper: float) -> Snapshot:
    d = raw()
    d["records"].append(
        {
            "id": "pd-001", "concept": "PREMIUM_DISCOUNT",
            "source_time": "2026-09-18T09:00:00",
            "confirmed_at": "2026-09-18T09:00:00",
            "updated_at": "2026-09-18T11:55:00",
            "direction": "neutral", "lower": lower, "upper": upper,
            "state": "ACTIVE", "active": True, "related_ids": [],
            "period_start": None, "period_end": None,
            "reference_price": 0, "comparison_price": 0, "strength": 0, "reason": "dealing range",
        }
    )
    return Snapshot.parse(d)


def test_longs_are_allowed_only_in_discount(symbol_cfg, spec_eurusd):
    # Range 1.1000-1.1200, equilibrium 1.1100; price ~1.1060 is in discount.
    ctx = context(symbol_cfg, spec_eurusd, snap=with_range(1.1000, 1.1200))
    chain = build_chain({"ict_premium_discount": {}})
    assert chain.evaluate(ctx, Side.LONG)
    assert not chain.evaluate(ctx, Side.SHORT)


def test_shorts_are_allowed_only_in_premium(symbol_cfg, spec_eurusd):
    # Range 1.0900-1.1100, equilibrium 1.1000; price ~1.1060 is in premium.
    ctx = context(symbol_cfg, spec_eurusd, snap=with_range(1.0900, 1.1100))
    chain = build_chain({"ict_premium_discount": {}})
    assert chain.evaluate(ctx, Side.SHORT)
    assert not chain.evaluate(ctx, Side.LONG)


def test_premium_discount_rejects_when_no_range_is_published(symbol_cfg, spec_eurusd):
    decision = build_chain({"ict_premium_discount": {}}).evaluate(
        context(symbol_cfg, spec_eurusd), Side.LONG
    )
    assert not decision and "no PREMIUM_DISCOUNT" in decision.reason


# --------------------------------------------------------------------------- #
# ict_no_opposing_zone
# --------------------------------------------------------------------------- #


def test_opposing_zone_ahead_blocks_the_trade(symbol_cfg, spec_eurusd):
    """A bearish FVG at 1.1100-1.1105 sits above price ~1.1060."""
    d = raw()
    for record in d["records"]:
        if record["id"] == "fvg-002":
            record["active"] = True  # revive the bearish gap above price
    ctx = context(symbol_cfg, spec_eurusd, snap=Snapshot.parse(d))
    decision = build_chain(
        {"ict_no_opposing_zone": {"distance_points": 1000.0}}
    ).evaluate(ctx, Side.LONG)
    assert not decision and "fvg-002" in decision.reason


def test_an_opposing_zone_beyond_reach_is_ignored(symbol_cfg, spec_eurusd):
    d = raw()
    for record in d["records"]:
        if record["id"] == "fvg-002":
            record["active"] = True
    ctx = context(symbol_cfg, spec_eurusd, snap=Snapshot.parse(d))
    assert build_chain({"ict_no_opposing_zone": {"distance_points": 50.0}}).evaluate(
        ctx, Side.LONG
    )


def test_clear_path_passes(symbol_cfg, spec_eurusd):
    assert build_chain({"ict_no_opposing_zone": {}}).evaluate(
        context(symbol_cfg, spec_eurusd), Side.LONG
    )


# --------------------------------------------------------------------------- #
# Configuration errors
# --------------------------------------------------------------------------- #


def test_unknown_option_on_an_ict_filter_is_rejected():
    with pytest.raises(ConfigError, match="unknown option"):
        build_chain({"ict_zone": {"conceptz": ["FVG"]}})
