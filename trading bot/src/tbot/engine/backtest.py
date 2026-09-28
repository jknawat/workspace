"""Bar-replay backtester.

It drives the *same* :class:`TradeEngine`, strategy objects, risk manager and
simulated broker that paper mode uses, so a backtest result is a statement about
the code that will actually trade -- not about a parallel implementation of it.

Lookahead safety: indicators are computed over the full series once, but every
value at index ``i`` depends only on bars ``<= i`` (see ``core.indicators``), and
the strategy is handed a context pinned to ``i``. Bars after ``i`` are present in
the list but no code path reads forward -- the one place that could, the channel
in ``donchian``, deliberately excludes the current bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..broker.base import ClosedTrade
from ..broker.paper import PaperBroker
from ..config.models import BotConfig
from ..core.types import Bar, SymbolSpec
from ..data.feed import BarFeed
from ..journal import Journal
from ..obs import log as obs_log
from ..risk import RiskManager
from .core import TradeEngine


@dataclass(slots=True)
class BacktestReport:
    start_balance: float
    end_balance: float
    trades: list[ClosedTrade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    signals: int = 0
    declined: int = 0
    bars: int = 0
    declined_reasons: dict[str, int] = field(default_factory=dict)

    # -- derived metrics ------------------------------------------------- #

    @property
    def net_pnl(self) -> float:
        return self.end_balance - self.start_balance

    @property
    def return_pct(self) -> float:
        return (self.net_pnl / self.start_balance * 100.0) if self.start_balance else 0.0

    @property
    def wins(self) -> list[ClosedTrade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losses(self) -> list[ClosedTrade]:
        return [t for t in self.trades if t.pnl <= 0]

    @property
    def win_rate(self) -> float:
        return (len(self.wins) / len(self.trades) * 100.0) if self.trades else 0.0

    @property
    def gross_profit(self) -> float:
        return sum(t.pnl for t in self.wins)

    @property
    def gross_loss(self) -> float:
        return abs(sum(t.pnl for t in self.losses))

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / self.gross_loss if self.gross_loss > 0 else float("inf")

    @property
    def expectancy(self) -> float:
        return (sum(t.pnl for t in self.trades) / len(self.trades)) if self.trades else 0.0

    @property
    def max_drawdown(self) -> float:
        peak, worst = self.start_balance, 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            worst = max(worst, peak - equity)
        return worst

    @property
    def max_drawdown_pct(self) -> float:
        peak, worst = self.start_balance, 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak * 100.0)
        return worst

    @property
    def longest_losing_streak(self) -> int:
        best = run = 0
        for t in self.trades:
            run = run + 1 if t.pnl <= 0 else 0
            best = max(best, run)
        return best

    def as_dict(self) -> dict[str, float | int]:
        return {
            "bars": self.bars,
            "signals": self.signals,
            "declined": self.declined,
            "trades": len(self.trades),
            "win_rate_pct": round(self.win_rate, 2),
            "net_pnl": round(self.net_pnl, 2),
            "return_pct": round(self.return_pct, 2),
            "profit_factor": round(self.profit_factor, 3),
            "expectancy": round(self.expectancy, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "longest_losing_streak": self.longest_losing_streak,
            "end_balance": round(self.end_balance, 2),
        }

    def render(self) -> str:
        rows = [
            ("bars processed", f"{self.bars:,}"),
            ("signals / declined", f"{self.signals} / {self.declined}"),
            ("trades closed", f"{len(self.trades)}"),
            ("win rate", f"{self.win_rate:.1f}% ({len(self.wins)}W / {len(self.losses)}L)"),
            ("net pnl", f"{self.net_pnl:+,.2f} ({self.return_pct:+.2f}%)"),
            ("profit factor", f"{self.profit_factor:.2f}"),
            ("expectancy / trade", f"{self.expectancy:+,.2f}"),
            ("max drawdown", f"{self.max_drawdown:,.2f} ({self.max_drawdown_pct:.2f}%)"),
            ("longest losing streak", f"{self.longest_losing_streak}"),
            ("end balance", f"{self.end_balance:,.2f}"),
        ]
        width = max(len(k) for k, _ in rows)
        lines = [f"  {k.ljust(width)}  {v}" for k, v in rows]
        if self.declined_reasons:
            lines.append("  top rejections:")
            top = sorted(self.declined_reasons.items(), key=lambda kv: -kv[1])[:5]
            lines += [f"    {n:>4}x  {reason}" for reason, n in top]
        return "\n".join(lines)


def run_backtest(
    config: BotConfig,
    feed: BarFeed,
    symbols: list[str] | None = None,
    specs: dict[str, SymbolSpec] | None = None,
    journal: Journal | None = None,
    max_bars: int = 0,
) -> BacktestReport:
    log = obs_log.get("backtest")
    broker = PaperBroker(balance=config.engine.start_balance, slippage_points=2.0)
    if specs:  # real broker specs captured with `tbot specs` beat the defaults
        broker.specs.update({k.upper(): v for k, v in specs.items()})
    broker.connect()

    wanted = [s.upper() for s in symbols] if symbols else [s.symbol for s in config.active_symbols]
    engine = TradeEngine(config, broker, journal=journal, risk=RiskManager(config))

    series: dict[str, list[Bar]] = {}
    for scfg in config.active_symbols:
        if scfg.symbol not in wanted:
            continue
        bars = feed.history(scfg.symbol, config.engine.timeframe, max_bars)
        if not bars:
            log.warning("no bars for %s, skipping", scfg.symbol, extra={"symbol": scfg.symbol})
            continue
        rt = engine.register(scfg, broker.symbol_spec(scfg.symbol))
        rt.ingest(bars)
        series[scfg.symbol] = bars

    if not series:
        raise ValueError("backtest has no data for any configured symbol")

    report = BacktestReport(start_balance=broker.balance, end_balance=broker.balance)

    # Merge all symbols onto one timeline so portfolio-level caps and the daily
    # loss limit behave exactly as they will in live trading.
    timeline: list[tuple[datetime, str, int]] = [
        (bar.ts, sym, i) for sym, bars in series.items() for i, bar in enumerate(bars)
    ]
    timeline.sort(key=lambda t: (t[0], t[1]))

    for _, symbol, i in timeline:
        result = engine.step(symbol, i)
        report.bars += 1
        if result.signal:
            report.signals += 1
            if result.decision is not None and not result.decision:
                report.declined += 1
                key = result.decision.reason.split(",")[0][:80]
                report.declined_reasons[key] = report.declined_reasons.get(key, 0) + 1

    closed_at_end = broker.force_close_all("backtest end")
    for trade in closed_at_end:
        engine._on_closed(trade)  # noqa: SLF001 - same-package bookkeeping

    report.trades = broker.closed_trades
    report.equity_curve = broker.equity_curve
    report.end_balance = broker.balance
    if journal:
        for ts, equity in report.equity_curve:
            journal.record_equity(ts, equity)
    broker.disconnect()
    return report
