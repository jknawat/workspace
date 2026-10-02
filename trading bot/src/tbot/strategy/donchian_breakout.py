"""Donchian channel breakout -- a deliberately simple second strategy.

Its purpose is architectural: it proves the engine, risk, broker and journal
layers are strategy-agnostic. Swapping ``strategy = "donchian"`` in a symbol's
TOML file is the entire change needed to trade a different model on that
symbol, with no engine edits.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.indicators import Series, atr, ema, slope_degrees
from ..core.types import Bar, Phase, Side, Signal
from .base import BarContext, Strategy, register
from .filters import build_chain


@register
class DonchianBreakout(Strategy):
    name = "donchian"

    defaults: ClassVar[dict[str, Any]] = {
        "channel_period": 20,
        "atr_period": 14,
        "ema_trend": 200,
        "slope_lookback": 5,
        "sl_atr": 2.0,
        "tp_atr": 4.0,
        "cooldown_bars": 5,
    }

    def __init__(self, cfg, spec) -> None:
        super().__init__(cfg, spec)
        self.filters = build_chain(cfg.filters, min_votes=getattr(cfg, 'min_votes', 0))
        self.reset()

    def reset(self) -> None:
        self.phase: Phase = Phase.SCANNING
        self.cooldown_until = -1
        self.last_reject = ""

    @property
    def warmup(self) -> int:
        return max(
            int(self.p("channel_period")),
            int(self.p("atr_period")),
            int(self.p("ema_trend")),
        ) + int(self.p("slope_lookback")) + 2

    def compute(self, bars: list[Bar]) -> dict[str, Series]:
        n = int(self.p("channel_period"))
        upper: Series = [None] * len(bars)
        lower: Series = [None] * len(bars)
        # Channel excludes the current bar, so a breakout compares this bar's
        # close against a level that was already known when it opened.
        for i in range(n, len(bars)):
            window = bars[i - n : i]
            upper[i] = max(b.high for b in window)
            lower[i] = min(b.low for b in window)
        closes = [b.close for b in bars]
        out: dict[str, Series] = {
            "upper": upper,
            "lower": lower,
            "atr": atr(bars, int(self.p("atr_period"))),
            "ema_trend": ema(closes, int(self.p("ema_trend"))),
        }
        out["slope"] = slope_degrees(
            out["ema_trend"], int(self.p("slope_lookback")), self.spec.point
        )
        return out

    def state_summary(self) -> dict[str, Any]:
        return {"phase": self.phase.value, "last_reject": self.last_reject}

    def on_bar(self, ctx: BarContext) -> Signal | None:
        if ctx.i < self.warmup or not ctx.ready("atr", "upper", "lower"):
            return None
        if self.phase is Phase.COOLDOWN:
            if ctx.i < self.cooldown_until:
                return None
            self.phase = Phase.SCANNING

        close = ctx.bar.close
        side: Side | None = None
        if close > ctx.require("upper"):
            side = Side.LONG
        elif close < ctx.require("lower"):
            side = Side.SHORT
        if side is None or side not in self.sides:
            return None

        decision = self.filters.evaluate(ctx, side)
        if not decision:
            self.last_reject = decision.reason
            return None

        a = ctx.require("atr")
        sl = close - float(self.p("sl_atr")) * a * side.sign
        tp = close + float(self.p("tp_atr")) * a * side.sign
        self.phase = Phase.COOLDOWN
        self.cooldown_until = ctx.i + int(self.p("cooldown_bars"))
        return Signal(
            symbol=ctx.symbol,
            side=side,
            ts=ctx.now,
            price=round(close, self.spec.digits),
            sl=round(sl, self.spec.digits),
            tp=round(tp, self.spec.digits),
            strategy=self.name,
            reason=f"{int(self.p('channel_period'))}-bar channel breakout",
            meta={"atr": a, "bar_index": ctx.i},
        )
