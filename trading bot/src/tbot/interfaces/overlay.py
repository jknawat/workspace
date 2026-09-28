"""Publish the bot's own state back to MetaTrader 5, for a chart overlay.

Stage 2 reads structure *from* MT5. This writes tbot's decisions *to* it, so
the chart can show both: the zones the library detected, and what the bot
actually did about them. Seeing an entry drawn on the same chart as the order
block it came from turns "why did it take that?" from a log-archaeology problem
into a glance.

The file is written to MT5's shared ``Common/Files`` folder, and the companion
indicator ``mql5/TbotOverlay.mq5`` reads it.

**Timestamps are converted back to broker time.** MQL5 places chart objects on
the terminal's own time axis; handing it UTC would draw every marker offset by
the server's offset. Everything inside tbot is UTC, and this is the one place
that converts the other way — mirroring the snapshot reader, which converts on
the way in.

Writes are atomic: a temp file in the same directory, then a replace. A
half-written file would make the indicator flicker or bail out.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..obs import log as obs_log

SCHEMA_VERSION = "1.0"


def _to_broker(ts: datetime | str | None, offset: timedelta) -> str | None:
    """UTC -> broker wall clock, formatted the way MQL5's StringToTime expects."""
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (ts.astimezone(timezone.utc) + offset).strftime("%Y.%m.%d %H:%M:%S")


class OverlayWriter:
    """Writes ``tbot_state.json`` for the chart indicator to read."""

    def __init__(
        self,
        directory: str | Path,
        broker_utc_offset_hours: float = 0.0,
        filename: str = "tbot_state.json",
    ) -> None:
        self.directory = Path(directory)
        self.offset = timedelta(hours=broker_utc_offset_hours)
        self.filename = filename
        self.log = obs_log.get("overlay")
        self.writes = 0

    @property
    def path(self) -> Path:
        return self.directory / self.filename

    def build(self, status: dict[str, Any]) -> dict[str, Any]:
        """Shape the runner's status dict into the overlay contract."""
        positions = []
        for p in status.get("positions", []):
            positions.append(
                {
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "volume": p.get("volume"),
                    "entry": p.get("entry"),
                    "sl": p.get("sl"),
                    "tp": p.get("tp"),
                    "pnl": p.get("pnl"),
                    "opened_at": _to_broker(p.get("opened_at"), self.offset),
                    "ticket": p.get("ticket"),
                }
            )
        phases = {
            symbol: {
                "phase": state.get("phase"),
                "side": state.get("side"),
                "zone": state.get("zone"),
                "last_reject": (state.get("last_reject") or "")[:120],
            }
            for symbol, state in (status.get("phases") or {}).items()
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "time_basis": "broker",
            "as_of": _to_broker(datetime.now(timezone.utc), self.offset),
            "mode": status.get("mode"),
            "paused": bool(status.get("paused")),
            "balance": status.get("balance"),
            "equity": status.get("equity"),
            "day_pnl": status.get("day_pnl"),
            "positions": positions,
            "phases": phases,
        }

    def write(self, status: dict[str, Any]) -> bool:
        """Publish one state file. Never raises: an overlay is not worth a crash."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.build(status), indent=1, default=str)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(payload, encoding="utf-8")
            os.replace(temp, self.path)  # atomic within the same directory
            self.writes += 1
            return True
        except OSError as exc:
            self.log.warning(
                "overlay write failed: %s", exc, extra={"event": "overlay_error"}
            )
            return False

    def on_status(self, status: dict[str, Any]) -> None:
        self.write(status)
