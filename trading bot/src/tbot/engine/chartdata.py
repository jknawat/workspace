"""What the live chart and the go/no-go panel need, assembled in one place.

Everything here is **read-only**. It inspects the engine's runtimes, evaluates
the filter chain for display, and never advances a strategy's state machine.
That separation is the whole point: a panel that showed what the bot would do
by making it do something would be a different bot.

The one subtlety worth stating plainly. The bot decides on *closed* bars. A
panel refreshed every two seconds against the bar still forming can show every
gate green while nothing happens, which looks like a fault and is not one. So
two readings are produced -- ``provisional`` for the forming bar and
``confirmed`` for the last closed one -- and the page labels them differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from ..core.types import Side
from ..data.mtf import TIMEFRAME_MINUTES

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime only
    from .core import SymbolRuntime, TradeEngine

#: Candles sent to the page. Ten hours of M5: enough for the 200-EMA to mean
#: something on screen while each candle is still wide enough to read.
CHART_BARS = 120

#: Score points plotted in the history strip.
SCORE_HISTORY = 40


@dataclass(frozen=True, slots=True)
class GateReading:
    """One filter's verdict for one side."""

    name: str
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "reason": self.reason}


def _evaluate_sides(rt: SymbolRuntime, ctx: Any) -> dict[str, Any]:
    """Run the filter chain for both directions, purely to display it.

    The chain stops at its first failure, which is right for trading and wrong
    for a checklist -- you want to see every gate, not just the first one that
    objected. So each filter is asked individually here.
    """
    chain = getattr(rt.strategy, "filters", None)
    filters = getattr(chain, "filters", []) or []
    allowed = {s.upper() for s in rt.cfg.sides}
    out: dict[str, Any] = {}
    for side in (Side.LONG, Side.SHORT):
        if side.value not in allowed:
            out[side.value] = {"configured": False, "gates": [], "verdict": "not traded"}
            continue
        gates: list[GateReading] = []
        for f in filters:
            try:
                d = f.check(ctx, side)
                gates.append(GateReading(f.name, bool(d.passed), str(d.reason)))
            except Exception as exc:  # noqa: BLE001 - a display must not crash the bot
                gates.append(GateReading(f.name, False, f"could not evaluate: {exc}"))
        blocked = [g.name for g in gates if not g.passed]
        out[side.value] = {
            "configured": True,
            "gates": [g.to_dict() for g in gates],
            "verdict": "allowed" if not blocked else f"blocked by {', '.join(blocked)}",
            "blocked_by": blocked,
        }
    return out


def _next_close(last_ts: datetime, timeframe: str) -> dict[str, Any]:
    """When the next decision is due.

    ``last_ts`` is the open time of the last *closed* bar, so that bar's own
    close is already in the past -- counting down to it just showed zero. What
    the page wants is the close of the bar currently forming, which is the next
    interval boundary after now.
    """
    minutes = TIMEFRAME_MINUTES.get(timeframe.upper(), 5)
    step = timedelta(minutes=minutes)
    now = datetime.now(timezone.utc)
    closes_at = last_ts + step
    while closes_at <= now:
        closes_at += step
    return {
        "closes_at": closes_at.isoformat(),
        "seconds_left": max(0.0, (closes_at - now).total_seconds()),
        "timeframe": timeframe.upper(),
        "last_bar": last_ts.isoformat(),
    }


def _trigger_state(rt: SymbolRuntime) -> dict[str, Any]:
    """Whether a setup can even begin right now.

    Passing every filter is not the same as being about to trade, and the panel
    read as though it were. The strategy arms on the *moment* the fast EMAs
    cross; once they have crossed and stayed crossed there is nothing to act
    on, however green the gates look. This says which of the two is true.
    """
    confirm = (rt.ind.get("ema_confirm") or [])
    fast = (rt.ind.get("ema_fast") or [])
    if len(confirm) < 2 or len(fast) < 2:
        return {"ready": False, "note": "not enough history yet"}
    c0, f0 = confirm[-1], fast[-1]
    c1, f1 = confirm[-2], fast[-2]
    if None in (c0, f0, c1, f1):
        return {"ready": False, "note": "EMAs not ready yet"}
    above_now, above_prev = c0 > f0, c1 > f1
    crossed = above_now != above_prev
    side = "LONG" if above_now else "SHORT"
    if crossed:
        note = ("the 5-EMA just crossed "
                + ("above" if above_now else "below")
                + " the 8-EMA - a " + ("buy" if above_now else "sell")
                + " setup is being considered now")
    else:
        note = ("the 5-EMA is already " + ("above" if above_now else "below")
                + " the 8-EMA and has not just crossed, so no new setup can "
                + "start - it must cross back and then cross again")
    return {
        "ready": True, "crossed": crossed, "would_be": side, "note": note,
        "ema_confirm": c0, "ema_fast": f0,
    }


def chart_payload(engine: TradeEngine, journal: Any = None) -> dict[str, Any]:
    """Everything the chart and panel render, for every registered symbol."""
    out: dict[str, Any] = {}
    for sym, rt in engine.runtimes.items():
        if not rt.bars:
            continue
        bars = rt.bars[-CHART_BARS:]
        idx = len(rt.bars) - 1

        def series(name: str, ind: dict = rt.ind, n: int = len(bars)) -> list:
            values = ind.get(name) or []
            return list(values[-n:]) if values else []

        state = dict(rt.strategy.state_summary())
        quote = None
        try:
            q = engine.broker.quote(rt.cfg.symbol)
            if q:
                quote = {"bid": q[0], "ask": q[1], "mid": (q[0] + q[1]) / 2.0}
        except Exception:  # noqa: BLE001 - a missing quote is not an outage
            quote = None

        spread = 0.0
        try:
            spread = engine.broker.spread_points(rt.cfg.symbol)
        except Exception:  # noqa: BLE001
            spread = 0.0

        # Provisional: the bar in progress. Confirmed: the last one the bot
        # actually judged. Both, because either alone misleads.
        provisional = _evaluate_sides(rt, rt.context(idx, spread, None))
        confirmed = (
            _evaluate_sides(rt, rt.context(idx - 1, spread, None)) if idx >= 1 else {}
        )

        levels = {
            "trigger": state.get("trigger"),
            "failure": getattr(rt.strategy, "failure_level", None),
        }
        positions = []
        try:
            for p in engine.broker.positions(rt.cfg.symbol):
                positions.append({
                    "side": p.side.value if hasattr(p.side, "value") else str(p.side),
                    "entry": p.entry_price, "sl": p.sl, "tp": p.tp,
                    "volume": p.volume,
                })
        except Exception:  # noqa: BLE001
            positions = []

        out[sym] = {
            "symbol": rt.cfg.symbol,
            "timeframe": engine.config.engine.timeframe,
            "bars": [
                {
                    "ts": b.ts.isoformat(), "o": b.open, "h": b.high,
                    "l": b.low, "c": b.close, "v": b.volume,
                }
                for b in bars
            ],
            "ema": {
                "confirm": series("ema_confirm"),
                "fast": series("ema_fast"),
                "trend": series("ema_trend"),
            },
            "quote": quote,
            "spread_points": spread,
            "phase": state.get("phase"),
            "side": state.get("side"),
            "pullback_count": state.get("pullback_count"),
            "levels": levels,
            "positions": positions,
            "bar_clock": _next_close(bars[-1].ts, engine.config.engine.timeframe),
            "gates": {"provisional": provisional, "confirmed": confirmed},
            "trigger_state": _trigger_state(rt),
            "mtf": rt.mtf.to_dict() if len(rt.mtf) else None,
            "score": rt.last_score.to_dict() if rt.last_score else None,
            "digits": rt.spec.digits,
        }

        if journal is not None:
            out[sym]["markers"] = _markers(journal, rt.cfg.symbol, bars[0].ts)
            out[sym]["score_history"] = _score_history(journal, rt.cfg.symbol)
    return out


def _markers(journal: Any, symbol: str, since: datetime) -> list[dict[str, Any]]:
    """Past entries and exits inside the visible window."""
    try:
        rows = journal.conn.execute(
            """SELECT side, entry_price, exit_price, opened_at, closed_at, pnl
               FROM trades WHERE symbol = ? AND closed_at >= ?
               ORDER BY closed_at DESC LIMIT 40""",
            (symbol, since.isoformat()),
        ).fetchall()
    except Exception:  # noqa: BLE001 - the chart must survive a locked journal
        return []
    return [
        {
            "side": r["side"], "entry": r["entry_price"], "exit": r["exit_price"],
            "opened_at": r["opened_at"], "closed_at": r["closed_at"],
            "pnl": r["pnl"], "win": r["pnl"] > 0,
        }
        for r in rows
    ]


def _score_history(journal: Any, symbol: str) -> list[dict[str, Any]]:
    try:
        rows = journal.conn.execute(
            """SELECT ts, score, taken, outcome FROM observations
               WHERE symbol = ? AND score IS NOT NULL
               ORDER BY id DESC LIMIT ?""",
            (symbol, SCORE_HISTORY),
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [
        {"ts": r["ts"], "score": r["score"], "taken": bool(r["taken"]),
         "outcome": r["outcome"]}
        for r in reversed(rows)
    ]
