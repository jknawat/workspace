"""Deterministic simulated broker, used by both paper mode and the backtester.

Because the same object serves both, a backtest and a paper-trading session
cannot diverge in their fill logic. Fills are pessimistic on purpose:

* market orders fill at the bar close, worsened by ``slippage_points`` and half
  the configured spread;
* when a bar's range touches both the stop and the target, the **stop** is taken
  first, since intrabar sequence is unknowable from OHLC alone.

An optimistic simulator is the fastest way to build confidence in a strategy
that loses money live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..core.types import AccountState, Bar, OrderRequest, OrderResult, Position, Side, SymbolSpec
from .base import Broker, BrokerError, ClosedTrade

# Representative specs so the simulator runs with zero setup. Real runs should
# pass specs captured from the live broker (``tbot specs --save``).
DEFAULT_SPECS: dict[str, SymbolSpec] = {
    "EURUSD": SymbolSpec("EURUSD", 5, 0.00001, 0.00001, 1.0, 0.01, 0.01, 100.0, 100_000),
    "GBPUSD": SymbolSpec("GBPUSD", 5, 0.00001, 0.00001, 1.0, 0.01, 0.01, 100.0, 100_000),
    "USDJPY": SymbolSpec("USDJPY", 3, 0.001, 0.001, 0.68, 0.01, 0.01, 100.0, 100_000),
    "XAUUSD": SymbolSpec("XAUUSD", 2, 0.01, 0.01, 1.0, 0.01, 0.01, 50.0, 100),
    "XAGUSD": SymbolSpec("XAGUSD", 3, 0.001, 0.001, 5.0, 0.01, 0.01, 50.0, 5_000),
}


@dataclass(slots=True)
class PaperBroker(Broker):
    """Bar-driven simulator. Call :meth:`on_bar` for every closed bar."""

    balance: float = 10_000.0
    currency: str = "USD"
    spread_points_map: dict[str, float] = field(default_factory=dict)
    slippage_points: float = 2.0
    specs: dict[str, SymbolSpec] = field(default_factory=lambda: dict(DEFAULT_SPECS))
    name: str = "paper"

    _positions: dict[int, Position] = field(default_factory=dict, init=False)
    _closed: list[ClosedTrade] = field(default_factory=list, init=False)
    _next_ticket: int = field(default=1, init=False)
    _last_bar: dict[str, Bar] = field(default_factory=dict, init=False)
    _connected: bool = field(default=False, init=False)
    _equity_curve: list[tuple[datetime, float]] = field(default_factory=list, init=False)

    # ------------------------------------------------------------------ #
    # Broker interface
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def account(self) -> AccountState:
        equity = self.balance + sum(
            p.unrealised(self._mark(p.symbol), self.symbol_spec(p.symbol))
            for p in self._positions.values()
        )
        return AccountState(balance=self.balance, equity=equity, currency=self.currency)

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        try:
            return self.specs[symbol.upper()]
        except KeyError:
            raise BrokerError(
                f"no simulated spec for {symbol}; add one to PaperBroker.specs"
            ) from None

    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        raise BrokerError(
            "PaperBroker does not source market data; pair it with a data feed"
        )

    def positions(self, symbol: str | None = None) -> list[Position]:
        out = list(self._positions.values())
        if symbol:
            out = [p for p in out if p.symbol == symbol.upper()]
        return out

    def spread_points(self, symbol: str) -> float:
        return self.spread_points_map.get(symbol.upper(), 0.0)

    def market_order(self, req: OrderRequest) -> OrderResult:
        spec = self.symbol_spec(req.symbol)
        bar = self._last_bar.get(req.symbol.upper())
        if bar is None:
            return OrderResult(False, message=f"no market data seen for {req.symbol}")
        if req.volume < spec.volume_min:
            return OrderResult(False, message=f"volume {req.volume} below min {spec.volume_min}")

        cost = (self.spread_points(req.symbol) / 2.0 + self.slippage_points) * spec.point
        price = round(bar.close + cost * req.side.sign, spec.digits)
        if (req.side is Side.LONG and req.sl >= price) or (
            req.side is Side.SHORT and req.sl <= price
        ):
            return OrderResult(False, message=f"stop {req.sl} on wrong side of fill {price}")

        ticket = self._next_ticket
        self._next_ticket += 1
        self._positions[ticket] = Position(
            symbol=req.symbol.upper(),
            side=req.side,
            volume=req.volume,
            entry_price=price,
            sl=req.sl,
            tp=req.tp,
            opened_at=bar.ts,
            ticket=ticket,
            strategy=req.comment.split(":", 1)[0],
        )
        return OrderResult(True, ticket=ticket, price=price, volume=req.volume, message="filled")

    def close_position(self, ticket: int, reason: str = "manual") -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, message=f"no such ticket {ticket}")
        bar = self._last_bar.get(pos.symbol)
        price = bar.close if bar else pos.entry_price
        return self._settle(pos, price, bar.ts if bar else pos.opened_at, reason)

    # ------------------------------------------------------------------ #
    # Simulation driver
    # ------------------------------------------------------------------ #

    def on_bar(self, symbol: str, bar: Bar) -> list[ClosedTrade]:
        """Advance the simulation; returns trades closed by this bar."""
        sym = symbol.upper()
        self._last_bar[sym] = bar
        closed: list[ClosedTrade] = []
        for pos in [p for p in self._positions.values() if p.symbol == sym]:
            hit_sl = bar.low <= pos.sl if pos.side is Side.LONG else bar.high >= pos.sl
            hit_tp = bar.high >= pos.tp if pos.side is Side.LONG else bar.low <= pos.tp
            if hit_sl:  # pessimistic ordering: stop wins a same-bar tie
                closed.append(self._settle_trade(pos, pos.sl, bar.ts, "SL"))
            elif hit_tp:
                closed.append(self._settle_trade(pos, pos.tp, bar.ts, "TP"))
        self._equity_curve.append((bar.ts, self.account().equity))
        return closed

    def _settle(self, pos: Position, price: float, when: datetime, reason: str) -> OrderResult:
        self._settle_trade(pos, price, when, reason)
        return OrderResult(True, ticket=pos.ticket, price=price, volume=pos.volume, message=reason)

    def _settle_trade(
        self, pos: Position, price: float, when: datetime, reason: str
    ) -> ClosedTrade:
        spec = self.symbol_spec(pos.symbol)
        pnl = (price - pos.entry_price) * pos.side.sign * spec.value_per_price_unit * pos.volume
        self.balance += pnl
        self._positions.pop(pos.ticket, None)
        trade = ClosedTrade(
            symbol=pos.symbol,
            side=pos.side.value,
            volume=pos.volume,
            entry_price=pos.entry_price,
            exit_price=price,
            opened_at=pos.opened_at,
            closed_at=when,
            pnl=pnl,
            reason=reason,
            strategy=pos.strategy,
        )
        self._closed.append(trade)
        return trade

    def _mark(self, symbol: str) -> float:
        bar = self._last_bar.get(symbol.upper())
        return bar.close if bar else 0.0

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        return list(self._closed)

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)

    def force_close_all(self, reason: str = "session end") -> list[ClosedTrade]:
        out: list[ClosedTrade] = []
        for pos in list(self._positions.values()):
            bar = self._last_bar.get(pos.symbol)
            price = bar.close if bar else pos.entry_price
            when = bar.ts if bar else datetime.now(timezone.utc)
            out.append(self._settle_trade(pos, price, when, reason))
        return out
