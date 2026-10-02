"""Live / paper runner.

A single-threaded polling loop, deliberately. The previous generation of this
kind of bot ran its decision logic on a GUI worker thread and shared mutable
strategy state with the render loop, which is how "the chart says ARMED but the
log says SCANNING" bugs are born. Here one thread owns all state; watchers are
*readers* of :meth:`status` and of the event bus.

The loop is bar-driven, not tick-driven: work happens once per newly closed bar
per symbol. Polling the same bar twice cannot double-enter, because the engine
only evaluates timestamps it has not seen.

**Remote control never runs on another thread.** Telegram's poller only sets
flags on a :class:`ControlState`; they are read here, at the top of a cycle, and
acted on by this thread. So "close everything" from a phone takes the same path
as any other close, and there is still exactly one thread touching positions.

Pausing stops *new entries* only. Strategies keep advancing their state
machines and exit policies keep managing open trades — a pause that froze the
state machines would leave them stale and confused on resume.
"""

from __future__ import annotations

import contextlib
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..broker.base import Broker
from ..config.models import BotConfig
from ..data.feed import BarFeed
from ..data.snapshot_store import SnapshotStore
from ..journal import Journal
from ..obs import log as obs_log
from ..risk import RiskManager
from .core import TradeEngine
from .events import ERROR, STARTED, STATUS, STOPPED

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400,
}

StatusSink = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class RunnerStats:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    polls: int = 0
    bars_processed: int = 0
    signals: int = 0
    orders: int = 0
    errors: int = 0


class Runner:
    def __init__(
        self,
        config: BotConfig,
        broker: Broker,
        feed: BarFeed,
        journal: Journal | None = None,
        snapshots: SnapshotStore | None = None,
        control: Any | None = None,          # ControlState, kept untyped to avoid a cycle
        status_sinks: list[StatusSink] | None = None,
        max_iterations: int = 0,
    ) -> None:
        self.config = config
        self.broker = broker
        self.feed = feed
        self.journal = journal
        self.engine = TradeEngine(
            config, broker, journal=journal, risk=RiskManager(config), snapshots=snapshots
        )
        self.control = control
        self.status_sinks = list(status_sinks or [])
        self.log = obs_log.get("runner")
        self.stats = RunnerStats()
        self.max_iterations = max_iterations
        self._stop = False
        self._last_seen: dict[str, datetime] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def install_signal_handlers(self) -> None:
        def handle(signum: int, _frame: object) -> None:
            self.log.warning("signal %s received, finishing current poll", signum)
            self._stop = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            # Installing a handler fails off the main thread; that is fine.
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, handle)

    def stop(self) -> None:
        self._stop = True

    @property
    def paused(self) -> bool:
        return bool(self.control is not None and self.control.paused)

    def prepare(self) -> None:
        self.engine.register_all()
        if not self.engine.runtimes:
            raise RuntimeError("no enabled symbols to trade")
        account = self._account_safely()
        self.log.info(
            "%s mode on %s: %d symbol(s), %s",
            self.config.engine.mode, self.broker.name,
            len(self.engine.runtimes), self.config.engine.timeframe,
            extra={"event": "start", "mode": self.config.engine.mode},
        )
        self.engine.events.publish(
            STARTED,
            mode=self.config.engine.mode,
            broker=self.broker.name,
            symbols=len(self.engine.runtimes),
            balance=account.balance if account else 0.0,
            timeframe=self.config.engine.timeframe,
        )
        self._publish_status()

    # ------------------------------------------------------------------ #
    # Remote control
    # ------------------------------------------------------------------ #

    def stop_file_present(self) -> bool:
        """True once the stop file exists.

        This is the whole mechanism behind stop.bat: the batch file writes a
        file, and the loop notices on its next cycle and finishes cleanly --
        closing nothing, cancelling nothing, just declining to start anything
        new. Killing the process would be faster and would leave the journal
        mid-write.
        """
        path = self.config.engine.stop_file
        return bool(path) and Path(path).exists()

    def apply_control(self) -> None:
        """Read operator flags and act on them, on this thread."""
        if self.stop_file_present():
            if not self._stop:
                self.log.warning(
                    "stop file %s found, finishing this cycle",
                    self.config.engine.stop_file, extra={"event": "stop_file"},
                )
            self._stop = True
        if self.control is None:
            return
        if self.control.take("close_all_requested"):
            self.close_all("operator request")
        if self.control.take("status_requested"):
            self._publish_status()
        if self.control.take("stop_requested"):
            self.log.warning("stop requested by operator")
            self._stop = True
        self.engine.entries_enabled = not self.control.paused

    def close_all(self, reason: str = "manual") -> int:
        """Close every open position now. Used by /closeall and by shutdown."""
        closed = 0
        for pos in self.broker.positions():
            result = self.broker.close_position(pos.ticket, reason=reason)
            if result.ok:
                closed += 1
            else:
                self.log.error(
                    "close failed for #%d: %s", pos.ticket, result.message,
                    extra={"symbol": pos.symbol, "event": "close_failed"},
                )
        drain = getattr(self.broker, "drain_closed", None)
        if callable(drain):
            for trade in drain():
                self.engine._on_closed(trade)  # noqa: SLF001 - same-package bookkeeping
        if closed:
            self.log.warning(
                "closed %d position(s): %s", closed, reason, extra={"event": "close_all"}
            )
        return closed

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def _account_safely(self):
        try:
            return self.broker.account()
        except Exception as exc:  # noqa: BLE001 - status must never raise
            self.log.error("account read failed: %s", exc)
            return None

    def status(self) -> dict[str, Any]:
        account = self._account_safely()
        positions: list[dict[str, Any]] = []
        for pos in self.broker.positions():
            rt = self.engine.runtimes.get(pos.symbol)
            pnl = None
            if rt is not None and rt.bars:
                try:
                    pnl = round(pos.unrealised(rt.bars[-1].close, rt.spec), 2)
                except Exception:  # noqa: BLE001 - a display field is not worth a crash
                    pnl = None
            positions.append(
                {
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "volume": pos.volume,
                    "entry": pos.entry_price,
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "pnl": pnl,
                    "ticket": pos.ticket,
                    "opened_at": pos.opened_at.isoformat(),
                }
            )
        book = self.engine.risk.book
        return {
            "started": True,
            "mode": self.config.engine.mode,
            "broker": self.broker.name,
            "timeframe": self.config.engine.timeframe,
            "paused": self.paused,
            "balance": round(account.balance, 2) if account else None,
            "equity": round(account.equity, 2) if account else None,
            "day_pnl": round(book.realised, 2),
            "day_trades": book.trades,
            "halted": self.engine.risk.halted_reason,
            "positions": positions,
            "phases": self.engine.state(),
            "symbols": list(self.engine.runtimes),
            "polls": self.stats.polls,
            "orders": self.stats.orders,
            "errors": self.stats.errors,
            "started_at": self.stats.started_at.isoformat(),
        }

    def _publish_status(self) -> None:
        status = self.status()
        for sink in self.status_sinks:
            try:
                sink(status)
            except Exception as exc:  # noqa: BLE001 - a watcher must not stop trading
                self.log.error("status sink failed: %s", exc)
        self.engine.events.publish(STATUS, **{k: status[k] for k in ("balance", "equity")})

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #

    def poll_once(self) -> int:
        """One pass over every symbol. Returns the number of new bars handled."""
        handled = 0
        self.stats.polls += 1
        self.apply_control()

        for symbol, rt in self.engine.runtimes.items():
            try:
                bars = self.feed.history(
                    symbol, self.config.engine.timeframe, self.config.engine.warmup_bars
                )
            except Exception as exc:  # noqa: BLE001 - a feed hiccup must not kill the loop
                self.stats.errors += 1
                self.log.error("feed error for %s: %s", symbol, exc, extra={"symbol": symbol})
                self.engine.events.publish(ERROR, symbol, message=f"feed error: {exc}")
                continue
            if not bars:
                continue
            latest = bars[-1].ts
            if self._last_seen.get(symbol) == latest:
                continue  # same closed bar as last poll: nothing to decide
            self._last_seen[symbol] = latest
            rt.ingest(bars)
            if self.config.engine.context_timeframes:
                self.engine.refresh_mtf(symbol, self.feed)

            try:
                result = self.engine.step(symbol)
            except Exception as exc:  # one bad symbol must not stop the rest
                self.stats.errors += 1
                self.log.exception("step failed for %s", symbol, extra={"symbol": symbol})
                self.engine.events.publish(ERROR, symbol, message=str(exc))
                continue

            handled += 1
            self.stats.bars_processed += 1
            if result.signal:
                self.stats.signals += 1
            if result.entered:
                self.stats.orders += 1
            if result.why:
                self.log.info(
                    "%s", result.why,
                    extra={"symbol": symbol, "event": "decision"},
                )

        if self.config.engine.mode == "live":
            self.engine.reconcile_live_positions()
        if handled:
            self._publish_status()
        return handled

    def run(self) -> RunnerStats:
        self.prepare()
        interval = max(1.0, float(self.config.engine.poll_seconds))
        iterations = 0
        status_every = max(1, int(60.0 / interval))  # a heartbeat about once a minute
        try:
            while not self._stop:
                started = time.monotonic()
                self.poll_once()
                iterations += 1
                if iterations % status_every == 0:
                    self._publish_status()
                if self.max_iterations and iterations >= self.max_iterations:
                    break
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, interval - elapsed))
        finally:
            self.log.info(
                "stopped after %d polls, %d bars, %d orders, %d errors",
                self.stats.polls, self.stats.bars_processed,
                self.stats.orders, self.stats.errors,
                extra={"event": "stop"},
            )
            self.engine.events.publish(
                STOPPED,
                reason="operator" if self._stop else "completed",
                polls=self.stats.polls,
                orders=self.stats.orders,
                errors=self.stats.errors,
            )
        return self.stats
