"""The single decision pipeline, shared by backtest, paper and live mode.

    bars -> indicators -> strategy -> risk gate -> broker -> journal

There is exactly one implementation of this sequence. In the systems this
project is a response to, the GUI, the headless connector and the backtest each
had their own copy, which is why they drifted: a filter fixed in one path stayed
broken in the others. Here, changing the pipeline changes every mode at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ..broker.base import Broker, ClosedTrade
from ..config.models import BotConfig, SymbolConfig
from ..core.indicators import Series
from ..core.types import (
    Bar,
    Decision,
    OrderRequest,
    OrderResult,
    Position,
    Signal,
    SymbolSpec,
    same_symbol,
)
from ..data.mtf import MultiTimeframe, view_for
from ..data.snapshot import Snapshot
from ..data.snapshot_store import SnapshotStore
from ..journal import Journal
from ..obs import log as obs_log
from ..risk import RiskManager
from ..strategy import Strategy, create
from ..strategy.base import BarContext
from .events import CLOSED, DECISION, DECLINED, EXIT, ORDER, SIGNAL, EventBus
from .exits import AppliedExit, ExitManager


@dataclass(slots=True)
class SymbolRuntime:
    cfg: SymbolConfig
    spec: SymbolSpec
    strategy: Strategy
    exits: ExitManager = field(default_factory=lambda: ExitManager([]))
    bars: list[Bar] = field(default_factory=list)
    ind: dict[str, Series] = field(default_factory=dict)
    mtf: MultiTimeframe = field(default_factory=MultiTimeframe)

    def ingest(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.ind = self.strategy.compute(bars) if bars else {}

    def context(
        self, i: int, spread_points: float = 0.0, snapshot: Snapshot | None = None
    ) -> BarContext:
        return BarContext(
            cfg=self.cfg, spec=self.spec, bars=self.bars, i=i, ind=self.ind,
            spread_points=spread_points, snapshot=snapshot,
            mtf=self.mtf if len(self.mtf) else None,
        )


@dataclass(slots=True)
class StepResult:
    symbol: str
    bar: Bar | None = None
    signal: Signal | None = None
    decision: Decision | None = None
    order: OrderRequest | None = None
    order_result: OrderResult | None = None
    closed: list[ClosedTrade] = field(default_factory=list)
    snapshot: Snapshot | None = None
    exits: list[AppliedExit] = field(default_factory=list)
    why: str = ""

    @property
    def entered(self) -> bool:
        return bool(self.order_result and self.order_result.ok)


class TradeEngine:
    def __init__(
        self,
        config: BotConfig,
        broker: Broker,
        journal: Journal | None = None,
        risk: RiskManager | None = None,
        snapshots: SnapshotStore | None = None,
    ) -> None:
        self.config = config
        self.broker = broker
        self.journal = journal
        self.risk = risk or RiskManager(config)
        self.snapshots = snapshots
        self.events = EventBus()
        # Flipped by the operator (Telegram /pause). Strategies keep advancing
        # and exits keep managing; only new entries are withheld.
        self.entries_enabled = True
        self.log = obs_log.get("engine")
        self.runtimes: dict[str, SymbolRuntime] = {}
        self._known_tickets: set[int] = set()
        self._last_balance: float | None = None

    # ------------------------------------------------------------------ #
    # Wiring
    # ------------------------------------------------------------------ #

    def register(self, scfg: SymbolConfig, spec: SymbolSpec | None = None) -> SymbolRuntime:
        resolved = spec or self.broker.symbol_spec(scfg.symbol)
        strategy = create(scfg, resolved)
        rt = SymbolRuntime(
            cfg=scfg,
            spec=resolved,
            strategy=strategy,
            exits=ExitManager.from_config(scfg.exits),
        )
        self.runtimes[scfg.symbol] = rt
        self.log.info(
            "registered %s via %s (%d filters, warmup %d)",
            scfg.symbol, scfg.strategy,
            len(getattr(strategy, "filters", []) or []), strategy.warmup,
            extra={"symbol": scfg.symbol, "strategy": scfg.strategy},
        )
        return rt

    def _runtime(self, symbol: str) -> SymbolRuntime:
        rt = self.runtimes.get(symbol)
        if rt is None:
            for name, candidate in self.runtimes.items():
                if same_symbol(name, symbol):
                    return candidate
            raise KeyError(f"{symbol} is not registered")
        return rt

    def register_all(self) -> None:
        for scfg in self.config.active_symbols:
            self.register(scfg)

    # ------------------------------------------------------------------ #
    # One bar, one symbol
    # ------------------------------------------------------------------ #

    def step(self, symbol: str, i: int | None = None) -> StepResult:
        rt = self._runtime(symbol)
        if not rt.bars:
            return StepResult(symbol=rt.cfg.symbol)
        idx = len(rt.bars) - 1 if i is None else i
        bar = rt.bars[idx]
        out = StepResult(symbol=rt.cfg.symbol, bar=bar)

        # 1. Let the simulator settle stops/targets on this bar before any new
        #    decision, so an entry can never be closed by its own entry bar.
        on_bar = getattr(self.broker, "on_bar", None)
        if callable(on_bar):
            for trade in on_bar(rt.cfg.symbol, bar):
                out.closed.append(trade)
                self._on_closed(trade)

        spread = self.broker.spread_points(rt.cfg.symbol) if self._live_quotes() else 0.0
        snapshot = self.snapshot_for(rt.cfg.symbol, bar.ts)
        out.snapshot = snapshot
        ctx = rt.context(idx, spread, snapshot)

        # 2. Manage what is already open, before considering anything new. A
        #    partial close here can free the capacity a fresh entry needs.
        if len(rt.exits):
            live = self.broker.positions()
            rt.exits.forget({p.ticket for p in live})
            out.exits = rt.exits.manage(live, ctx, self.broker)
            for applied in out.exits:
                self.events.publish(
                    EXIT, rt.cfg.symbol,
                    action=applied.action.kind,
                    ticket=applied.action.ticket,
                    reason=applied.action.reason,
                    sl=applied.action.sl,
                    volume=applied.action.volume,
                    ok=applied.ok,
                )
            if any(a.ok and a.action.is_close for a in out.exits):
                self._drain_closes(out)

        # 3. Strategy decision, with MT5's structure snapshot when one is fresh.
        signal = rt.strategy.on_bar(ctx)
        out.why = self.explain(rt.cfg.symbol)
        self.events.publish(
            DECISION, rt.cfg.symbol,
            why=out.why,
            phase=str(rt.strategy.state_summary().get("phase", "?")),
            price=bar.close,
            bar_ts=bar.ts.isoformat(),
            mtf=rt.mtf.summary() if len(rt.mtf) else "",
            signal=bool(signal),
        )
        if signal is None:
            return out
        out.signal = signal
        self.events.publish(
            SIGNAL, signal.symbol,
            side=signal.side.value, price=signal.price, sl=signal.sl, tp=signal.tp,
            strategy=signal.strategy, reason=signal.reason, rr=round(signal.rr, 2),
        )

        if not self.entries_enabled:
            paused = Decision.no("paused by operator")
            out.decision = paused
            if self.journal:
                self.journal.record_signal(signal, paused, None)
            self.events.publish(
                DECLINED, signal.symbol, side=signal.side.value, reason=paused.reason
            )
            self.log.info(
                "signal held: %s %s (paused)", signal.symbol, signal.side.value,
                extra={"symbol": signal.symbol, "event": "paused"},
            )
            return out

        # 4. Risk gate.
        account = self.broker.account()
        positions: list[Position] = self.broker.positions()
        decision, order = self.risk.approve(signal, rt.spec, account, positions)
        out.decision, out.order = decision, order
        if self.journal:
            self.journal.record_signal(signal, decision, order)
        if not decision or order is None:
            self.log.info(
                "signal declined %s %s: %s",
                signal.symbol, signal.side.value, decision.reason,
                extra={"symbol": signal.symbol, "event": "declined", "reason": decision.reason},
            )
            self.events.publish(
                DECLINED, signal.symbol,
                side=signal.side.value, reason=decision.reason,
            )
            return out

        # 5. Route.
        result = self.broker.market_order(order)
        out.order_result = result
        level = self.log.info if result.ok else self.log.error
        level(
            "%s %s %.2f lots @ %.5f sl %.5f tp %.5f -> %s",
            signal.side.value, signal.symbol, order.volume, result.price,
            order.sl, order.tp, result.message,
            extra={
                "symbol": signal.symbol,
                "event": "order",
                "ok": result.ok,
                "volume": order.volume,
                "risk_money": decision.detail.get("risk_money"),
                "reason": signal.reason,
            },
        )
        self.events.publish(
            ORDER, signal.symbol,
            side=signal.side.value, volume=order.volume, price=result.price,
            sl=order.sl, tp=order.tp, ok=result.ok, message=result.message,
            risk_money=decision.detail.get("risk_money"), reason=signal.reason,
        )
        return out

    # ------------------------------------------------------------------ #
    # Bookkeeping
    # ------------------------------------------------------------------ #

    def _drain_closes(self, out: StepResult) -> None:
        """Pick up settlements an exit policy caused, so the journal and the
        daily-loss counter stay correct."""
        drain = getattr(self.broker, "drain_closed", None)
        if not callable(drain):
            return  # live broker: reconcile_live_positions covers this instead
        for trade in drain():
            out.closed.append(trade)
            self._on_closed(trade)

    def _on_closed(self, trade: ClosedTrade) -> None:
        self.risk.record_close(trade.pnl, trade.closed_at.date())
        if self.journal:
            self.journal.record_trade(trade)
        self.log.info(
            "closed %s %s %.2f lots pnl %.2f (%s)",
            trade.symbol, trade.side, trade.volume, trade.pnl, trade.reason,
            extra={"symbol": trade.symbol, "event": "close", "pnl": trade.pnl,
                   "reason": trade.reason},
        )
        self.events.publish(
            CLOSED, trade.symbol,
            side=trade.side, volume=trade.volume, pnl=round(trade.pnl, 2),
            entry=trade.entry_price, exit=trade.exit_price, reason=trade.reason,
            strategy=trade.strategy,
        )

    def reconcile_live_positions(self) -> list[int]:
        """Detect positions closed by the broker (stop, target, or by hand).

        Live mode has no callback: a stop-out happens on the broker side. Here
        the engine diffs ticket sets between polls and attributes the balance
        delta to whatever disappeared, so the daily-loss kill-switch stays
        correct even when the bot did not close the trade itself.
        """
        current = {p.ticket for p in self.broker.positions()}
        vanished = sorted(self._known_tickets - current)
        balance = self.broker.account().balance
        if vanished and self._last_balance is not None:
            delta = balance - self._last_balance
            self.risk.record_close(delta, date.today())
            self.log.info(
                "reconciled %d closed position(s), balance delta %.2f",
                len(vanished), delta,
                extra={"event": "reconcile", "tickets": vanished, "pnl": delta},
            )
        self._known_tickets = current
        self._last_balance = balance
        return vanished

    def _live_quotes(self) -> bool:
        return self.config.engine.mode != "backtest"

    # ------------------------------------------------------------------ #
    # MT5 structure snapshots
    # ------------------------------------------------------------------ #

    def refresh_mtf(self, symbol: str, feed, bars_per_timeframe: int = 260) -> MultiTimeframe:
        """Rebuild a symbol's higher/lower timeframe context from the feed.

        One failure per timeframe is survivable: a timeframe that cannot be
        fetched is simply absent, and the gates treat absent as "not ready"
        rather than as agreement.
        """
        rt = self._runtime(symbol)
        views = {}
        for tf in self.config.engine.context_timeframes:
            try:
                bars = feed.history(rt.cfg.symbol, tf, bars_per_timeframe)
            except Exception as exc:  # noqa: BLE001 - one timeframe must not stop the rest
                self.log.warning(
                    "context timeframe %s unavailable for %s: %s", tf, symbol, exc,
                    extra={"symbol": symbol, "event": "mtf_unavailable"},
                )
                continue
            views[tf] = view_for(tf, bars)
        rt.mtf = MultiTimeframe(views)
        return rt.mtf

    def explain(self, symbol: str) -> str:
        """Why this symbol is doing what it is doing, in one line.

        The dashboard and the journal both need a plain answer to "why buy, why
        sell, why wait", and the strategies already know -- this just asks them
        and adds the context read.
        """
        rt = self._runtime(symbol)
        state = rt.strategy.state_summary()
        phase = str(state.get("phase", "?"))
        side = state.get("side")
        reject = str(state.get("last_reject") or "")

        if phase == "COOLDOWN":
            why = "resting after the last trade"
        elif phase == "ARMED":
            pulled = state.get("pullback_count")
            why = f"armed {side}, waiting for the pullback"
            if pulled is not None:
                why += f" ({pulled} bar(s) so far)"
        elif phase == "WINDOW":
            trigger = state.get("trigger")
            why = f"armed {side}, waiting for a break of {trigger}"
        else:
            why = "waiting for a setup"
            if reject:
                why += f"; last one was turned down because {reject}"
        if len(rt.mtf):
            why += f"  [{rt.mtf.summary()}]"
        return why

    def snapshot_for(self, symbol: str, now: datetime | None = None) -> Snapshot | None:
        """The symbol's SMC/ICT snapshot, only if present, usable and fresh.

        ``None`` is returned for every failure mode -- not configured, no file,
        terminal stopped, structure stale. Callers must treat that as "no
        evidence", never as "no objection".
        """
        if self.snapshots is None:
            return None
        return self.snapshots.fresh(symbol, now)

    def snapshot_state(self) -> dict[str, dict[str, object]]:
        """Per-symbol snapshot health, for status output and diagnostics."""
        if self.snapshots is None:
            return {}
        out: dict[str, dict[str, object]] = {}
        for symbol in self.runtimes:
            snap = self.snapshots.get(symbol)
            if snap is None:
                out[symbol] = {"available": False, "path": str(self.snapshots.path_for(symbol))}
                continue
            age = snap.age(datetime.now(timezone.utc))
            out[symbol] = {
                "available": True,
                "status": snap.status,
                "timeframe": snap.timeframe,
                "as_of": snap.as_of.isoformat() if snap.as_of else None,
                "age_seconds": None if age is None else round(age.total_seconds()),
                "bias": snap.bias(),
                "records": snap.counts(),
                "problems": snap.problems(),
            }
        return out

    def state(self) -> dict[str, dict[str, object]]:
        snapshots = self.snapshot_state()
        out: dict[str, dict[str, object]] = {}
        for sym, rt in self.runtimes.items():
            summary = dict(rt.strategy.state_summary())
            summary["why"] = self.explain(sym)
            if len(rt.mtf):
                summary["mtf"] = rt.mtf.to_dict()
            if sym in snapshots:
                summary["snapshot"] = snapshots[sym]
            out[sym] = summary
        return out
