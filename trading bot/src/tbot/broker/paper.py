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

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from ..core.types import (
    AccountState,
    Bar,
    OrderRequest,
    OrderResult,
    Position,
    Side,
    SymbolSpec,
    round_to_step,
    same_symbol,
)
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
    _pending: list[ClosedTrade] = field(default_factory=list, init=False)
    _next_ticket: int = field(default=1, init=False)
    _last_bar: dict[str, Bar] = field(default_factory=dict, init=False)
    #: Optional callable returning the live spread in points for a symbol.
    #: Set in paper mode so simulated fills pay what real ones would.
    spread_source: Any = None
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
        # Case-insensitive match, exact storage: a spec captured from the broker
        # is keyed by whatever the broker calls it (EURUSDm), while a default
        # table uses the plain name.
        for name, spec in self.specs.items():
            if same_symbol(name, symbol):
                return spec
        raise BrokerError(f"no simulated spec for {symbol}; add one to PaperBroker.specs")

    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        raise BrokerError(
            "PaperBroker does not source market data; pair it with a data feed"
        )

    def positions(self, symbol: str | None = None) -> list[Position]:
        """Copies, deliberately.

        ``positions()`` is a read. Handing out live references let callers
        mutate broker state by accident -- an exit manager adjusting its local
        view of a volume would silently double-apply a partial close. The MT5
        adapter builds fresh objects per call, so copying here also keeps the
        two adapters behaving identically.
        """
        out = [replace(p) for p in self._positions.values()]
        if symbol:
            out = [p for p in out if same_symbol(p.symbol, symbol)]
        return out

    def spread_points(self, symbol: str) -> float:
        """The spread this simulated fill is charged.

        A live source takes precedence when one is attached. Paper mode on an
        MT5 feed was charging nothing at all: the simulator has no order book,
        so with no source the spread is whatever the map says, and the map is
        empty unless a backtest filled it. Every paper fill was therefore free
        while the backtest charged 240 points on gold, which made the forward
        run quietly more flattering than the test it was meant to confirm.
        """
        if self.spread_source is not None:
            try:
                live = self.spread_source(symbol)
            except Exception:  # noqa: BLE001 - a lost quote must not stop trading
                live = None
            if live is not None and live > 0:
                return float(live)
        for name, points in self.spread_points_map.items():
            if same_symbol(name, symbol):
                return points
        return 0.0

    def quote(self, symbol: str) -> tuple[float, float] | None:
        """Last bar's close, split by the configured spread.

        A simulated book has no real bid and ask; this is what the simulator
        itself fills against, so the panel shows the price the paper account is
        actually trading at rather than a prettier one.
        """
        bar = self._last_bar.get(symbol.strip())
        if bar is None:
            return None
        half = self.spread_points(symbol) * self.symbol_spec(symbol).point / 2.0
        return (bar.close - half, bar.close + half)

    def market_order(self, req: OrderRequest) -> OrderResult:
        spec = self.symbol_spec(req.symbol)
        bar = self._last_bar.get(req.symbol.strip())
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
            symbol=req.symbol.strip(),
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

    def close_position(
        self, ticket: int, volume: float | None = None, reason: str = "manual"
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, message=f"no such ticket {ticket}")
        bar = self._last_bar.get(pos.symbol)
        price = bar.close if bar else pos.entry_price
        when = bar.ts if bar else pos.opened_at

        if volume is None or volume >= pos.volume:
            self._settle_trade(pos, price, when, reason)
            return OrderResult(
                True, ticket=ticket, price=price, volume=pos.volume, message=reason
            )

        spec = self.symbol_spec(pos.symbol)
        part = round_to_step(volume, spec)
        remainder = round_to_step(pos.volume - part, spec)
        if part < spec.volume_min or remainder < spec.volume_min:
            # Closing this slice would leave an untradeable remnant behind.
            return OrderResult(
                False,
                message=(
                    f"partial close {volume} leaves {remainder} on a {spec.volume_min} "
                    f"minimum; close the whole position instead"
                ),
            )
        self._settle_trade(pos, price, when, reason, volume=part)
        pos.volume = remainder
        return OrderResult(True, ticket=ticket, price=price, volume=part, message=reason)

    def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, message=f"no such ticket {ticket}")
        spec = self.symbol_spec(pos.symbol)
        bar = self._last_bar.get(pos.symbol)
        price = bar.close if bar else pos.entry_price

        if sl is not None:
            # A stop on the wrong side of the market would fill instantly; a real
            # broker rejects it, so the simulator must too.
            if (pos.side is Side.LONG and sl >= price) or (
                pos.side is Side.SHORT and sl <= price
            ):
                return OrderResult(
                    False, message=f"stop {sl} is on the wrong side of price {price}"
                )
            pos.sl = round(sl, spec.digits)
        if tp is not None:
            if (pos.side is Side.LONG and tp <= price) or (
                pos.side is Side.SHORT and tp >= price
            ):
                return OrderResult(
                    False, message=f"target {tp} is on the wrong side of price {price}"
                )
            pos.tp = round(tp, spec.digits)
        return OrderResult(True, ticket=ticket, price=price, volume=pos.volume, message="modified")

    # ------------------------------------------------------------------ #
    # Simulation driver
    # ------------------------------------------------------------------ #

    def on_bar(self, symbol: str, bar: Bar) -> list[ClosedTrade]:
        """Advance the simulation; returns trades closed by this bar."""
        sym = symbol.strip()
        self._last_bar[sym] = bar
        for pos in [p for p in self._positions.values() if p.symbol == sym]:
            hit_sl = bar.low <= pos.sl if pos.side is Side.LONG else bar.high >= pos.sl
            hit_tp = bar.high >= pos.tp if pos.side is Side.LONG else bar.low <= pos.tp
            if hit_sl:  # pessimistic ordering: stop wins a same-bar tie
                self._settle_trade(pos, pos.sl, bar.ts, "SL")
            elif hit_tp:
                self._settle_trade(pos, pos.tp, bar.ts, "TP")
        self._equity_curve.append((bar.ts, self.account().equity))
        return self.drain_closed()

    def drain_closed(self) -> list[ClosedTrade]:
        """Trades settled since the last drain, however they were closed.

        Exit policies close positions between bars, so the engine needs a way to
        learn about those settlements too -- not only the ones a bar triggered.
        """
        out, self._pending = self._pending, []
        return out

    def _settle_trade(
        self, pos: Position, price: float, when: datetime, reason: str,
        volume: float | None = None,
    ) -> ClosedTrade:
        spec = self.symbol_spec(pos.symbol)
        closed = pos.volume if volume is None else volume
        pnl = (price - pos.entry_price) * pos.side.sign * spec.value_per_price_unit * closed
        self.balance += pnl
        if volume is None:
            self._positions.pop(pos.ticket, None)
        trade = ClosedTrade(
            symbol=pos.symbol,
            side=pos.side.value,
            volume=closed,
            entry_price=pos.entry_price,
            exit_price=price,
            opened_at=pos.opened_at,
            closed_at=when,
            pnl=pnl,
            reason=reason,
            strategy=pos.strategy,
        )
        self._closed.append(trade)
        self._pending.append(trade)
        return trade

    def _mark(self, symbol: str) -> float:
        bar = self._last_bar.get(symbol.strip())
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
