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
        unknown = set(options) - set(self.defaults)
        if unknown:
            raise ConfigError(
                f"filter {self.name!r}: unknown option(s) {sorted(unknown)}; "
                f"known: {sorted(self.defaults)}"
            )
        self.opt = {**self.defaults, **options}

    @abstractmethod
    def check(self, ctx: BarContext, side: Side) -> Decision: ...

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{self.name} {self.opt}>"


_REGISTRY: dict[str, type[Filter]] = {}


def register(cls: type[Filter]) -> type[Filter]:
    _REGISTRY[cls.name] = cls
    return cls


def build_chain(spec: dict[str, dict[str, Any]]) -> FilterChain:
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
    return FilterChain(filters)


class FilterChain:
    """Evaluates every filter and reports the first failure, with the full trace."""

    def __init__(self, filters: list[Filter]) -> None:
        self.filters = filters

    def __len__(self) -> int:
        return len(self.filters)

    def evaluate(self, ctx: BarContext, side: Side) -> Decision:
        trace: dict[str, Any] = {}
        for f in self.filters:
            d = f.check(ctx, side)
            trace[f.name] = {"passed": d.passed, "reason": d.reason, **d.detail}
            if not d.passed:
                return Decision.no(f"{f.name}: {d.reason}", trace=trace)
        return Decision.ok("all filters passed", trace=trace)


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
