"""Exit policies: what happens to a position *after* it is opened.

Until now a trade opened and then waited for its stop or its target. That is
the simplest possible exit model and it leaves a lot on the table: no moving to
break-even once a trade is safe, no trailing a runner, no banking part of a
winner.

Each policy is a small object built from config, exactly like an entry filter:

    [exits.break_even]
    trigger_r = 1.0

    [exits.trailing_atr]
    distance_atr = 2.0
    start_r = 1.5

Two properties matter more than the policies themselves:

* **They run through the broker port.** The simulator implements
  ``modify_position`` and partial ``close_position`` the same way the MT5
  adapter does, so a backtest exercises the real exit logic rather than an
  idealised version of it.
* **Stops only ever move in the protective direction, and only to a placeable
  level.** A trailing stop that can loosen is not a trailing stop; it is a way
  to turn a small loss into a large one. And trailing behind the best price
  seen can compute a stop on the wrong side of the market after a long wick,
  which a real broker rejects. Both are checked before anything is sent.

Risk is measured in *R*: one R is the distance from entry to the position's
**original** stop, remembered when the position is first seen. Measuring
against the current stop would make R shrink every time the stop moved, so
"take half off at 1R" would keep re-triggering.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..broker.base import Broker
from ..config.models import ConfigError
from ..core.types import Position, Side, round_to_step
from ..obs import log as obs_log
from ..strategy.base import BarContext


@dataclass(frozen=True, slots=True)
class ExitAction:
    """One instruction for an open position."""

    kind: str  # "modify" | "close"
    ticket: int
    reason: str
    sl: float | None = None
    tp: float | None = None
    volume: float | None = None  # None on a close means "all of it"

    @property
    def is_close(self) -> bool:
        return self.kind == "close"


@dataclass(slots=True)
class PositionState:
    """Per-position memory an exit policy may rely on across bars."""

    initial_risk: float
    opened_index: int
    best_price: float  # most favourable price seen since entry
    flags: dict[str, Any] = field(default_factory=dict)

    def r_multiple(self, price: float, pos: Position) -> float:
        if self.initial_risk <= 0:
            return 0.0
        return (price - pos.entry_price) * pos.side.sign / self.initial_risk


# --------------------------------------------------------------------------- #
# Policy base and registry
# --------------------------------------------------------------------------- #


class ExitPolicy(ABC):
    name: ClassVar[str] = "base"
    defaults: ClassVar[dict[str, Any]] = {}

    def __init__(self, **options: Any) -> None:
        unknown = set(options) - set(self.defaults)
        if unknown:
            raise ConfigError(
                f"exit policy {self.name!r}: unknown option(s) {sorted(unknown)}; "
                f"known: {sorted(self.defaults)}"
            )
        self.opt = {**self.defaults, **options}

    @abstractmethod
    def evaluate(
        self, pos: Position, ctx: BarContext, state: PositionState
    ) -> ExitAction | None:
        """Return an action for this bar, or ``None`` to leave the position alone."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{self.name} {self.opt}>"


_REGISTRY: dict[str, type[ExitPolicy]] = {}


def register(cls: type[ExitPolicy]) -> type[ExitPolicy]:
    _REGISTRY[cls.name] = cls
    return cls


def available() -> list[str]:
    return sorted(_REGISTRY)


def build_policies(spec: dict[str, dict[str, Any]]) -> list[ExitPolicy]:
    out: list[ExitPolicy] = []
    for name, options in spec.items():
        opts = dict(options)
        if not opts.pop("enabled", True):
            continue
        try:
            cls = _REGISTRY[name]
        except KeyError:
            raise ConfigError(
                f"unknown exit policy {name!r}; available: {sorted(_REGISTRY)}"
            ) from None
        out.append(cls(**opts))
    return out


# --------------------------------------------------------------------------- #
# Policies
# --------------------------------------------------------------------------- #


@register
class BreakEvenPolicy(ExitPolicy):
    """Move the stop to entry once the trade is far enough ahead.

    ``offset_r`` nudges it slightly past entry so the trade covers its own
    costs rather than scratching at exactly zero.
    """

    name = "break_even"
    defaults: ClassVar[dict[str, Any]] = {"trigger_r": 1.0, "offset_r": 0.05}

    def evaluate(self, pos, ctx, state):
        if state.flags.get("break_even"):
            return None
        if state.r_multiple(ctx.bar.close, pos) < float(self.opt["trigger_r"]):
            return None
        target = pos.entry_price + float(self.opt["offset_r"]) * state.initial_risk * pos.side.sign
        if not _improves(pos, target, ctx.bar.close):
            return None
        state.flags["break_even"] = True
        return ExitAction(
            "modify", pos.ticket, f"break-even at {self.opt['trigger_r']}R", sl=target
        )


@register
class TrailingAtrPolicy(ExitPolicy):
    """Trail the stop a fixed ATR distance behind the best price seen.

    ``start_r`` delays trailing until the trade is meaningfully ahead; trailing
    from the first bar is usually just a wider way of getting stopped out.
    """

    name = "trailing_atr"
    defaults: ClassVar[dict[str, Any]] = {"distance_atr": 2.0, "start_r": 1.0, "source": "atr"}

    def evaluate(self, pos, ctx, state):
        atr = ctx.value(str(self.opt["source"]))
        if atr is None or atr <= 0:
            return None
        if state.r_multiple(ctx.bar.close, pos) < float(self.opt["start_r"]):
            return None
        target = state.best_price - float(self.opt["distance_atr"]) * atr * pos.side.sign
        if not _improves(pos, target, ctx.bar.close):
            return None
        return ExitAction("modify", pos.ticket, "trailing stop (ATR)", sl=target)


@register
class TrailingStructurePolicy(ExitPolicy):
    """Trail behind the most recent swing published by MetaTrader 5.

    A structural trail respects where price actually turned, instead of a fixed
    distance that ignores the shape of the move. Needs a fresh snapshot; with
    none it simply does nothing, leaving any other policy in charge.
    """

    name = "trailing_structure"
    defaults: ClassVar[dict[str, Any]] = {"start_r": 1.0, "buffer_atr": 0.25, "source": "atr"}

    def evaluate(self, pos, ctx, state):
        if ctx.snapshot is None:
            return None
        if state.r_multiple(ctx.bar.close, pos) < float(self.opt["start_r"]):
            return None
        concept = "SWING_LOW" if pos.side is Side.LONG else "SWING_HIGH"
        swing = ctx.snapshot.latest(concept)
        if swing is None:
            return None

        atr = ctx.value(str(self.opt["source"])) or 0.0
        buffer = float(self.opt["buffer_atr"]) * atr
        level = swing.lower if pos.side is Side.LONG else swing.upper
        target = level - buffer * pos.side.sign
        if not _improves(pos, target, ctx.bar.close):
            return None
        return ExitAction(
            "modify", pos.ticket, f"trailing stop behind {swing.id}", sl=target
        )


@register
class PartialTakeProfitPolicy(ExitPolicy):
    """Bank part of the position at a fixed R multiple, once.

    The remainder keeps its original target, so a trade that runs still pays
    for the ones that did not.
    """

    name = "partial_tp"
    defaults: ClassVar[dict[str, Any]] = {"trigger_r": 1.0, "percent": 50.0}

    def evaluate(self, pos, ctx, state):
        if state.flags.get("partial_tp"):
            return None
        if state.r_multiple(ctx.bar.close, pos) < float(self.opt["trigger_r"]):
            return None
        percent = max(0.0, min(100.0, float(self.opt["percent"])))
        volume = round_to_step(pos.volume * percent / 100.0, ctx.spec)
        if volume < ctx.spec.volume_min:
            # Too small to slice; leaving the position whole is the safe answer.
            state.flags["partial_tp"] = True
            return None
        remainder = round_to_step(pos.volume - volume, ctx.spec)
        if remainder < ctx.spec.volume_min:
            state.flags["partial_tp"] = True
            return None
        state.flags["partial_tp"] = True
        return ExitAction(
            "close",
            pos.ticket,
            f"partial {percent:.0f}% at {self.opt['trigger_r']}R",
            volume=volume,
        )


@register
class TimeStopPolicy(ExitPolicy):
    """Close a position that has gone nowhere for too long.

    Capital tied up in a trade that has not worked is capital unavailable to
    one that might. ``min_r`` lets a winner keep running past the deadline.
    """

    name = "time_stop"
    defaults: ClassVar[dict[str, Any]] = {"max_bars": 48, "min_r": 0.5}

    def evaluate(self, pos, ctx, state):
        held = ctx.i - state.opened_index
        if held < int(self.opt["max_bars"]):
            return None
        if state.r_multiple(ctx.bar.close, pos) >= float(self.opt["min_r"]):
            return None  # it is working; let it run
        return ExitAction("close", pos.ticket, f"time stop after {held} bars")


def _improves(pos: Position, new_sl: float, price: float) -> bool:
    """True only when the new stop is both tighter *and* actually placeable.

    Two conditions, and the second is easy to forget:

    1. It must move in the protective direction. A trailing stop that can also
       loosen is a mechanism for turning small losses into large ones.
    2. It must stay on the correct side of the current price. Trailing a fixed
       distance behind the best price seen produces a stop *above* the market
       whenever a bar prints a long wick and closes well back -- a real broker
       rejects that, and it would otherwise mean an instant stop-out.
    """
    if pos.side is Side.LONG:
        return new_sl > pos.sl and new_sl < price
    return new_sl < pos.sl and new_sl > price


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class AppliedExit:
    action: ExitAction
    ok: bool
    message: str


class ExitManager:
    """Runs the configured policies over open positions, once per closed bar."""

    def __init__(self, policies: list[ExitPolicy]) -> None:
        self.policies = policies
        self.state: dict[int, PositionState] = {}
        self.log = obs_log.get("exits")

    def __len__(self) -> int:
        return len(self.policies)

    @classmethod
    def from_config(cls, spec: dict[str, dict[str, Any]]) -> ExitManager:
        return cls(build_policies(spec))

    def forget(self, live_tickets: set[int]) -> None:
        """Drop memory of positions that no longer exist."""
        for ticket in [t for t in self.state if t not in live_tickets]:
            del self.state[ticket]

    def _state_for(self, pos: Position, ctx: BarContext) -> PositionState:
        st = self.state.get(pos.ticket)
        if st is None:
            st = PositionState(
                initial_risk=abs(pos.entry_price - pos.sl),
                opened_index=ctx.i,
                best_price=pos.entry_price,
            )
            self.state[pos.ticket] = st
        # Track the best price *including wicks*: a stop trails against the
        # extreme the market actually reached, not just where bars closed.
        extreme = ctx.bar.high if pos.side is Side.LONG else ctx.bar.low
        if (extreme - st.best_price) * pos.side.sign > 0:
            st.best_price = extreme
        return st

    def manage(
        self, positions: list[Position], ctx: BarContext, broker: Broker
    ) -> list[AppliedExit]:
        """Evaluate every policy against every open position for this symbol."""
        applied: list[AppliedExit] = []
        if not self.policies:
            return applied

        for pos in positions:
            if pos.symbol != ctx.symbol:
                continue
            state = self._state_for(pos, ctx)
            for policy in self.policies:
                action = policy.evaluate(pos, ctx, state)
                if action is None:
                    continue
                result = self._apply(action, pos, broker)
                applied.append(result)
                if not result.ok:
                    continue
                if action.is_close and (
                    action.volume is None or action.volume >= pos.volume
                ):
                    break  # the position is gone; later policies have nothing to act on
                if action.is_close and action.volume is not None:
                    pos.volume = round_to_step(pos.volume - action.volume, ctx.spec)
                elif action.sl is not None:
                    pos.sl = action.sl
        return applied

    def _apply(self, action: ExitAction, pos: Position, broker: Broker) -> AppliedExit:
        if action.is_close:
            result = broker.close_position(
                action.ticket, volume=action.volume, reason=action.reason
            )
        else:
            result = broker.modify_position(action.ticket, sl=action.sl, tp=action.tp)

        level = self.log.info if result.ok else self.log.warning
        level(
            "%s %s #%d: %s -> %s",
            action.kind, pos.symbol, action.ticket, action.reason, result.message,
            extra={
                "symbol": pos.symbol,
                "event": f"exit_{action.kind}",
                "ticket": action.ticket,
                "reason": action.reason,
                "ok": result.ok,
                "sl": action.sl,
                "volume": action.volume,
            },
        )
        return AppliedExit(action=action, ok=result.ok, message=result.message)
