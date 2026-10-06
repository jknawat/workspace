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

from ..broker.base import Broker, BrokerError
from ..config.models import BotConfig
from ..data.feed import BarFeed
from ..data.snapshot_store import SnapshotStore
from ..journal import Journal
from ..obs import log as obs_log
from ..risk import RiskManager
from . import carryover
from .chartdata import chart_payload
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
        chart_sinks: list[Any] | None = None,
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
        self.chart_sinks = list(chart_sinks or [])
        self._last_equity_at: datetime | None = None
        #: Symbols whose strategy state has been rebuilt from recent bars.
        self._replayed: set[str] = set()
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

    def _carry_over_positions(self) -> None:
        """Bring back simulated positions left open by the previous run.

        Then replay the bars that passed while the bot was down, so a stop or
        target hit during the downtime settles at the price and time it really
        settled at, instead of the position reappearing as though nothing had
        happened in between.
        """
        if self.journal is None or self.config.engine.mode != "paper":
            return
        broker = self.broker
        if not hasattr(broker, "_positions"):
            return  # not the simulator; live positions live at the broker

        rows = carryover.load(self.journal)
        if not rows:
            return
        restored = carryover.restore(broker, rows)
        if not restored:
            return

        # settle_missed feeds every bar through on_bar, which also sets the
        # simulator's last-seen price for the symbol, so nothing needs priming
        # separately.
        bars_by_symbol = {}
        for pos in restored:
            rt = self.engine.runtimes.get(pos.symbol)
            if rt is not None and rt.bars:
                bars_by_symbol[pos.symbol] = rt.bars

        self.log.info(
            "restored %d simulated position(s) from the previous run",
            len(restored),
            extra={"event": "carryover", "positions": len(restored)},
        )
        for trade in carryover.settle_missed(broker, restored, bars_by_symbol):
            self.log.info(
                "a carried-over position had already settled while the bot was "
                "off: %s %s pnl %.2f (%s)",
                trade.symbol, trade.side, trade.pnl, trade.reason,
                extra={"event": "carryover_settled", "symbol": trade.symbol},
            )
            self.engine._on_closed(trade)  # noqa: SLF001 - same package
        carryover.save(self.journal, broker)

    def _preflight_orders(self) -> None:
        """Refuse to start live if the broker will reject every order.

        Two live orders were lost to a malformed comment field, and the failure
        only appeared on the first signal -- hours after start, with the setups
        already gone. A bot that cannot place an order should say so while
        someone is still watching the window, not discover it at 3am.

        Only fatal problems stop the start. A closed market or no free margin
        are conditions of the moment and pass with a warning.
        """
        if self.config.engine.mode != "live":
            return
        problems: list[str] = []
        for symbol in self.engine.runtimes:
            try:
                fatal, message = self.broker.preflight(symbol)
            except Exception as exc:  # noqa: BLE001 - a check must not crash the bot
                self.log.warning(
                    "order preflight for %s could not run: %s", symbol, exc,
                    extra={"symbol": symbol, "event": "preflight_error"},
                )
                continue
            if fatal:
                problems.append(message)
                self.log.error(
                    "order preflight FAILED: %s", message,
                    extra={"symbol": symbol, "event": "preflight_failed"},
                )
            else:
                self.log.info(
                    "order preflight %s", message,
                    extra={"symbol": symbol, "event": "preflight"},
                )
        if problems:
            raise BrokerError(
                "the broker will refuse every order as this request is built:\n  "
                + "\n  ".join(problems)
                + "\nNothing was traded. Fix this before starting again."
            )

    def prepare(self) -> None:
        self.engine.register_all()
        if not self.engine.runtimes:
            raise RuntimeError("no enabled symbols to trade")
        self._carry_over_positions()
        self._preflight_orders()
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

    def _publish_chart(self) -> None:
        """Push the chart and gate readings to whoever is displaying them.

        Computed on the trading thread and handed over as a finished snapshot.
        The web thread must never reach into the engine itself: neither the
        runtimes nor the MT5 handle are safe to read from another thread while
        a bar is being processed.
        """
        if not self.chart_sinks:
            return
        try:
            payload = chart_payload(self.engine, self.journal)
        except Exception as exc:  # noqa: BLE001 - a panel must not stop trading
            self.log.error("chart payload failed: %s", exc)
            return
        for sink in self.chart_sinks:
            try:
                sink(payload)
            except Exception as exc:  # noqa: BLE001
                self.log.error("chart sink failed: %s", exc)

    def _save_positions(self) -> None:
        """Keep the open simulated positions on disk, so a stop keeps them.

        Written every poll rather than at shutdown: a crash, a kill or a power
        cut would otherwise lose exactly the trade this exists to protect.
        """
        if self.journal is None or self.config.engine.mode != "paper":
            return
        if not hasattr(self.broker, "_positions"):
            return
        with contextlib.suppress(Exception):
            carryover.save(self.journal, self.broker)

    def _record_equity(self, status: dict) -> None:
        """Keep an equity history for paper and live runs.

        The journal only ever held an equity curve for backtests, so the thing
        the forward test exists to produce -- the shape of the account over
        weeks -- was not being written down anywhere. One point per poll is
        plenty at a 15-second cadence and costs a few hundred KB a year.
        """
        if self.journal is None:
            return
        equity = status.get("equity")
        if not isinstance(equity, (int, float)):
            return
        now = datetime.now(timezone.utc)
        if self._last_equity_at and (now - self._last_equity_at).total_seconds() < 60:
            return
        self._last_equity_at = now
        with contextlib.suppress(Exception):
            self.journal.record_equity(now, float(equity))

    def _publish_status(self) -> None:
        self._publish_chart()
        status = self.status()
        self._record_equity(status)
        self._save_positions()
        for sink in self.status_sinks:
            try:
                sink(status)
            except Exception as exc:  # noqa: BLE001 - a watcher must not stop trading
                self.log.error("status sink failed: %s", exc)
        self.engine.events.publish(STATUS, **{k: status[k] for k in ("balance", "equity")})

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #

    def _replay_strategy(self, symbol: str, rt: Any) -> None:
        """Rebuild the strategy's state by replaying the bars it missed.

        A strategy is a state machine -- scanning, armed, waiting for a
        pullback, waiting for a breakout -- and starting fresh throws all of
        that away. A setup two bars from triggering becomes a setup that never
        existed, and the bot waits for a whole new crossover. Restarting ten
        times in a day, as happened while this was being built, discards ten
        chances.

        Rather than persisting the state machine -- whose internals are bar
        *indices* into a window that shifts between runs -- the bars are simply
        fed through it again. The machine is deterministic, so replaying the
        recent past puts it exactly where the market left it.

        The signals this produces are discarded. They belong to bars that
        closed while the bot was down, and acting on them would be trading the
        past. Only the state survives, and the newest bar is then handled
        normally by the caller.

        ``on_bar`` is called directly rather than through ``engine.step``, so
        no order can be sent from here however the replay turns out.
        """
        bars = rt.bars
        depth = int(self.config.engine.replay_bars)
        if depth <= 0 or len(bars) < 2:
            return
        start = max(rt.strategy.warmup, len(bars) - 1 - depth)
        if start >= len(bars) - 1:
            return

        spread = 0.0
        with contextlib.suppress(Exception):
            spread = self.broker.spread_points(symbol)

        replayed = 0
        for i in range(start, len(bars) - 1):
            # Snapshot deliberately None: MT5's structure snapshot describes
            # only the present, so handing today's to a bar from an hour ago
            # would be lookahead. Gates that read it fail closed, which keeps
            # the replay conservative.
            ctx = rt.context(i, spread, None)
            with contextlib.suppress(Exception):
                rt.strategy.on_bar(ctx)  # signals discarded on purpose
            replayed += 1

        state = rt.strategy.state_summary()
        phase = str(state.get("phase", "?"))
        if phase != "SCANNING":
            self.log.info(
                "replayed %d bars for %s; resumed mid-setup: %s %s",
                replayed, symbol, phase, state.get("side") or "",
                extra={"symbol": symbol, "event": "replay", "phase": phase},
            )
        else:
            self.log.info(
                "replayed %d bars for %s; nothing in progress",
                replayed, symbol,
                extra={"symbol": symbol, "event": "replay", "phase": phase},
            )

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
            if symbol not in self._replayed:
                self._replayed.add(symbol)
                self._replay_strategy(symbol, rt)

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
