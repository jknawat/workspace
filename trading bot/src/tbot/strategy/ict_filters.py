"""Entry gates built on MetaTrader 5's SMC/ICT structure snapshot.

These are ordinary :class:`~tbot.strategy.filters.Filter` objects, so they can
gate *any* strategy. Declaring them under ``[filters.…]`` on a symbol that runs
``ema_pullback`` turns a mechanical crossover system into one that only fires
when structure agrees; declaring them on ``ict_confluence`` tightens a system
that is already structure-driven. That is deliberate — the choice between
"trade ICT" and "use ICT as a filter" stays a config decision, not a rewrite.

**Every gate here fails closed.** No snapshot, a stale one, a disabled concept,
a missing record — all of them reject. A structure gate that passes when it has
no data is worse than no gate at all, because it silently converts "I don't
know" into "go ahead".

**State strings are configurable.** The snapshot contract fixes the *concepts*
but leaves each record's ``state`` as free text (``FRESH``, ``MITIGATED``,
``SWEPT``, …) that a library version may extend. Filters that care about state
match whole lower-case *tokens* from config rather than hardcoding vocabulary —
token matching, not substring, because ``"swept"`` is a substring of
``"UNSWEPT"`. Run ``tbot snapshot --symbol X --concept Y`` to see the exact
strings your library version emits before relying on one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..core.types import Decision, Side
from ..data.snapshot import BIAS_CONCEPTS, Record, Snapshot
from .base import BarContext
from .filters import Filter, register

ZONE_DEFAULTS = ["ORDER_BLOCK", "FVG"]


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _snapshot(ctx: BarContext) -> tuple[Snapshot | None, Decision]:
    """Fetch the snapshot, or the rejection that stands in for it."""
    if ctx.snapshot is None:
        return None, Decision.no(
            "no fresh MT5 structure snapshot (export EA stopped, stale, or disabled)"
        )
    return ctx.snapshot, Decision.ok("snapshot present")


def _state_tokens(state: str) -> set[str]:
    """Split a state string into lower-case word tokens.

    Token matching rather than substring matching, because ``"swept"`` is a
    substring of ``"UNSWEPT"`` — a plain ``in`` test would let an untouched
    liquidity pool satisfy a "must have been swept" gate, which is precisely
    backwards.
    """
    token = ""
    tokens: set[str] = set()
    for ch in state.lower():
        if ch.isalnum():
            token += ch
        elif token:
            tokens.add(token)
            token = ""
    if token:
        tokens.add(token)
    return tokens


def _state_matches(record: Record, wanted: list[str]) -> bool:
    """Empty ``wanted`` accepts any state; otherwise match a whole token."""
    if not wanted:
        return True
    tokens = _state_tokens(record.state)
    full = record.state.strip().lower()
    return any(w.lower() in tokens or w.lower() == full for w in wanted)


def _within_age(record: Record, ctx: BarContext, max_age_minutes: float) -> bool:
    if max_age_minutes <= 0:
        return True
    return record.age(ctx.now) <= timedelta(minutes=max_age_minutes)


def _points(ctx: BarContext, value: float) -> float:
    """Convert a point count to a price distance for this symbol."""
    return value * ctx.spec.point


def _concepts_ready(snapshot: Snapshot, concepts: list[str]) -> list[str]:
    return [c for c in concepts if not snapshot.concept_ready(c)]


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


@register
class IctSnapshotFilter(Filter):
    """Require a usable snapshot, and optionally that named concepts are ready.

    Use this as the first gate on any ICT-dependent symbol: it turns "MT5 is not
    publishing" into one clear rejection reason instead of several confusing
    ones further down the chain.
    """

    name = "ict_snapshot"
    defaults: dict[str, Any] = {"concepts": []}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        missing = _concepts_ready(snapshot, list(self.opt["concepts"]))
        if missing:
            return Decision.no(
                f"concept(s) not ready: {', '.join(missing)}",
                status=snapshot.status,
                problems=snapshot.problems(),
            )
        return Decision.ok(
            "snapshot usable", status=snapshot.status, records=len(snapshot.records)
        )


@register
class IctBiasFilter(Filter):
    """Trade only with the most recent structural event (BOS / CHoCH / MSS / …).

    Neutral is rejected by default: no confirmed structure is not permission,
    it is absence of evidence.
    """

    name = "ict_bias"
    defaults: dict[str, Any] = {"concepts": sorted(BIAS_CONCEPTS), "allow_neutral": False}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        concepts = list(self.opt["concepts"])
        bias = snapshot.bias(*concepts)
        wanted = "bullish" if side is Side.LONG else "bearish"
        if bias == wanted:
            return Decision.ok(f"structure bias {bias}", bias=bias)
        if bias == "neutral" and self.opt["allow_neutral"]:
            return Decision.ok("no structural bias, permitted by config", bias=bias)
        return Decision.no(f"structure bias {bias}, wanted {wanted}", bias=bias)


@register
class IctKillzoneFilter(Filter):
    """Trade only inside an active killzone published by MT5.

    Killzone windows come from the terminal's own session config, so this stays
    correct across DST without a second timetable to maintain. ``names`` matches
    case-insensitive substrings of the record's id or reason ("london",
    "new york"); empty accepts any killzone.
    """

    name = "ict_killzone"
    defaults: dict[str, Any] = {"names": []}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        if not snapshot.concept_ready("KILL_ZONE"):
            return Decision.no("KILL_ZONE concept not ready")

        wanted = [n.lower() for n in self.opt["names"]]
        open_zones: list[str] = []
        for record in snapshot.by_concept("KILL_ZONE"):
            label = f"{record.id} {record.reason}".lower()
            if wanted and not any(n in label for n in wanted):
                continue
            if record.period_start and ctx.now < record.period_start:
                continue
            if record.period_end and ctx.now > record.period_end:
                continue
            open_zones.append(record.id)

        if not open_zones:
            names = ", ".join(self.opt["names"]) or "any"
            return Decision.no(f"outside killzone ({names}) at {ctx.now:%a %H:%M} UTC")
        return Decision.ok(f"inside killzone {open_zones[0]}", killzones=open_zones)


@register
class IctZoneFilter(Filter):
    """Require price to be trading inside a directional zone.

    The zone is what gives an ICT entry its stop: an order block or fair-value
    gap agreeing with the trade direction, which price has come back into. The
    bar's whole range is tested, not just its close, because a wick into the
    zone is the usual entry trigger.
    """

    name = "ict_zone"
    defaults: dict[str, Any] = {
        "concepts": list(ZONE_DEFAULTS),
        "tolerance_points": 0.0,
        "states": [],
        "max_age_minutes": 0.0,
        "min_strength": 0.0,
        "require_direction": True,
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        matches = zones_touching(ctx, snapshot, side, self.opt)
        if not matches:
            return Decision.no(
                f"price {ctx.bar.close:.5f} is not in a {side.value} "
                f"{'/'.join(self.opt['concepts'])} zone"
            )
        best = matches[0]
        return Decision.ok(
            f"inside {best.concept} {best.id}",
            zone_id=best.id,
            zone_concept=best.concept,
            zone_lower=best.lower,
            zone_upper=best.upper,
        )


@register
class IctLiquiditySweptFilter(Filter):
    """Require liquidity to have been taken on the *opposite* side, recently.

    The classic sequence: price runs the stops below an equal-lows cluster, then
    reverses upward.

    ``direction`` says how to match the record's label to the trade:

    * ``agree`` (default) — a long wants a bullish-labelled pool, which is the
      convention where an equal-lows cluster is labelled by the move that
      follows its sweep;
    * ``oppose`` — use if your library labels pools by which side they sit on;
    * ``any`` — ignore the label and accept either.

    Check your own data with ``tbot snapshot --symbol X --concept LIQUIDITY``
    before trusting the default; label conventions differ between versions.
    """

    name = "ict_liquidity_swept"
    defaults: dict[str, Any] = {
        "states": ["swept", "taken"],
        "max_age_minutes": 240.0,
        "direction": "agree",  # agree | oppose | any
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        if not snapshot.concept_ready("LIQUIDITY"):
            return Decision.no("LIQUIDITY concept not ready")

        mode = str(self.opt["direction"]).lower()
        wanted = side if mode == "agree" else side.opposite
        states = list(self.opt["states"])
        for record in snapshot.by_concept("LIQUIDITY", active_only=False):
            if mode != "any" and not record.agrees_with(wanted.value):
                continue
            if not _state_matches(record, states):
                continue
            if not _within_age(record, ctx, float(self.opt["max_age_minutes"])):
                continue
            return Decision.ok(
                f"liquidity {record.id} {record.state}",
                liquidity_id=record.id,
                level=record.reference_price,
            )
        return Decision.no(
            f"no {'sell' if side is Side.LONG else 'buy'}-side liquidity taken "
            f"in the last {self.opt['max_age_minutes']:.0f} min"
        )


@register
class IctPremiumDiscountFilter(Filter):
    """Buy in discount, sell in premium.

    Equilibrium is the midpoint of the published PREMIUM_DISCOUNT range. The
    contract does not fix that record's state vocabulary, so only its geometry
    is used here -- which is the definition anyway.
    """

    name = "ict_premium_discount"
    defaults: dict[str, Any] = {"tolerance_points": 0.0}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        record = snapshot.latest("PREMIUM_DISCOUNT")
        if record is None:
            return Decision.no("no PREMIUM_DISCOUNT range published")
        if record.height <= 0:
            return Decision.no("PREMIUM_DISCOUNT range has no height")

        equilibrium = record.mid
        tolerance = _points(ctx, float(self.opt["tolerance_points"]))
        price = ctx.bar.close
        in_discount = price <= equilibrium + tolerance
        in_premium = price >= equilibrium - tolerance
        ok = in_discount if side is Side.LONG else in_premium
        where = "discount" if price < equilibrium else "premium"
        if not ok:
            return Decision.no(
                f"price {price:.5f} is in {where}, equilibrium {equilibrium:.5f}",
                equilibrium=equilibrium,
            )
        return Decision.ok(f"price in {where}", equilibrium=equilibrium)


@register
class IctNoOpposingZoneFilter(Filter):
    """Reject when an opposing zone blocks the path to target.

    Buying straight into an unmitigated bearish order block is how an otherwise
    good setup gets stopped at break-even. ``distance_points`` is how far ahead
    to look.
    """

    name = "ict_no_opposing_zone"
    defaults: dict[str, Any] = {
        "concepts": list(ZONE_DEFAULTS),
        "distance_points": 200.0,
        "states": [],
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        snapshot, why = _snapshot(ctx)
        if snapshot is None:
            return why
        price = ctx.bar.close
        reach = _points(ctx, float(self.opt["distance_points"]))
        opposite = side.opposite
        states = list(self.opt["states"])

        for record in snapshot.by_concept(*self.opt["concepts"]):
            if not record.agrees_with(opposite.value):
                continue
            if not _state_matches(record, states):
                continue
            ahead = record.lower - price if side is Side.LONG else price - record.upper
            if 0 <= ahead <= reach:
                return Decision.no(
                    f"opposing {record.concept} {record.id} {ahead / ctx.spec.point:.0f}pts ahead",
                    blocker=record.id,
                )
        return Decision.ok("path to target is clear")


# --------------------------------------------------------------------------- #
# Zone selection, shared with the ict_confluence strategy
# --------------------------------------------------------------------------- #


def zones_touching(
    ctx: BarContext, snapshot: Snapshot, side: Side, options: dict[str, Any]
) -> list[Record]:
    """Directional zones whose range the current bar traded into.

    Sorted by proximity of the bar's close to the zone midpoint, so the most
    relevant zone comes first. Shared by :class:`IctZoneFilter` and the
    ``ict_confluence`` strategy so both agree on what "in a zone" means.
    """
    tolerance = _points(ctx, float(options.get("tolerance_points", 0.0)))
    states = list(options.get("states", []))
    max_age = float(options.get("max_age_minutes", 0.0))
    min_strength = float(options.get("min_strength", 0.0))
    require_direction = bool(options.get("require_direction", True))
    concepts = list(options.get("concepts", ZONE_DEFAULTS))

    bar = ctx.bar
    out: list[Record] = []
    for record in snapshot.by_concept(*concepts):
        if require_direction and not record.agrees_with(side.value):
            continue
        if not _state_matches(record, states):
            continue
        if not _within_age(record, ctx, max_age):
            continue
        if record.strength < min_strength:
            continue
        # The bar's range must overlap the zone: a wick into it counts.
        if bar.low - tolerance > record.upper or bar.high + tolerance < record.lower:
            continue
        out.append(record)

    out.sort(key=lambda r: abs(r.mid - bar.close))
    return out
