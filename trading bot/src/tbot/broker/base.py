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
    def close_position(
        self, ticket: int, volume: float | None = None, reason: str = "manual"
    ) -> OrderResult:
        """Close a position. ``volume`` closes only part of it (partial exit)."""

    @abstractmethod
    def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        """Move a live position's stop and/or target. ``None`` leaves one unchanged."""

    def spread_points(self, symbol: str) -> float:
        """Current spread in points; 0.0 when quotes are unavailable."""
        return 0.0

    def closed_trade(self, ticket: int) -> ClosedTrade | None:
        """Reconstruct a settled trade the broker closed on its own.

        In live trading a stop or target fires server-side: there is no
        callback, the position simply disappears between polls. Without this
        the bot knows its balance moved but never records *what* happened, so
        the journal keeps the signal and loses the outcome -- which is the one
        half that makes the record worth keeping.

        ``None`` means the trade could not be reconstructed.
        """
        return None

    def preflight(self, symbol: str) -> tuple[bool, str]:
        """Can this broker actually accept an order for ``symbol`` right now?

        Returns ``(fatal, message)``. ``fatal`` means the request shape itself
        is wrong -- the bot will never place a trade until it is fixed -- as
        opposed to a passing condition like a closed market or no free margin.

        This exists because two live orders were refused for a malformed
        comment field and the failure only surfaced on the first signal, hours
        later, having already cost the setups. A broker that will refuse every
        order should say so at startup.
        """
        return False, "not checked"

    def quote(self, symbol: str) -> tuple[float, float] | None:
        """Current ``(bid, ask)``, or ``None`` when no quote is available.

        For display only. Nothing that decides a trade reads this: entries are
        made on closed bars, and a mid-bar price that moved a decision would be
        a different strategy than the one that was backtested.
        """
        return None

    def __enter__(self) -> Broker:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()
