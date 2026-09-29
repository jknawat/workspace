"""SQLite trade journal.

Every signal is stored -- including the rejected ones, with the reason. A bot
that only records its fills can never answer the question that actually matters
after a bad month: *what did it decline to do, and why?*

SQLite (stdlib) rather than a server: the journal must survive a crash, be
queryable with any tool, and need zero operational setup.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..broker.base import ClosedTrade
from ..core.types import Decision, OrderRequest, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    mode        TEXT NOT NULL,
    broker      TEXT NOT NULL,
    note        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id),
    ts        TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    side      TEXT NOT NULL,
    strategy  TEXT NOT NULL,
    price     REAL NOT NULL,
    sl        REAL NOT NULL,
    tp        REAL NOT NULL,
    reason    TEXT NOT NULL,
    approved  INTEGER NOT NULL,
    decision  TEXT NOT NULL,
    volume    REAL,
    meta      TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    volume      REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price  REAL NOT NULL,
    opened_at   TEXT NOT NULL,
    closed_at   TEXT NOT NULL,
    pnl         REAL NOT NULL,
    reason      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equity (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    ts     TEXT NOT NULL,
    equity REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signals_symbol ON signals(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_trades_symbol  ON trades(symbol, closed_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Journal:
    def __init__(self, path: str | Path = "data/journal.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.run_id: int | None = None

    # ------------------------------------------------------------------ #

    def start_run(self, mode: str, broker: str, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, mode, broker, note) VALUES (?, ?, ?, ?)",
            (_now(), mode, broker, note),
        )
        self.run_id = int(cur.lastrowid or 0)
        return self.run_id

    def finish_run(self) -> None:
        if self.run_id is not None:
            self.conn.execute(
                "UPDATE runs SET finished_at = ? WHERE id = ?", (_now(), self.run_id)
            )

    def record_signal(
        self, signal: Signal, decision: Decision, order: OrderRequest | None
    ) -> None:
        self.conn.execute(
            """INSERT INTO signals
               (run_id, ts, symbol, side, strategy, price, sl, tp, reason,
                approved, decision, volume, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._run(),
                signal.ts.isoformat(),
                signal.symbol,
                signal.side.value,
                signal.strategy,
                signal.price,
                signal.sl,
                signal.tp,
                signal.reason,
                1 if decision.passed else 0,
                decision.reason,
                order.volume if order else None,
                json.dumps({**signal.meta, **decision.detail}, default=str),
            ),
        )

    def record_trade(self, trade: ClosedTrade) -> None:
        self.conn.execute(
            """INSERT INTO trades
               (run_id, symbol, side, strategy, volume, entry_price, exit_price,
                opened_at, closed_at, pnl, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._run(),
                trade.symbol,
                trade.side,
                trade.strategy,
                trade.volume,
                trade.entry_price,
                trade.exit_price,
                trade.opened_at.isoformat(),
                trade.closed_at.isoformat(),
                trade.pnl,
                trade.reason,
            ),
        )

    def record_equity(self, ts: datetime, equity: float) -> None:
        self.conn.execute(
            "INSERT INTO equity (run_id, ts, equity) VALUES (?,?,?)",
            (self._run(), ts.isoformat(), equity),
        )

    # ------------------------------------------------------------------ #

    def rejection_counts(self, run_id: int | None = None) -> list[tuple[str, str, int]]:
        """(symbol, reason, count) for declined signals -- the tuning feedback loop."""
        rid = run_id or self.run_id
        rows = self.conn.execute(
            """SELECT symbol, decision, COUNT(*) AS n FROM signals
               WHERE approved = 0 AND (? IS NULL OR run_id = ?)
               GROUP BY symbol, decision ORDER BY n DESC""",
            (rid, rid),
        ).fetchall()
        return [(r["symbol"], r["decision"], r["n"]) for r in rows]

    def stats(self, run_id: int | None = None) -> dict[str, Any]:
        rid = run_id or self.run_id
        row = self.conn.execute(
            """SELECT COUNT(*) AS trades,
                      COALESCE(SUM(pnl), 0) AS net,
                      COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins
               FROM trades WHERE (? IS NULL OR run_id = ?)""",
            (rid, rid),
        ).fetchone()
        trades = int(row["trades"])
        return {
            "trades": trades,
            "wins": int(row["wins"]),
            "net_pnl": float(row["net"]),
            "win_rate": (int(row["wins"]) / trades * 100.0) if trades else 0.0,
        }

    def _run(self) -> int:
        if self.run_id is None:
            raise RuntimeError("Journal.start_run() must be called first")
        return self.run_id

    def close(self) -> None:
        with closing(self.conn):
            self.finish_run()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
