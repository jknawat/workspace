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
CREATE TABLE IF NOT EXISTS decisions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   INTEGER NOT NULL REFERENCES runs(id),
    ts       TEXT NOT NULL,
    symbol   TEXT NOT NULL,
    phase    TEXT NOT NULL DEFAULT '',
    action   TEXT NOT NULL,              -- buy | sell | wait
    score    REAL,                       -- confidence points, null if unscored
    risk_pct REAL,                       -- share of balance staked, null if none
    volume   REAL,
    price    REAL,
    why      TEXT NOT NULL DEFAULT '',
    mtf      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS observations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    ts         TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    side       TEXT NOT NULL,
    taken      INTEGER NOT NULL DEFAULT 0, -- did it become a real trade
    score      REAL,
    features   TEXT NOT NULL DEFAULT '{}',
    entry      REAL, sl REAL, tp REAL,
    -- Filled in when the position settles. Null means still open or, for a
    -- signal that was declined, never resolved.
    pnl        REAL,
    r_multiple REAL,
    outcome    TEXT
);
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signals_symbol   ON signals(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_trades_symbol    ON trades(symbol, closed_at);
CREATE INDEX IF NOT EXISTS ix_decisions_symbol ON decisions(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_obs_symbol       ON observations(symbol, ts);
"""

#: Columns added after the first release. SQLite has no "ADD COLUMN IF NOT
#: EXISTS", and an existing journal must keep its history rather than be
#: recreated, so each one is applied only when absent.
MIGRATIONS = (
    ("signals", "score", "REAL"),
    ("signals", "risk_pct", "REAL"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


#: How long an unchanged "waiting" stays suppressed before being restated.
REPEAT_A_WAIT_AFTER_SECONDS = 3600.0


def _reason_shape(why: str) -> str:
    """The reason with its numbers removed, for de-duplication only.

    Many rejection messages differ between bars by a number alone -- a session
    gate names the bar's own clock time, a cap names the current count -- so
    comparing the raw text logs a fresh row every bar and buries the log. The
    row that *is* written keeps the full wording; only restatements of the same
    kind of reason are suppressed.
    """
    return "".join(ch for ch in why if not ch.isdigit())


class Journal:
    def __init__(self, path: str | Path = "data/journal.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.run_id: int | None = None
        #: Last reason written per symbol, with when, so a repeated "wait" is
        #: neither logged thousands of times a day nor silently dropped forever.
        self._last_decision: dict[str, tuple[tuple[str, str, str], datetime]] = {}

    # ------------------------------------------------------------------ #

    def _migrate(self) -> None:
        """Add columns a newer version needs, without discarding old rows."""
        for table, column, decl in MIGRATIONS:
            existing = {
                r["name"]
                for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

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

    def record_decision(
        self,
        ts: datetime,
        symbol: str,
        action: str,
        why: str,
        *,
        phase: str = "",
        score: float | None = None,
        risk_pct: float | None = None,
        volume: float | None = None,
        price: float | None = None,
        mtf: str = "",
    ) -> bool:
        """Log what the bot decided, and why. Returns whether a row was written.

        A bar-by-bar record of "still waiting" would be thousands of identical
        rows a day and unreadable. So a ``wait`` is written only when the
        reasoning changes, which turns the log into a narrative of what the bot
        noticed rather than a heartbeat. Orders are always written: those are
        the rows that must never be missing.
        """
        key = (symbol, action, _reason_shape(why))
        if action == "wait":
            last = self._last_decision.get(symbol)
            if last is not None and last[0] == key:
                # Same reason as last time -- but repeat it occasionally anyway.
                # Pure suppression made the log look dead during a quiet week,
                # which is indistinguishable from a stopped bot to anyone
                # reading it. An hourly restatement is a pulse, not a flood.
                since = (ts - last[1]).total_seconds()
                if 0 <= since < REPEAT_A_WAIT_AFTER_SECONDS:
                    return False
        self._last_decision[symbol] = (key, ts)
        self.conn.execute(
            """INSERT INTO decisions
               (run_id, ts, symbol, phase, action, score, risk_pct, volume,
                price, why, mtf)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._run(), ts.isoformat(), symbol, phase, action, score,
                risk_pct, volume, price, why, mtf,
            ),
        )
        return True

    def record_observation(
        self,
        signal: Signal,
        *,
        taken: bool,
        score: float | None = None,
        features: dict[str, Any] | None = None,
    ) -> int:
        """One labelled example, outcome to be filled in later.

        Declined signals are recorded too. A dataset of only the trades that
        were taken can never answer whether the gates were right to decline the
        rest, which is the question any learning from this data has to settle.
        """
        cur = self.conn.execute(
            """INSERT INTO observations
               (run_id, ts, symbol, side, taken, score, features, entry, sl, tp,
                outcome)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._run(), signal.ts.isoformat(), signal.symbol,
                signal.side.value, 1 if taken else 0, score,
                json.dumps(features or {}, default=str),
                signal.price, signal.sl, signal.tp,
                "open" if taken else "not taken",
            ),
        )
        return int(cur.lastrowid or 0)

    def resolve_observation(self, trade: ClosedTrade) -> bool:
        """Attach a settled trade's result to the observation that opened it.

        Matched on symbol, side and entry price rather than timestamp: the
        broker's fill time is not the signal's bar time, and on a real fill the
        price is the more reliable join.
        """
        row = self.conn.execute(
            """SELECT id, entry, sl FROM observations
               WHERE symbol = ? AND side = ? AND taken = 1 AND outcome = 'open'
               ORDER BY ABS(entry - ?) ASC, id DESC LIMIT 1""",
            (trade.symbol, trade.side, trade.entry_price),
        ).fetchone()
        if row is None:
            return False
        # R as a price ratio, not a money one: how far it ran against how far
        # it was willing to lose. Dimensionless, so it does not depend on
        # contract size or lot count and stays comparable across symbols.
        risk = abs(float(row["entry"]) - float(row["sl"]))
        moved = trade.exit_price - trade.entry_price
        if trade.side.upper() == "SHORT":
            moved = -moved
        r_multiple = (moved / risk) if risk else None
        self.conn.execute(
            """UPDATE observations
               SET pnl = ?, r_multiple = ?, outcome = ?
               WHERE id = ?""",
            (
                trade.pnl,
                r_multiple,
                "win" if trade.pnl > 0 else "loss",
                int(row["id"]),
            ),
        )
        return True

    def recent_decisions(
        self, limit: int = 200, symbol: str = "", action: str = ""
    ) -> list[dict[str, Any]]:
        """Newest first, for the log tab."""
        sql = ["SELECT * FROM decisions WHERE 1=1"]
        args: list[Any] = []
        if symbol:
            sql.append("AND symbol = ?")
            args.append(symbol)
        if action:
            sql.append("AND action = ?")
            args.append(action)
        sql.append("ORDER BY id DESC LIMIT ?")
        args.append(max(1, min(limit, 2000)))
        rows = self.conn.execute(" ".join(sql), args).fetchall()
        return [dict(r) for r in rows]

    def score_bands(self, bands: tuple[tuple[int, int], ...]) -> list[dict[str, Any]]:
        """Settled observations grouped by score band.

        This is the feedback loop: it reports what each band of the confidence
        score actually earned on *live* trades, so the tiers can eventually be
        set on evidence nobody optimised against.
        """
        rows = self.conn.execute(
            """SELECT score, pnl FROM observations
               WHERE taken = 1 AND score IS NOT NULL AND pnl IS NOT NULL
                 AND outcome IN ('win', 'loss')"""
        ).fetchall()
        out = []
        for lo, hi in bands:
            bucket = [float(r["pnl"]) for r in rows
                      if lo <= float(r["score"]) < hi]
            wins = [p for p in bucket if p > 0]
            gross_loss = abs(sum(p for p in bucket if p <= 0))
            out.append({
                "band": f"{lo}-{hi - 1}",
                "trades": len(bucket),
                "wins": len(wins),
                "win_rate": (len(wins) / len(bucket) * 100.0) if bucket else 0.0,
                "net": sum(bucket),
                "per_trade": (sum(bucket) / len(bucket)) if bucket else 0.0,
                "profit_factor": (sum(wins) / gross_loss) if gross_loss else None,
            })
        return out

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        """Small facts that must outlive one run, such as the paper balance."""
        self.conn.execute(
            "INSERT INTO state (key, value, at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "at = excluded.at",
            (key, str(value), _now()),
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
