"""Open paper positions, across a restart.

A simulated position lives in memory inside the bot. Stopping while one is open
used to delete it: the trade never settled, never reached the journal, and the
balance kept the number it had before the trade opened. The record simply lost
a sample -- and not a random one, because losers hit their stop quickly while
winners run, so the trades most likely to be open at any moment are the ones
that were going well.

Restoring is not enough on its own. If the bot was off for three hours, the
stop may have been hit two hours ago, and bringing the position back as though
it were still live would be worse than losing it: the account would carry a
trade the market closed long ago. So anything restored is replayed against the
bars that passed while the bot was down, and settles at the price and time it
actually settled at.

Live mode needs none of this. The position sits at the broker, MetaTrader
enforces the stop and target with the bot off, and ``broker.positions()`` reads
it back on the next start.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..broker.base import ClosedTrade
from ..core.types import Position, Side

if TYPE_CHECKING:  # pragma: no cover
    from ..broker.paper import PaperBroker
    from ..journal import Journal

#: Journal key holding the open simulated positions.
KEY = "paper_positions"


def save(journal: Journal, broker: PaperBroker) -> None:
    """Write the open simulated positions down. Cheap enough to call often."""
    rows = [
        {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "side": p.side.value if hasattr(p.side, "value") else str(p.side),
            "volume": p.volume,
            "entry_price": p.entry_price,
            "sl": p.sl,
            "tp": p.tp,
            "opened_at": p.opened_at.isoformat(),
            "strategy": p.strategy,
        }
        for p in broker.positions()
    ]
    journal.set_state(KEY, json.dumps(rows))


def load(journal: Journal) -> list[dict[str, Any]]:
    raw = journal.get_state(KEY)
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def restore(broker: PaperBroker, rows: list[dict[str, Any]]) -> list[Position]:
    """Put saved positions back into the simulator.

    Ticket numbering continues above the restored ones, so a new trade cannot
    be handed a ticket that already belongs to a position carried over.
    """
    restored: list[Position] = []
    for r in rows:
        try:
            pos = Position(
                symbol=str(r["symbol"]),
                side=Side(str(r["side"])),
                volume=float(r["volume"]),
                entry_price=float(r["entry_price"]),
                sl=float(r["sl"]),
                tp=float(r["tp"]),
                opened_at=datetime.fromisoformat(str(r["opened_at"])),
                ticket=int(r["ticket"]),
                strategy=str(r.get("strategy", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue  # a malformed row must not stop the bot starting
        broker._positions[pos.ticket] = pos  # noqa: SLF001 - same package
        broker._next_ticket = max(broker._next_ticket, pos.ticket + 1)  # noqa: SLF001
        restored.append(pos)
    return restored


def settle_missed(
    broker: PaperBroker,
    positions: list[Position],
    bars_by_symbol: dict[str, list],
) -> list[ClosedTrade]:
    """Replay the bars that passed while the bot was down.

    Each bar goes through the simulator's own ``on_bar``, so a stop or target
    touched during the downtime closes at that level and that time -- the same
    path a live bar would take. Bars at or before the position's open time are
    skipped: they are history the trade has already lived through.
    """
    if not positions:
        return []
    closed: list[ClosedTrade] = []
    opened_at = {p.symbol: p.opened_at for p in positions}
    for symbol, bars in bars_by_symbol.items():
        since = opened_at.get(symbol)
        for bar in bars:
            if since is not None and bar.ts <= since:
                continue
            closed.extend(broker.on_bar(symbol, bar))
    return closed
