"""ICT/SMC confluence entries, driven by MetaTrader 5's structure snapshot.

The model, in one line: **structure picks the direction, a zone gives the entry
and the stop, liquidity gives the target.**

    SCANNING  price trades into a directional zone (order block / FVG / breaker)
              that agrees with the published structural bias
       ↓
    ARMED     wait for confirmation — a directional close, or a fresh BOS/MSS
       ↓
    ENTRY     stop just beyond the zone's far edge; target an R multiple or the
              next liquidity pool
       ↓
    COOLDOWN

What makes this different from the ATR-only model in ``ema_pullback``: the stop
comes from *structure*, not from volatility. If the zone is wrong, price closes
through it and the trade is done — which is both a tighter stop and a more
meaningful one. ATR is used only to size the buffer beyond the edge and to
sanity-check that the resulting stop is neither microscopic nor absurd.

Two safeguards worth knowing about:

* **One entry per zone.** An order block stays ``active`` for many bars. Without
  remembering which zones have been traded, a bot re-enters the same setup on
  every bar until the zone finally breaks. Traded zone ids are retained.
* **Stop-distance bounds.** A zone a fraction of an ATR tall would produce a
  huge position for the same money risk. Stops outside
  ``[min_sl_atr, max_sl_atr]`` are rejected with the reason recorded.
"""

from __future__ import annotations

from typing import Any

from ..config.models import ConfigError
from ..core.indicators import Series, atr
from ..core.types import Bar, Phase, Side, Signal
from ..data.snapshot import Record, Snapshot
from .base import BarContext, Strategy, register
from .filters import build_chain
from .ict_filters import zones_touching

CONFIRMATIONS = {"none", "candle", "structure"}
TARGETS = {"rr", "liquidity"}


@register
class IctConfluence(Strategy):
    name = "ict_confluence"

    defaults: dict[str, Any] = {
        # zone selection
        "zone_concepts": ["ORDER_BLOCK", "FVG"],
        "zone_states": [],              # empty: any state; e.g. ["fresh"]
        "zone_tolerance_points": 0.0,
        "zone_max_age_minutes": 0.0,    # 0: no age limit
        "zone_min_strength": 0.0,
        # direction
        "require_bias": True,
        "bias_concepts": ["BOS", "CHOCH", "MSS", "DISPLACEMENT"],
        # confirmation
        "confirmation": "candle",       # none | candle | structure
        "confirm_max_bars": 3,
        "structure_concepts": ["BOS", "MSS", "DISPLACEMENT"],
        # exits
        "atr_period": 14,
        "sl_buffer_atr": 0.5,
        "min_sl_atr": 0.5,
        "max_sl_atr": 6.0,
        "target": "rr",                 # rr | liquidity
        "tp_rr": 2.0,
        "liquidity_min_rr": 1.5,        # fall back to rr below this
        # hygiene
        "one_entry_per_zone": True,
        "cooldown_bars": 6,
    }

    def __init__(self, cfg, spec) -> None:
        super().__init__(cfg, spec)
        for key, allowed in (("confirmation", CONFIRMATIONS), ("target", TARGETS)):
            if self.p(key) not in allowed:
                raise ConfigError(
                    f"ict_confluence.{key}: {self.p(key)!r} not in {sorted(allowed)}"
                )
        self.filters = build_chain(cfg.filters)
        self.transitions: list[dict[str, Any]] = []
        self.traded_zones: list[str] = []
        self.reset()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        self.phase: Phase = Phase.SCANNING
        self.side: Side | None = None
        self.zone: Record | None = None
        self.armed_at: int | None = None
        self.cooldown_until: int = -1
        self.last_reject: str = ""

    @property
    def warmup(self) -> int:
        return int(self.p("atr_period")) + 2

    def compute(self, bars: list[Bar]) -> dict[str, Series]:
        # Structure comes from MT5; ATR is all this strategy needs locally.
        return {"atr": atr(bars, int(self.p("atr_period")))}

    def state_summary(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "side": self.side.value if self.side else None,
            "zone": self.zone.id if self.zone else None,
            "traded_zones": len(self.traded_zones),
            "last_reject": self.last_reject,
        }

    # ------------------------------------------------------------------ #
    # Bar handling
    # ------------------------------------------------------------------ #

    def on_bar(self, ctx: BarContext) -> Signal | None:
        if ctx.i < self.warmup or not ctx.ready("atr"):
            return None

        snapshot = ctx.snapshot
        if snapshot is None:
            # Fail closed: without structure this strategy has no opinion at all.
            self.last_reject = "no fresh MT5 structure snapshot"
            if self.phase is not Phase.SCANNING:
                self._to(Phase.SCANNING, ctx, self.last_reject)
            return None

        if self.phase is Phase.COOLDOWN:
            if ctx.i < self.cooldown_until:
                return None
            self._to(Phase.SCANNING, ctx, "cooldown elapsed")

        if self.phase is Phase.ARMED:
            return self._armed(ctx, snapshot)
        return self._scan(ctx, snapshot)

    # -- phase 1: find a zone ------------------------------------------- #

    def _scan(self, ctx: BarContext, snapshot: Snapshot) -> Signal | None:
        for side in self.sides:
            if bool(self.p("require_bias")):
                bias = snapshot.bias(*self.p("bias_concepts"))
                wanted = "bullish" if side is Side.LONG else "bearish"
                if bias != wanted:
                    continue

            zone = self._pick_zone(ctx, snapshot, side)
            if zone is None:
                continue

            decision = self.filters.evaluate(ctx, side)
            if not decision:
                self.last_reject = decision.reason
                self._record(ctx, "rejected", side=side.value, zone=zone.id,
                             reason=decision.reason)
                continue

            self.side, self.zone, self.armed_at = side, zone, ctx.i
            if self.p("confirmation") == "none":
                return self._try_enter(ctx, snapshot, "zone touch, no confirmation required")
            self._to(Phase.ARMED, ctx, f"{side.value} zone {zone.id} touched")
            # A directional bar can confirm the setup it created.
            return self._armed(ctx, snapshot, first_bar=True)
        return None

    def _pick_zone(self, ctx: BarContext, snapshot: Snapshot, side: Side) -> Record | None:
        options = {
            "concepts": self.p("zone_concepts"),
            "states": self.p("zone_states"),
            "tolerance_points": self.p("zone_tolerance_points"),
            "max_age_minutes": self.p("zone_max_age_minutes"),
            "min_strength": self.p("zone_min_strength"),
            "require_direction": True,
        }
        for zone in zones_touching(ctx, snapshot, side, options):
            if bool(self.p("one_entry_per_zone")) and zone.id in self.traded_zones:
                continue
            return zone
        return None

    # -- phase 2: confirmation ------------------------------------------ #

    def _armed(
        self, ctx: BarContext, snapshot: Snapshot, first_bar: bool = False
    ) -> Signal | None:
        assert self.side is not None and self.zone is not None and self.armed_at is not None
        side, zone = self.side, self.zone
        bar = ctx.bar

        # Invalidation: a close beyond the zone's far edge means the zone failed.
        broke = bar.close < zone.lower if side is Side.LONG else bar.close > zone.upper
        if broke:
            self._to(Phase.SCANNING, ctx, f"close through zone {zone.id}")
            return None

        if not first_bar and ctx.i - self.armed_at > int(self.p("confirm_max_bars")):
            self._to(Phase.SCANNING, ctx, "confirmation window expired")
            return None

        mode = self.p("confirmation")
        if mode == "candle":
            confirmed = bar.is_bullish if side is Side.LONG else bar.is_bearish
            reason = "directional close inside the zone"
        else:  # structure
            event = self._structure_event(ctx, snapshot, side)
            confirmed = event is not None
            reason = f"structure {event.concept} {event.id}" if event else ""

        if not confirmed:
            return None
        return self._try_enter(ctx, snapshot, reason)

    def _structure_event(
        self, ctx: BarContext, snapshot: Snapshot, side: Side
    ) -> Record | None:
        """A structural event agreeing with ``side``, confirmed since arming."""
        assert self.armed_at is not None
        since = ctx.bars[self.armed_at].ts
        for record in snapshot.by_concept(*self.p("structure_concepts")):
            if record.agrees_with(side.value) and record.confirmed_at >= since:
                return record
        return None

    # -- phase 3: build the order --------------------------------------- #

    def _try_enter(self, ctx: BarContext, snapshot: Snapshot, reason: str) -> Signal | None:
        assert self.side is not None and self.zone is not None
        side, zone = self.side, self.zone
        a = ctx.require("atr")
        entry = ctx.bar.close

        buffer = float(self.p("sl_buffer_atr")) * a
        sl = zone.lower - buffer if side is Side.LONG else zone.upper + buffer
        sl_distance = abs(entry - sl)

        low, high = float(self.p("min_sl_atr")) * a, float(self.p("max_sl_atr")) * a
        if sl_distance < low or sl_distance > high:
            self.last_reject = (
                f"stop {sl_distance / a:.2f} ATR outside "
                f"[{self.p('min_sl_atr')}, {self.p('max_sl_atr')}]"
            )
            self._to(Phase.SCANNING, ctx, self.last_reject)
            return None

        tp, target_kind = self._target(ctx, snapshot, side, entry, sl_distance)

        if bool(self.p("one_entry_per_zone")):
            self.traded_zones.append(zone.id)
            if len(self.traded_zones) > 500:  # bound memory on long live runs
                del self.traded_zones[:250]

        meta = {
            "atr": a,
            "zone_id": zone.id,
            "zone_concept": zone.concept,
            "zone_lower": zone.lower,
            "zone_upper": zone.upper,
            "zone_state": zone.state,
            "bias": snapshot.bias(*self.p("bias_concepts")),
            "target": target_kind,
            "snapshot_as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
            "bar_index": ctx.i,
        }
        signal = Signal(
            symbol=ctx.symbol,
            side=side,
            ts=ctx.now,
            price=round(entry, self.spec.digits),
            sl=round(sl, self.spec.digits),
            tp=round(tp, self.spec.digits),
            strategy=self.name,
            reason=f"{zone.concept} {zone.id}: {reason}",
            meta=meta,
        )
        self._record(ctx, "entry", side=side.value, zone=zone.id, reason=reason)
        self._enter_cooldown(ctx)
        return signal

    def _target(
        self, ctx: BarContext, snapshot: Snapshot, side: Side, entry: float, risk: float
    ) -> tuple[float, str]:
        """Take profit: the next liquidity pool, or a plain R multiple.

        Liquidity targets use **geometry, not direction labels** -- the nearest
        published level beyond entry in the trade's direction. Which side of the
        book a library labels "bullish" is a convention that can differ between
        versions; "above the entry" cannot.
        """
        rr_target = entry + float(self.p("tp_rr")) * risk * side.sign
        if self.p("target") != "liquidity" or risk <= 0:
            return rr_target, "rr"

        levels = [
            r.reference_price or r.mid
            for r in snapshot.by_concept("LIQUIDITY")
            if (r.reference_price or r.mid) * side.sign > entry * side.sign
        ]
        if not levels:
            return rr_target, "rr (no liquidity ahead)"

        level = min(levels) if side is Side.LONG else max(levels)
        if abs(level - entry) / risk < float(self.p("liquidity_min_rr")):
            return rr_target, "rr (liquidity too close)"
        return level, "liquidity"

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _enter_cooldown(self, ctx: BarContext) -> None:
        self.cooldown_until = ctx.i + int(self.p("cooldown_bars"))
        self.phase = Phase.COOLDOWN
        self.side = None
        self.zone = None
        self.armed_at = None

    def _to(self, phase: Phase, ctx: BarContext, reason: str) -> None:
        self._record(ctx, "transition", to=phase.value, reason=reason)
        if phase is Phase.SCANNING:
            cooldown, traded = self.cooldown_until, self.traded_zones
            self.reset()
            self.cooldown_until = cooldown
            self.traded_zones = traded
        self.phase = phase

    def _record(self, ctx: BarContext, event: str, **fields: Any) -> None:
        self.transitions.append(
            {"i": ctx.i, "ts": ctx.now.isoformat(), "event": event, **fields}
        )
        if len(self.transitions) > 2000:
            del self.transitions[:1000]
