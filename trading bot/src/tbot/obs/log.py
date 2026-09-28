"""Structured logging.

Logs are JSON Lines, one object per event. Text logs force every later question
("how often did the atr filter reject XAUUSD?") to become a regex; a JSONL file
answers it with a one-line query. A human-readable console stream runs
alongside for live watching.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        symbol = getattr(record, "symbol", "")
        tag = f" [{symbol}]" if symbol else ""
        return f"{ts} {record.levelname[0]}{tag} {record.getMessage()}"


def setup(level: str = "INFO", file: str | Path | None = "logs/tbot.jsonl") -> logging.Logger:
    root = logging.getLogger("tbot")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    if file:
        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    return root


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"tbot.{name}")
