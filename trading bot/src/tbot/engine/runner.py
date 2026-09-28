"""Live / paper runner.

A single-threaded polling loop, deliberately. The previous generation of this
kind of bot ran its decision logic on a GUI worker thread and shared mutable
strategy state with the render loop, which is how "the chart says ARMED but the
log says SCANNING" bugs are born. Here one thread owns all state; any UI is a
*reader* of :meth:`TradeEngine.state`.

The loop is bar-driven, not tick-driven: work happens once per newly closed bar
per symbol. Polling the same bar twice cannot double-enter, because the engine
only evaluates timestamps it has not seen.
"""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..broker.base import Broker
from ..config.models import BotConfig
from ..data.feed import BarFeed
from ..journal import Journal
from ..obs import log as obs_log
from ..risk import RiskManager
from .core import TradeEngine

TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400,
}


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
        max_iterations: int = 0,
    ) -> None:
        self.config = config
        self.broker = broker
        self.feed = feed
        self.journal = journal
        self.engine = TradeEngine(config, broker, journal=journal, risk=RiskManager(config))
        self.log = obs_log.get("runner")
        self.stats = RunnerStats()
        self.max_iterations = max_iterations
        self._stop = False
        self._last_seen: dict[str, datetime] = {}

    # ------------------------------------------------------------------ #

    def install_signal_handlers(self) -> None:
        def handle(signum: int, _frame: object) -> None:
            self.log.warning("signal %s received, finishing current poll", signum)
            self._stop = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handle)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                pass

    def stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------------ #

    def prepare(self) -> None:
        self.engine.register_all()
        if not self.engine.runtimes:
            raise RuntimeError("no enabled symbols to trade")
        self.log.info(
            "%s mode on %s: %d symbol(s), %s",
            self.config.engine.mode, self.broker.name,
            len(self.engine.runtimes), self.config.engine.timeframe,
            extra={"event": "start", "mode": self.config.engine.mode},
        )

    def poll_once(self) -> int:
        """One pass over every symbol. Returns the number of new bars handled."""
        handled = 0
        self.stats.polls += 1
        for symbol, rt in self.engine.runtimes.items():
            try:
                bars = self.feed.history(
                    symbol, self.config.engine.timeframe, self.config.engine.warmup_bars
                )
            except Exception as exc:  # noqa: BLE001 - a feed hiccup must not kill the loop
                self.stats.errors += 1
                self.log.error("feed error for %s: %s", symbol, exc, extra={"symbol": symbol})
                continue
            if not bars:
                continue
            latest = bars[-1].ts
            if self._last_seen.get(symbol) == latest:
                continue  # same closed bar as last poll: nothing to decide
            self._last_seen[symbol] = latest
            rt.ingest(bars)

            result = self.engine.step(symbol)
            handled += 1
            self.stats.bars_processed += 1
            if result.signal:
                self.stats.signals += 1
            if result.entered:
                self.stats.orders += 1
        if self.config.engine.mode == "live":
            self.engine.reconcile_live_positions()
        return handled

    def run(self) -> RunnerStats:
        self.prepare()
        interval = max(1.0, float(self.config.engine.poll_seconds))
        iterations = 0
        while not self._stop:
            started = time.monotonic()
            self.poll_once()
            iterations += 1
            if self.max_iterations and iterations >= self.max_iterations:
                break
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))
        self.log.info(
            "stopped after %d polls, %d bars, %d orders, %d errors",
            self.stats.polls, self.stats.bars_processed, self.stats.orders, self.stats.errors,
            extra={"event": "stop"},
        )
        return self.stats
