"""Portfolio-level risk gate.

One object owns every "may this order exist?" question: budget per symbol,
concurrency caps, reward/risk floor, and the daily loss kill-switch. The
strategy layer decides *direction*; this layer decides *size and permission*,
and it is the only place either is decided.

Budget model: each symbol carries a weight, weights are renormalised across the
enabled symbols, and a symbol's risk budget is
``balance * risk_per_trade_pct/100 * weight``. Total risk therefore stays at
``risk_per_trade_pct`` even if every symbol signals on the same bar -- as
opposed to equal-weighting, where N simultaneous signals risk N x the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..config.models import BotConfig
from ..core.types import (
    AccountState,
    Decision,
    OrderRequest,
    Position,
    Signal,
    SymbolSpec,
    same_symbol,
)
from .sizing import SizingResult, lot_for_risk


@dataclass(slots=True)
class DayBook:
    """Realised PnL for a single trading day (UTC)."""

    day: date
    realised: float = 0.0
    trades: int = 0

    def add(self, pnl: float) -> None:
        self.realised += pnl
        self.trades += 1


@dataclass(slots=True)
class RiskManager:
    cfg: BotConfig
    book: DayBook = field(default_factory=lambda: DayBook(date.min))
    halted_reason: str = ""

    # ------------------------------------------------------------------ #
    # Budget
    # ------------------------------------------------------------------ #

    def weight_for(self, symbol: str) -> float | None:
        """This symbol's share of the risk budget, or ``None`` if unconfigured.

        Case-insensitive, and ``None`` rather than ``0.0`` for "not found" --
        the two mean very different things. An uppercase lookup here once
        turned every XAUUSDm signal into "risk budget is zero or negative",
        which reads like a balance problem and is actually a name mismatch.
        """
        for name, weight in self.cfg.normalised_weights.items():
            if same_symbol(name, symbol):
                return weight
        return None

    def budget_for(self, symbol: str, balance: float, risk_mult: float = 1.0) -> float:
        """Money at risk for one trade.

        ``risk_mult`` is the confidence scorer's share of the budget. It scales
        the *risk*, not the lot size: scaling lots directly would mean a trade
        with a wide stop risked proportionally more, which is the one thing
        position sizing exists to prevent.
        """
        weight = self.weight_for(symbol) or 0.0
        return (
            balance
            * (self.cfg.risk.risk_per_trade_pct / 100.0)
            * weight
            * max(risk_mult, 0.0)
        )

    def daily_loss_limit(self, balance: float) -> float:
        return balance * (self.cfg.risk.max_daily_loss_pct / 100.0)

    # ------------------------------------------------------------------ #
    # Day roll / PnL tracking
    # ------------------------------------------------------------------ #

    def roll_day(self, today: date) -> None:
        if self.book.day != today:
            self.book = DayBook(today)
            self.halted_reason = ""

    def record_close(self, pnl: float, when: date) -> None:
        self.roll_day(when)
        self.book.add(pnl)

    # ------------------------------------------------------------------ #
    # The gate
    # ------------------------------------------------------------------ #

    def approve(
        self,
        signal: Signal,
        spec: SymbolSpec,
        account: AccountState,
        positions: list[Position],
        risk_mult: float = 1.0,
    ) -> tuple[Decision, OrderRequest | None]:
        self.roll_day(signal.ts.date())
        risk_cfg = self.cfg.risk

        if self.halted_reason:
            return Decision.no(f"halted: {self.halted_reason}"), None

        loss_limit = self.daily_loss_limit(account.balance)
        if -self.book.realised >= loss_limit > 0:
            self.halted_reason = (
                f"daily loss {self.book.realised:.2f} hit limit -{loss_limit:.2f}"
            )
            return Decision.no(self.halted_reason), None

        if len(positions) >= risk_cfg.max_open_positions:
            return Decision.no(
                f"{len(positions)} open positions >= cap {risk_cfg.max_open_positions}"
            ), None

        same = [p for p in positions if p.symbol == signal.symbol]
        if len(same) >= risk_cfg.max_positions_per_symbol:
            return Decision.no(
                f"{signal.symbol} already has {len(same)} position(s)"
            ), None

        if signal.sl_distance <= 0:
            return Decision.no("signal has no stop distance"), None

        if signal.rr < risk_cfg.min_rr:
            return Decision.no(
                f"reward/risk {signal.rr:.2f} < min {risk_cfg.min_rr:.2f}"
            ), None

        if self.weight_for(signal.symbol) is None:
            # A name mismatch, not a money problem -- say which.
            return Decision.no(
                f"{signal.symbol} has no risk weight; configured symbols are "
                f"{sorted(self.cfg.normalised_weights)}"
            ), None

        budget = self.budget_for(signal.symbol, account.balance, risk_mult)
        sizing: SizingResult = lot_for_risk(spec, budget, signal.sl_distance)
        if not sizing.ok:
            return Decision.no(f"sizing: {sizing.reason}", budget=budget), None

        order = OrderRequest(
            symbol=signal.symbol,
            side=signal.side,
            volume=sizing.volume,
            sl=signal.sl,
            tp=signal.tp,
            comment=f"{signal.strategy}:{signal.reason}"[:60],
        )
        return (
            Decision.ok(
                "approved",
                budget=budget,
                volume=sizing.volume,
                risk_money=sizing.risk_money,
                rr=signal.rr,
            ),
            order,
        )
