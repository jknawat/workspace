"""Strategy contract and registry.

A strategy is a *pure decision function over a bar history*. It never talks to a
broker, never places an order, and never touches the GUI -- it returns a
:class:`Signal` or ``None``. That is what makes the identical object usable in
backtest, paper and live mode without a second code path.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, ClassVar

from ..config.models import ConfigError, SymbolConfig
from ..core.indicators import Series
from ..core.types import Bar, Side, Signal, SymbolSpec


@dataclass(slots=True)
class BarContext:
    """Everything a strategy or filter may look at for one bar."""

    cfg: SymbolConfig
    spec: SymbolSpec
    bars: list[Bar]
    i: int
    ind: dict[str, Series]
    spread_points: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return self.cfg.symbol

    @property
    def bar(self) -> Bar:
        return self.bars[self.i]

    @property
    def prev(self) -> Bar | None:
        return self.bars[self.i - 1] if self.i > 0 else None

    @property
    def now(self) -> datetime:
        return self.bars[self.i].ts

    def value(self, name: str, offset: int = 0) -> float | None:
        """Indicator value ``offset`` bars back from the current bar."""
        series = self.ind.get(name)
        if series is None:
            return None
        idx = self.i - offset
        return series[idx] if 0 <= idx < len(series) else None

    def require(self, name: str, offset: int = 0) -> float:
        v = self.value(name, offset)
        if v is None:
            raise LookupError(f"{self.symbol}: indicator '{name}'[-{offset}] not ready")
        return v

    def ready(self, *names: str) -> bool:
        return all(self.value(n) is not None for n in names)


class Strategy(ABC):
    """Base class for all strategies."""

    name: ClassVar[str] = "base"
    defaults: ClassVar[dict[str, Any]] = {}

    def __init__(self, cfg: SymbolConfig, spec: SymbolSpec) -> None:
        self.cfg = cfg
        self.spec = spec
        self.params = self._merge_params(cfg.params)
        self.sides = tuple(Side(s) for s in cfg.sides)

    @classmethod
    def _merge_params(cls, given: dict[str, Any]) -> dict[str, Any]:
        unknown = set(given) - set(cls.defaults)
        if unknown:
            raise ConfigError(
                f"strategy '{cls.name}': unknown param(s) {sorted(unknown)}; "
                f"known: {sorted(cls.defaults)}"
            )
        merged = dict(cls.defaults)
        merged.update(given)
        return merged

    def p(self, key: str) -> Any:
        return self.params[key]

    @property
    @abstractmethod
    def warmup(self) -> int:
        """Bars required before the strategy may emit anything."""

    @abstractmethod
    def compute(self, bars: list[Bar]) -> dict[str, Series]:
        """Compute named indicator series over the full bar history."""

    @abstractmethod
    def on_bar(self, ctx: BarContext) -> Signal | None:
        """Evaluate one closed bar. Return a signal or ``None``."""

    def reset(self) -> None:
        """Drop any internal state (used when the feed gaps or on restart)."""

    def state_summary(self) -> dict[str, Any]:
        """Human-readable state, surfaced by ``tbot status`` and the journal."""
        return {}


_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    if cls.name in _REGISTRY:
        raise ValueError(f"strategy '{cls.name}' already registered")
    _REGISTRY[cls.name] = cls
    return cls


def create(cfg: SymbolConfig, spec: SymbolSpec) -> Strategy:
    try:
        cls = _REGISTRY[cfg.strategy]
    except KeyError:
        raise ConfigError(
            f"unknown strategy '{cfg.strategy}'; available: {sorted(_REGISTRY)}"
        ) from None
    return cls(cfg, spec)


def available() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str) -> type[Strategy]:
    return _REGISTRY[name]
