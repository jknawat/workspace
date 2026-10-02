"""A minimal event bus, so watchers never become part of the trading path.

The dashboard, the Telegram notifier and the MT5 chart overlay all want to know
what the engine is doing. None of them may influence it, and none of them may
break it: a Telegram outage or a wedged HTTP client must not stop a stop-loss
from being managed.

Two rules enforce that:

* **Subscriber exceptions are caught and logged, never propagated.** A watcher
  that throws gets a log line; the engine carries on.
* **Publishing is synchronous and cheap.** Subscribers are expected to hand
  work off (a queue, a buffer) rather than do it inline. The Telegram sender
  and the HTTP server both run on their own threads for exactly this reason.

This is deliberately not a message broker. One process, one direction, no
delivery guarantees -- anything that must be durable goes in the journal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..obs import log as obs_log

# Event kinds. Watchers may filter on these; unknown kinds must be ignored
# rather than treated as errors, so new ones can be added without breaking one.
SIGNAL = "signal"        # a strategy proposed a trade
DECLINED = "declined"    # the risk gate refused it
SCORED = "scored"        # a signal was rated, with the tier it earned
ORDER = "order"          # an order was sent (check data["ok"])
EXIT = "exit"            # an exit policy modified or closed a position
CLOSED = "closed"        # a position settled, with realised pnl
STATUS = "status"        # periodic heartbeat: balance, positions, phases
STARTED = "started"
STOPPED = "stopped"
ERROR = "error"


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    symbol: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "ts": self.ts.isoformat(),
            **self.data,
        }


Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[tuple[str, Subscriber]] = []
        self.log = obs_log.get("events")

    def subscribe(self, fn: Subscriber, name: str = "") -> None:
        self._subscribers.append((name or getattr(fn, "__name__", "subscriber"), fn))

    def __len__(self) -> int:
        return len(self._subscribers)

    def publish(self, kind: str, symbol: str = "", /, **data: Any) -> Event:
        """Publish an event. ``kind`` and ``symbol`` are positional-only.

        That slash matters: without it, a payload field called ``kind`` or
        ``symbol`` collides with these parameters and raises
        ``TypeError: got multiple values for argument`` -- at runtime, in the
        trading loop, on whichever event happened to carry that key.
        """
        event = Event(kind=kind, symbol=symbol, data=data)
        for name, fn in self._subscribers:
            try:
                fn(event)
            except Exception as exc:  # noqa: BLE001 - a watcher must never stop trading
                self.log.error(
                    "event subscriber %s failed on %s: %s",
                    name, kind, exc,
                    extra={"event": "subscriber_error", "subscriber": name},
                )
        return event

# A plain-language decision line for every bar, signal or not: the dashboard
# and journal both need an answer to "why buy, why sell, why wait".
DECISION = "decision"
