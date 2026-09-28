"""The broker port.

Everything above this line (strategy, risk, engine, journal) depends only on
this interface. Everything MetaTrader-specific lives behind it. That boundary
is what lets the whole system be exercised on a laptop with no terminal
installed, and it is the main structural difference from bots that import
``MetaTrader5`` directly inside their strategy and GUI code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..core.types import AccountState, Bar, OrderRequest, OrderResult, Position, SymbolSpec


class BrokerError(RuntimeError):
    """Any broker-side failure: connection, symbol lookup, or rejected order."""


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    symbol: str
    side: str
    volume: float
    entry_price: float
    exit_price: float
    opened_at: datetime
    closed_at: datetime
    pnl: float
    reason: str
    strategy: str = ""


class Broker(ABC):
    """Minimal surface the engine needs. Keep it small; adapters stay cheap."""

    name: str = "broker"

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def account(self) -> AccountState: ...

    @abstractmethod
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...

    @abstractmethod
    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]: ...

    @abstractmethod
    def positions(self, symbol: str | None = None) -> list[Position]: ...

    @abstractmethod
    def market_order(self, req: OrderRequest) -> OrderResult: ...

    @abstractmethod
    def close_position(self, ticket: int, reason: str = "manual") -> OrderResult: ...

    def spread_points(self, symbol: str) -> float:
        """Current spread in points; 0.0 when quotes are unavailable."""
        return 0.0

    def __enter__(self) -> "Broker":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()
