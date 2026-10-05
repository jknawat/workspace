"""Composable entry filters.

Each filter is a tiny, independently testable object built from a config table.
A strategy declares *which* filters it wants in TOML; adding a filter is a
config edit, not a new branch inside a 3,000-line method. Every filter returns
a :class:`Decision` carrying the numbers it judged on, so a rejected signal is
always explainable after the fact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from itertools import pairwise
from typing import Any, ClassVar

from ..config.models import ConfigError
from ..core.types import Decision, Side
from .base import BarContext


class Filter(ABC):
    name: ClassVar[str] = "base"
    defaults: ClassVar[dict[str, Any]] = {}

    def __init__(self, **options: Any) -> None:
        # ``when`` is understood by every filter rather than declared per
        # subclass, so it never collides with a filter's own option names.
        self.when = str(options.pop("when", "both")).lower()
        if self.when not in ("both", "arm", "entry"):
            raise ConfigError(
                f"filter {self.name!r}: when={self.when!r} is not one of "
                "both|arm|entry"
            )
        # A veto filter kills the trade on its own. A voter only contributes
        # to a count. Default veto, so an existing config behaves identically.
        self.veto = bool(options.pop("veto", True))
        unknown = set(options) - set(self.defaults)
        if unknown:
            raise ConfigError(
                f"filter {self.name!r}: unknown option(s) {sorted(unknown)}; "
                f"known: {sorted(self.defaults)}"
            )
        self.opt = {**self.defaults, **options}

    @abstractmethod
    def check(self, ctx: BarContext, side: Side) -> Decision: ...

    def applies_at(self, stage: str) -> bool:
        return self.when == "both" or self.when == stage

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{self.name} {self.opt}>"


_REGISTRY: dict[str, type[Filter]] = {}


def register(cls: type[Filter]) -> type[Filter]:
    _REGISTRY[cls.name] = cls
    return cls


def build_chain(spec: dict[str, dict[str, Any]], min_votes: int = 0) -> FilterChain:
    filters: list[Filter] = []
    for name, options in spec.items():
        opts = dict(options)
        if not opts.pop("enabled", True):
            continue
        try:
            cls = _REGISTRY[name]
        except KeyError:
            raise ConfigError(
                f"unknown filter {name!r}; available: {sorted(_REGISTRY)}"
            ) from None
        filters.append(cls(**opts))
    return FilterChain(filters, min_votes=min_votes)


#: When a filter is consulted. A setup is *armed* when the entry condition
#: first appears, and *entered* when price finally triggers -- which on a
#: pullback strategy can be many bars later, at a materially different price.
#: A gate that measures where price is relative to a moving average therefore
#: answers a different question at each point.
STAGE_ARM = "arm"
STAGE_ENTRY = "entry"
STAGES = (STAGE_ARM, STAGE_ENTRY)


class FilterChain:
    """Evaluates every filter and reports the first failure, with the full trace."""

    def __init__(self, filters: list[Filter], min_votes: int = 0) -> None:
        self.filters = filters
        #: How many of the *voting* filters must pass. 0 means all of them,
        #: which is the same as having no voters at all -- the default, so a
        #: config that marks nothing as a voter behaves exactly as before.
        self.min_votes = min_votes

    def __len__(self) -> int:
        return len(self.filters)

    def evaluate(self, ctx: BarContext, side: Side, stage: str = "") -> Decision:
        """Check the chain. ``stage`` skips filters not configured for it.

        Two kinds of filter. A **veto** fails the trade on its own. A **voter**
        contributes to a count, and ``min_votes`` of them must pass.

        Vetoes are evaluated first and short-circuit, because the point of a
        veto is that no amount of agreement elsewhere buys past it: trading on
        a 2000-point spread loses money whatever the candles say.

        An empty stage checks everything, which keeps every existing caller and
        every backtest behaving as before.
        """
        trace: dict[str, Any] = {}
        voters: list[tuple[str, bool, str]] = []

        for f in self.filters:
            if stage and not f.applies_at(stage):
                continue
            d = f.check(ctx, side)
            trace[f.name] = {
                "passed": d.passed, "reason": d.reason, "veto": f.veto, **d.detail
            }
            if f.veto:
                if not d.passed:
                    return Decision.no(f"{f.name}: {d.reason}", trace=trace)
            else:
                voters.append((f.name, d.passed, d.reason))

        if not voters:
            return Decision.ok("all filters passed", trace=trace)

        passed = [name for name, ok, _ in voters if ok]
        needed = self.min_votes if self.min_votes > 0 else len(voters)
        if len(passed) < needed:
            objections = "; ".join(
                f"{name}: {why}" for name, ok, why in voters if not ok
            )
            return Decision.no(
                f"only {len(passed)} of {len(voters)} votes, need {needed} "
                f"({objections})",
                trace=trace,
                votes=len(passed), votes_needed=needed,
            )
        return Decision.ok(
            f"vetoes clear, {len(passed)} of {len(voters)} votes (need {needed})",
            trace=trace,
            votes=len(passed), votes_needed=needed,
        )


# --------------------------------------------------------------------------- #
# Concrete filters
# --------------------------------------------------------------------------- #


@register
class AtrRangeFilter(Filter):
    """Volatility band: too quiet means noise, too wild means the stop is huge."""

    name = "atr_range"
    defaults: ClassVar[dict[str, Any]] = {"min": 0.0, "max": float("inf"), "source": "atr"}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        v = ctx.value(self.opt["source"])
        if v is None:
            return Decision.no("atr not ready")
        if v < self.opt["min"]:
            return Decision.no(f"atr {v:.6f} below min {self.opt['min']}", atr=v)
        if v > self.opt["max"]:
            return Decision.no(f"atr {v:.6f} above max {self.opt['max']}", atr=v)
        return Decision.ok("atr in range", atr=v)


@register
class EmaOrderFilter(Filter):
    """Require the EMA stack to be ordered with the trade direction."""

    name = "ema_order"
    defaults: ClassVar[dict[str, Any]] = {
        "series": ["ema_confirm", "ema_fast", "ema_medium", "ema_slow"]
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        names = list(self.opt["series"])
        raw = [ctx.value(n) for n in names]
        if any(v is None for v in raw):
            return Decision.no("ema stack not ready")
        vals: list[float] = [float(v) for v in raw]  # type: ignore[arg-type]
        pairs = list(pairwise(vals))
        if side is Side.LONG:
            ordered = all(a > b for a, b in pairs)
        else:
            ordered = all(a < b for a, b in pairs)
        detail = dict(zip(names, vals, strict=True))
        if not ordered:
            return Decision.no(f"ema stack not ordered for {side.value}", **detail)
        return Decision.ok("ema stack ordered", **detail)


@register
class PriceVsEmaFilter(Filter):
    """Trade only on the correct side of a slow trend EMA."""

    name = "price_vs_ema"
    defaults: ClassVar[dict[str, Any]] = {"series": "ema_trend"}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        ref = ctx.value(self.opt["series"])
        if ref is None:
            return Decision.no("trend ema not ready")
        close = ctx.bar.close
        ok = close > ref if side is Side.LONG else close < ref
        if not ok:
            return Decision.no(
                f"close {close:.5f} on wrong side of trend ema {ref:.5f}",
                close=close,
                ref=ref,
            )
        return Decision.ok("price aligned with trend", close=close, ref=ref)


@register
class AngleFilter(Filter):
    """Reject flat markets: the reference series must actually be sloping."""

    name = "angle"
    defaults: ClassVar[dict[str, Any]] = {"series": "slope", "min_degrees": 0.0}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        raw = ctx.value(self.opt["series"])
        if raw is None:
            return Decision.no("slope not ready")
        directional = raw * side.sign
        if directional < self.opt["min_degrees"]:
            return Decision.no(
                f"slope {directional:.2f} deg below min {self.opt['min_degrees']}",
                slope=directional,
            )
        return Decision.ok("slope sufficient", slope=directional)


@register
class CandleDirectionFilter(Filter):
    """Require the last N closed bars to agree with the trade direction."""

    name = "candle_direction"
    defaults: ClassVar[dict[str, Any]] = {"bars": 1, "offset": 0}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        n, off = int(self.opt["bars"]), int(self.opt["offset"])
        end = ctx.i - off
        if end - n + 1 < 0:
            return Decision.no("not enough history")
        window = ctx.bars[end - n + 1 : end + 1]
        if side is Side.LONG:
            agree = all(b.is_bullish for b in window)
        else:
            agree = all(b.is_bearish for b in window)
        if not agree:
            return Decision.no(f"last {n} candle(s) do not confirm {side.value}")
        return Decision.ok(f"last {n} candle(s) confirm {side.value}")


@register
class SessionFilter(Filter):
    """Trading-hours gate, evaluated in UTC against the symbol's session."""

    name = "session"
    defaults: ClassVar[dict[str, Any]] = {}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        session = ctx.cfg.session
        if not session.contains(ctx.now):
            return Decision.no(
                f"{ctx.now:%a %H:%M} UTC outside session "
                f"{session.start:%H:%M}-{session.end:%H:%M}"
            )
        return Decision.ok("within session")


@register
class SpreadFilter(Filter):
    """Live-only guard: a widened spread destroys a tight-stop edge."""

    name = "spread"
    defaults: ClassVar[dict[str, Any]] = {"max_points": 50.0}

    def check(self, ctx: BarContext, side: Side) -> Decision:
        if ctx.spread_points <= 0:  # backtest, or no quote available yet
            return Decision.ok("spread unknown, skipped")
        if ctx.spread_points > self.opt["max_points"]:
            return Decision.no(
                f"spread {ctx.spread_points:.0f}pts above max "
                f"{self.opt['max_points']:.0f}",
                spread=ctx.spread_points,
            )
        return Decision.ok("spread acceptable", spread=ctx.spread_points)


def available() -> list[str]:
    return sorted(_REGISTRY)


@register
class CandlePatternFilter(Filter):
    """Does the candle itself back this direction?

    The one input here that reads price *action* rather than an average of it.
    Everything else in the chain is derived from EMAs, ATR or the spread, all
    of which smooth away the shape of the bar the trade actually enters on.

    ``require`` decides how strict it is:

    * ``support``  -- at least one pattern must back this side (default)
    * ``no_oppose`` -- only fails when a pattern backs the *other* side, which
      lets a bar with no pattern through rather than treating "nothing to see"
      as a refusal
    * ``named``    -- one of ``patterns`` must be present and back this side

    Most bars show no pattern at all, so ``support`` as a veto would block
    almost everything. It is meant to be a voter.
    """

    name = "candles"
    defaults: ClassVar[dict[str, Any]] = {
        "require": "support",
        "patterns": (),
        "wick_ratio": 2.0,
        "doji_body": 0.1,
        "marubozu_body": 0.8,
        "opposite_wick": 0.35,
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        from .candles import detect, summarise

        mode = str(self.opt["require"])
        found = detect(
            ctx.bars, ctx.i,
            wick_ratio=float(self.opt["wick_ratio"]),
            doji_body=float(self.opt["doji_body"]),
            marubozu_body=float(self.opt["marubozu_body"]),
            opposite_wick=float(self.opt["opposite_wick"]),
        )
        note = summarise(found, side.value)
        supporting = [p for p in found if p.supports(side.value)]
        opposing = [
            p for p in found
            if p.side not in ("NEUTRAL", side.value.upper())
        ]

        if mode == "no_oppose":
            if opposing:
                return Decision.no(
                    f"{opposing[0].name} backs the other side", note=note
                )
            return Decision.ok(note or "nothing against it", note=note)

        if mode == "named":
            wanted = {str(p).lower() for p in self.opt["patterns"]}
            if not wanted:
                return Decision.no(
                    "require='named' with no patterns listed, so nothing can "
                    "ever match"
                )
            hit = [p for p in supporting if p.name in wanted]
            if not hit:
                return Decision.no(f"none of {sorted(wanted)} present", note=note)
            return Decision.ok(hit[0].note, note=note)

        if mode != "support":
            return Decision.no(
                f"require={mode!r} is not one of support|no_oppose|named"
            )
        if not supporting:
            return Decision.no(note or "no pattern backs this side", note=note)
        return Decision.ok(supporting[0].note, note=note)


@register
class SupportResistanceRoomFilter(Filter):
    """Is there room to reach the target, or is a level in the way?

    The strategy risks ``sl_atr`` to make ``tp_atr`` -- on gold, 3 ATR against
    7.5. That target only pays if price can actually travel the distance, and a
    swing high sitting two ATR above the entry is a concrete reason it might
    not: the market turned there before, and the orders that turned it may
    still be sitting there.

    ``min_room`` is the share of the target distance that must be clear. 1.0
    demands the whole way, which almost nothing will satisfy; 0.5 asks that the
    trade can at least reach halfway before meeting resistance.

    Nothing in the way is the best case, not a missing answer -- a signal with
    no level between it and its target passes.
    """

    name = "sr_room"
    defaults: ClassVar[dict[str, Any]] = {
        "min_room": 0.5,
        "left": 3,
        "right": 3,
        "lookback": 300,
        # Levels this close together are the same level seen twice; keeping
        # both would let one swing veto a trade it has already vetoed.
        "merge_atr": 0.25,
    }

    def check(self, ctx: BarContext, side: Side) -> Decision:
        from .levels import room_toward, swings

        atr = ctx.value("atr")
        if not atr:
            return Decision.no("atr not ready")

        # The target the strategy will ask for, from its own parameters --
        # the filter runs before the signal exists, so it cannot read tp.
        tp_atr = float(ctx.cfg.params.get("tp_atr", 0.0) or 0.0)
        if tp_atr <= 0:
            return Decision.ok("strategy has no atr target to protect")
        target = tp_atr * atr
        needed = float(self.opt["min_room"]) * target

        found = swings(
            ctx.bars, ctx.i,
            left=int(self.opt["left"]),
            right=int(self.opt["right"]),
            lookback=int(self.opt["lookback"]),
        )
        merge = float(self.opt["merge_atr"]) * atr
        price = ctx.bar.close
        # Drop levels within a hair of price: the bar that just closed is
        # often itself near a pivot, and that is not resistance to a move.
        found = [lv for lv in found if lv.distance_from(price) > merge]

        room = room_toward(found, price, side.value)
        if room is None:
            return Decision.ok("clear to target", room="unlimited")
        if room < needed:
            return Decision.no(
                f"only {room / atr:.1f} ATR of room, needs "
                f"{needed / atr:.1f} ({room / target:.0%} of target)",
                room_atr=round(room / atr, 2),
                needed_atr=round(needed / atr, 2),
            )
        return Decision.ok(
            f"{room / atr:.1f} ATR of room to the first level",
            room_atr=round(room / atr, 2),
        )
