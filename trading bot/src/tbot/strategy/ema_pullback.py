"""EMA crossover -> pullback -> breakout-window entry model.

This is the same *family* of idea as the classic MT5 "sunrise" strategies --
an EMA stack crossover, a pullback, then a breakout entry -- but implemented
once, driven entirely by config, and with the state machine made explicit
rather than inferred from scattered instance flags.

Lifecycle of one setup::

    SCANNING  --crossover + all filters pass-->  ARMED
    ARMED     --N counter-direction bars-------> WINDOW   (breakout level armed)
              --opposite crossover / timeout---> SCANNING (invalidated)
    WINDOW    --price breaks the level---------> signal, then COOLDOWN
              --price breaks the failure level-> SCANNING
              --window expires-----------------> SCANNING
    COOLDOWN  --n bars---------------------->    SCANNING

Every transition is recorded in ``self.transitions`` so a session can be
replayed and explained without adding print statements.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..core.indicators import Series, atr, crossed_above, crossed_below, ema, slope_degrees
from ..core.types import Bar, Phase, Side, Signal
from .base import BarContext, Strategy, register
from .filters import STAGE_ARM, STAGE_ENTRY, build_chain


@register
class EmaPullbackBreakout(Strategy):
    name = "ema_pullback"

    defaults: ClassVar[dict[str, Any]] = {
        # indicator periods
        "ema_confirm": 5,
        "ema_fast": 8,
        "ema_medium": 13,
        "ema_slow": 21,
        "ema_trend": 200,
        "atr_period": 14,
        "slope_source": "ema_medium",
        "slope_lookback": 5,
        # "point" or "atr". Use "atr" for anything that is not forex: with
        # point scaling, gold reads 89.8-89.9 degrees on every bar and the
        # angle filter silently passes everything.
        "slope_scale": "point",
        # entry model
        "use_pullback": True,
        "pullback_bars": 2,
        "pullback_max_wait": 10,
        "window_offset_atr": 0.25,
        "window_bars": 5,
        "invalidate_on_opposite_cross": True,
        # exits
        "sl_atr": 2.5,
        "tp_atr": 6.0,
        "cooldown_bars": 3,
    }

    def __init__(self, cfg, spec) -> None:
        super().__init__(cfg, spec)
        self.filters = build_chain(cfg.filters)
        self.transitions: list[dict[str, Any]] = []
        self.reset()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        self.phase: Phase = Phase.SCANNING
        self.side: Side | None = None
        self.armed_at: int | None = None
        self.pullback_count = 0
        self.pullback_extreme: float | None = None
        self.trigger: float | None = None
        self.failure_level: float | None = None
        self.window_expires_at: int | None = None
        self.cooldown_until: int = -1
        self.last_reject: str = ""

    @property
    def warmup(self) -> int:
        periods = [
            int(self.p("ema_confirm")),
            int(self.p("ema_fast")),
            int(self.p("ema_medium")),
            int(self.p("ema_slow")),
            int(self.p("ema_trend")),
            int(self.p("atr_period")),
        ]
        return max(periods) + int(self.p("slope_lookback")) + 2

    def compute(self, bars: list[Bar]) -> dict[str, Series]:
        closes = [b.close for b in bars]
        out: dict[str, Series] = {
            "ema_confirm": ema(closes, int(self.p("ema_confirm"))),
            "ema_fast": ema(closes, int(self.p("ema_fast"))),
            "ema_medium": ema(closes, int(self.p("ema_medium"))),
            "ema_slow": ema(closes, int(self.p("ema_slow"))),
            "ema_trend": ema(closes, int(self.p("ema_trend"))),
            "atr": atr(bars, int(self.p("atr_period"))),
        }
        # Scale the angle by ATR or by point. "atr" makes 45 degrees mean "one
        # ATR per bar" on any instrument; "point" only behaves on forex, and
        # pins gold at ~90 degrees on every bar (see slope_degrees).
        scale = out["atr"] if str(self.p("slope_scale")) == "atr" else self.spec.point
        out["slope"] = slope_degrees(
            out[str(self.p("slope_source"))],
            int(self.p("slope_lookback")),
            scale,
        )
        return out

    def state_summary(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "side": self.side.value if self.side else None,
            "pullback_count": self.pullback_count,
            "trigger": self.trigger,
            "window_expires_at": self.window_expires_at,
            "last_reject": self.last_reject,
        }

    # ------------------------------------------------------------------ #
    # Bar handling
    # ------------------------------------------------------------------ #

    def on_bar(self, ctx: BarContext) -> Signal | None:
        if ctx.i < self.warmup or not ctx.ready("atr", "ema_confirm", "ema_fast"):
            return None

        if self.phase is Phase.COOLDOWN:
            if ctx.i >= self.cooldown_until:
                self._to(Phase.SCANNING, ctx, "cooldown elapsed")
            else:
                return None

        if self.phase is Phase.SCANNING:
            return self._scan(ctx)
        if self.phase is Phase.ARMED:
            return self._armed(ctx)
        if self.phase is Phase.WINDOW:
            return self._window(ctx)
        return None

    # -- phase 1 -------------------------------------------------------- #

    def _scan(self, ctx: BarContext) -> Signal | None:
        side = self._crossover_side(ctx)
        if side is None or side not in self.sides:
            return None

        decision = self.filters.evaluate(ctx, side, stage=STAGE_ARM)
        if not decision:
            self.last_reject = decision.reason
            self._record(ctx, "rejected", side=side.value, reason=decision.reason)
            return None

        if not bool(self.p("use_pullback")):
            self._record(ctx, "entry_immediate", side=side.value)
            signal = self._make_signal(ctx, side, "crossover, no pullback required")
            self._enter_cooldown(ctx)
            return signal

        self.side = side
        self.armed_at = ctx.i
        self.pullback_count = 0
        self.pullback_extreme = ctx.bar.low if side is Side.LONG else ctx.bar.high
        self._to(Phase.ARMED, ctx, f"crossover {side.value}, filters passed")
        return None

    def _crossover_side(self, ctx: BarContext) -> Side | None:
        confirm, fast = ctx.ind["ema_confirm"], ctx.ind["ema_fast"]
        if crossed_above(confirm, fast, ctx.i):
            return Side.LONG
        if crossed_below(confirm, fast, ctx.i):
            return Side.SHORT
        return None

    # -- phase 2 -------------------------------------------------------- #

    def _armed(self, ctx: BarContext) -> Signal | None:
        assert self.side is not None and self.armed_at is not None
        bar = ctx.bar

        if bool(self.p("invalidate_on_opposite_cross")):
            opposite = self._crossover_side(ctx)
            if opposite is not None and opposite is not self.side:
                self._to(Phase.SCANNING, ctx, "opposite crossover invalidated setup")
                return None

        if ctx.i - self.armed_at > int(self.p("pullback_max_wait")):
            self._to(Phase.SCANNING, ctx, "pullback wait expired")
            return None

        counter = bar.is_bearish if self.side is Side.LONG else bar.is_bullish
        if counter:
            self.pullback_count += 1
            if self.side is Side.LONG:
                self.pullback_extreme = min(self.pullback_extreme or bar.low, bar.low)
            else:
                self.pullback_extreme = max(self.pullback_extreme or bar.high, bar.high)

        if self.pullback_count < int(self.p("pullback_bars")):
            return None

        offset = float(self.p("window_offset_atr")) * ctx.require("atr")
        if self.side is Side.LONG:
            self.trigger = bar.high + offset
            self.failure_level = self.pullback_extreme
        else:
            self.trigger = bar.low - offset
            self.failure_level = self.pullback_extreme
        self.window_expires_at = ctx.i + int(self.p("window_bars"))
        self._to(
            Phase.WINDOW,
            ctx,
            f"pullback complete ({self.pullback_count} bars), trigger {self.trigger:.5f}",
        )
        return None

    # -- phase 3 -------------------------------------------------------- #

    def _window(self, ctx: BarContext) -> Signal | None:
        assert self.side is not None and self.trigger is not None
        bar = ctx.bar

        broke_out = bar.high >= self.trigger if self.side is Side.LONG else bar.low <= self.trigger
        if broke_out:
            # Re-run the chain: session and spread can invalidate between arming
            # and the breakout, and those are exactly the gates that matter at
            # the moment an order would actually be sent.
            decision = self.filters.evaluate(ctx, self.side, stage=STAGE_ENTRY)
            if not decision:
                self.last_reject = decision.reason
                self._to(Phase.SCANNING, ctx, f"breakout blocked: {decision.reason}")
                return None
            side = self.side
            entry = (
                max(bar.close, self.trigger)
                if side is Side.LONG
                else min(bar.close, self.trigger)
            )
            # Build the signal before cooling down: _enter_cooldown clears the
            # pullback count that the signal reports in its metadata.
            signal = self._make_signal(ctx, side, "breakout of pullback window", price=entry)
            self._enter_cooldown(ctx)
            return signal

        if self.failure_level is not None:
            failed = (
                bar.low < self.failure_level
                if self.side is Side.LONG
                else bar.high > self.failure_level
            )
            if failed:
                self._to(Phase.SCANNING, ctx, "price broke the failure boundary")
                return None

        if self.window_expires_at is not None and ctx.i >= self.window_expires_at:
            self._to(Phase.SCANNING, ctx, "breakout window expired")
        return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _make_signal(
        self, ctx: BarContext, side: Side, reason: str, price: float | None = None
    ) -> Signal:
        a = ctx.require("atr")
        entry = price if price is not None else ctx.bar.close
        sl_dist = float(self.p("sl_atr")) * a
        tp_dist = float(self.p("tp_atr")) * a
        sl = entry - sl_dist * side.sign
        tp = entry + tp_dist * side.sign
        return Signal(
            symbol=ctx.symbol,
            side=side,
            ts=ctx.now,
            price=round(entry, self.spec.digits),
            sl=round(sl, self.spec.digits),
            tp=round(tp, self.spec.digits),
            strategy=self.name,
            reason=reason,
            meta={"atr": a, "pullback_count": self.pullback_count, "bar_index": ctx.i},
        )

    def _enter_cooldown(self, ctx: BarContext) -> None:
        self.cooldown_until = ctx.i + int(self.p("cooldown_bars"))
        self.phase = Phase.COOLDOWN
        self.side = None
        self.trigger = None
        self.failure_level = None
        self.window_expires_at = None
        self.pullback_count = 0

    def _to(self, phase: Phase, ctx: BarContext, reason: str) -> None:
        self._record(ctx, "transition", to=phase.value, reason=reason)
        if phase is Phase.SCANNING:
            # Both survive the reset: the cooldown is time-based, and
            # last_reject is the explanation for this transition -- clearing it
            # would erase the reason the moment it was recorded.
            cooldown, reject = self.cooldown_until, self.last_reject
            self.reset()
            self.cooldown_until = cooldown
            self.last_reject = reject
        self.phase = phase

    def _record(self, ctx: BarContext, event: str, **fields: Any) -> None:
        self.transitions.append(
            {"i": ctx.i, "ts": ctx.now.isoformat(), "event": event, **fields}
        )
        if len(self.transitions) > 2000:  # bound memory on long live runs
            del self.transitions[:1000]
